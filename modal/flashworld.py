from __future__ import annotations

import json
import os
import subprocess
import uuid
import base64
import io
from pathlib import Path
from typing import Any

import modal
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse

APP_NAME = "flashworld-modal"
REPO_URL = "https://github.com/imlixinyang/FlashWorld.git"
REPO_DIR = Path("/opt/FlashWorld")
RUNS_DIR = Path("/data/runs")

app = modal.App(APP_NAME)
flash_volume = modal.Volume.from_name("flashworld-artifacts", create_if_missing=True)

# FlashWorld needs CUDA devel image for compiling gsplat and spz from source.
# Every dependency is pinned exactly as the upstream repo requires.
image = (
    modal.Image.from_registry(
        "nvidia/cuda:12.4.1-devel-ubuntu22.04",
        add_python="3.10",
    )
    .apt_install(
        "git",
        "wget",
        "cmake",
        "build-essential",
        "ninja-build",
        "ffmpeg",
        "libgl1",
        "libglib2.0-0",
        "pkg-config",
        "libavformat-dev",
        "libavcodec-dev",
        "libavdevice-dev",
        "libavutil-dev",
        "libavfilter-dev",
        "libswscale-dev",
        "libswresample-dev",
    )
    # Step 1: PyTorch stack pinned to upstream requirements.txt
    .pip_install(
        "torch==2.6.0",
        "torchvision==0.21.0",
        extra_index_url="https://download.pytorch.org/whl/cu124",
    )
    # Step 2: Clone repo first so we have the models/ package available
    .run_commands(
        f"git clone --depth 1 {REPO_URL} {REPO_DIR}",
    )
    # Step 3: All pinned pip dependencies from requirements.txt
    .pip_install(
        "triton==3.2.0",
        "transformers==4.57.0",
        "omegaconf==2.3.0",
        "ninja==1.13.0",
        "numpy==2.2.6",
        "einops==0.8.1",
        "moviepy==1.0.3",
        "opencv-python==4.12.0.88",
        "av==15.1.0",
        "plyfile==1.1.2",
        "ftfy==6.3.1",
        "accelerate==1.10.1",
        "nanobind==2.9.2",
        "uvicorn",
        "jaxtyping",
        "rich",
        "pandas",
        "Pillow",
        "imageio",
        "tqdm",
        "safetensors",
        "huggingface_hub",
        "gradio",
        "fastapi",
        "python-multipart",
    )
    # Step 4: Compile gsplat from the exact pinned commit (needs CUDA toolkit + torch)
    .run_commands(
        "TORCH_CUDA_ARCH_LIST='8.0;8.6;8.9;9.0+PTX' "
        "CUDA_HOME=/usr/local/cuda "
        "pip install --no-cache-dir --no-build-isolation "
        "git+https://github.com/nerfstudio-project/gsplat.git@32f2a54d21c7ecb135320bb02b136b7407ae5712",
        gpu="A100",
    )
    # Step 5: Install diffusers from exact pinned commit
    .pip_install(
        "git+https://github.com/huggingface/diffusers.git@447e8322f76efea55d4769cd67c372edbf0715b8",
    )
    # Step 6: Compile spz (Niantic gaussian splat codec) from exact pinned commit
    .run_commands(
        "pip install --no-cache-dir git+https://github.com/nianticlabs/spz.git@a4fc69e7948c7152e807e6501d73ddc9c149ce37",
    )
    # Step 7: Download the FlashWorld model checkpoint from HuggingFace
    .run_commands(
        "pip install --no-cache-dir huggingface_hub[cli]",
        "python3 -c \""
        "from huggingface_hub import hf_hub_download; "
        "hf_hub_download(repo_id='imlixinyang/FlashWorld', filename='model.ckpt')"
        "\"",
    )
)


class CommandError(RuntimeError):
    pass


def _run(command: list[str], cwd: Path | None = None) -> str:
    result = subprocess.run(
        command,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise CommandError(
            f"Command failed: {' '.join(command)}\n"
            f"exit_code={result.returncode}\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )
    return result.stdout


def _list_files(root: Path) -> list[str]:
    if not root.exists():
        return []
    return [str(p.relative_to(root)) for p in sorted(root.rglob("*")) if p.is_file()]


@app.function(
    image=image,
    gpu="A100-80GB",
    timeout=60 * 30,
    volumes={"/data": flash_volume},
)
def generate(
    text_prompt: str = "",
    image_b64: str | None = None,
    run_id: str | None = None,
    n_frame: int = 16,
    image_height: int = 480,
    image_width: int = 704,
    export_video: bool = True,
    export_spz: bool = True,
    export_ply: bool = False,
    video_fps: int = 15,
    offload_t5: bool = False,
) -> dict[str, Any]:
    """Generate a 3D scene from a text prompt and/or image using FlashWorld."""
    import sys
    sys.path.insert(0, str(REPO_DIR))

    import torch
    import numpy as np
    import time as _time
    from PIL import Image as PILImage
    from huggingface_hub.constants import HUGGINGFACE_HUB_CACHE

    # These imports come from the FlashWorld repo
    from utils import export_gaussians, sample_from_dense_cameras, normalize_cameras, create_raymaps
    from app import GenerationSystem

    run_id = run_id or uuid.uuid4().hex[:12]
    run_dir = RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    # Locate the model checkpoint
    ckpt_path = os.path.join(
        HUGGINGFACE_HUB_CACHE,
        "models--imlixinyang--FlashWorld",
        "snapshots",
        "6a8e88c6f88678ac098e4c82675f0aee555d6e5d",
        "model.ckpt",
    )
    if not os.path.exists(ckpt_path):
        from huggingface_hub import hf_hub_download
        hf_hub_download(repo_id="imlixinyang/FlashWorld", filename="model.ckpt")

    # Initialize the generation system
    device = torch.device("cuda")
    print("Initializing GenerationSystem...")
    generation_system = GenerationSystem(
        ckpt_path=ckpt_path,
        device=device,
        offload_t5=offload_t5,
    )
    print("GenerationSystem initialized!")

    # Process image input if provided
    image_tensor = None
    if image_b64:
        image_bytes = base64.b64decode(image_b64)
        pil_image = PILImage.open(io.BytesIO(image_bytes)).convert("RGB")

        w, h = pil_image.size
        if image_height / h > image_width / w:
            scale = image_height / h
        else:
            scale = image_width / w

        new_h = int(image_height / scale)
        new_w = int(image_width / scale)

        pil_image = pil_image.crop((
            (w - new_w) // 2, (h - new_h) // 2,
            new_w + (w - new_w) // 2, new_h + (h - new_h) // 2,
        )).resize((image_width, image_height))

        image_tensor = torch.from_numpy(np.array(pil_image)).float().permute(2, 0, 1) / 255.0 * 2 - 1

    # Build default orbit cameras (simple circular orbit like the examples)
    cameras = _build_orbit_cameras(n_frame, image_height, image_width, device)

    video_path = str(run_dir / "video.mp4") if export_video else None

    start = _time.time()
    scene_params, ref_w2c, T_norm = generation_system.generate(
        cameras,
        n_frame,
        image=image_tensor,
        text=text_prompt,
        image_index=0,
        image_height=image_height,
        image_width=image_width,
        video_path=video_path,
        video_fps=video_fps,
    )
    elapsed = _time.time() - start
    print(f"Generation took {elapsed:.2f}s")

    scene_params = scene_params.detach().cpu()

    # Export gaussians
    spz_path = str(run_dir / "gaussians.spz") if export_spz else None
    ply_path = str(run_dir / "gaussians.ply") if export_ply else None
    export_gaussians(
        scene_params,
        opacity_threshold=0.00025,
        T_norm=T_norm,
        spz_path=spz_path,
        ply_path=ply_path,
    )

    files = _list_files(run_dir)
    flash_volume.commit()

    return {
        "run_id": run_id,
        "run_dir": str(run_dir),
        "files": files,
        "generation_time_seconds": round(elapsed, 2),
    }


def _build_orbit_cameras(
    n_frame: int,
    image_height: int,
    image_width: int,
    device: str | object = "cuda",
) -> "torch.Tensor":
    """Build a simple orbit camera trajectory (like the FlashWorld examples)."""
    import torch
    import math

    cameras = []
    fx = 500.0
    fy = 500.0
    cx = image_width / 2.0
    cy = image_height / 2.0

    for i in range(n_frame):
        angle = 2.0 * math.pi * i / n_frame
        # Simple orbit: rotate around Y axis
        half_angle = angle / 2.0
        # Quaternion for rotation around Y axis: [cos(a/2), 0, sin(a/2), 0]
        qw = math.cos(half_angle)
        qx = 0.0
        qy = math.sin(half_angle)
        qz = 0.0
        # Position on a circle
        radius = 5.0
        px = radius * math.sin(angle)
        py = 0.0
        pz = radius * math.cos(angle)

        cameras.append([qw, qx, qy, qz, px, py, pz,
                        fx / image_width, fy / image_height,
                        cx / image_width, cy / image_height])

    return torch.tensor(cameras, dtype=torch.float32, device=device)


@app.function(image=image, volumes={"/data": flash_volume})
@modal.asgi_app()
def viewer() -> FastAPI:
    """Serve generated artifacts (videos, splats, plys) over HTTP."""
    api = FastAPI(title="FlashWorld Artifact Viewer")

    @api.get("/")
    def root() -> JSONResponse:
        run_ids = sorted(p.name for p in RUNS_DIR.glob("*") if p.is_dir())
        return JSONResponse({"runs": run_ids})

    @api.get("/runs/{run_id}")
    def list_run(run_id: str) -> JSONResponse:
        run_dir = RUNS_DIR / run_id
        if not run_dir.exists():
            raise HTTPException(status_code=404, detail="run_id not found")
        return JSONResponse({"run_id": run_id, "files": _list_files(run_dir)})

    @api.get("/runs/{run_id}/file")
    def get_file(run_id: str, path: str) -> FileResponse:
        run_dir = (RUNS_DIR / run_id).resolve()
        if not run_dir.exists():
            raise HTTPException(status_code=404, detail="run_id not found")
        target = (run_dir / path).resolve()
        if not str(target).startswith(str(run_dir)):
            raise HTTPException(status_code=400, detail="invalid path")
        if not target.exists() or not target.is_file():
            raise HTTPException(status_code=404, detail="file not found")
        return FileResponse(target)

    return api


@app.local_entrypoint()
def main(
    prompt: str = "",
    image_path: str = "",
    export_video: bool = True,
    export_spz: bool = True,
    export_ply: bool = False,
    video_fps: int = 15,
    offload_t5: bool = False,
) -> None:
    image_b64 = None
    if image_path:
        p = Path(image_path)
        image_b64 = base64.b64encode(p.read_bytes()).decode("utf-8")

    result = generate.remote(
        text_prompt=prompt,
        image_b64=image_b64,
        export_video=export_video,
        export_spz=export_spz,
        export_ply=export_ply,
        video_fps=video_fps,
        offload_t5=offload_t5,
    )
    print(json.dumps(result, indent=2))
    print("\nDeploy viewer with: modal deploy modal/flashworld.py")
