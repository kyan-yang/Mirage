from __future__ import annotations

import json
import os
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Any, Iterable

import modal
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from huggingface_hub import login as hf_login

APP_NAME = "hunyuanworld-modal"
REPO_URL = "https://github.com/Tencent-Hunyuan/HunyuanWorld-1.0.git"
REPO_DIR = Path("/opt/HunyuanWorld-1.0")
RUNS_DIR = Path("/data/runs")

app = modal.App(APP_NAME)
world_volume = modal.Volume.from_name("hunyuanworld-artifacts", create_if_missing=True)

image = (
    modal.Image.from_registry(
        "nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04",
        add_python="3.10",
    )
    .apt_install(
        "git",
        "wget",
        "cmake",
        "build-essential",
        "ffmpeg",
        "libgl1",
        "libglib2.0-0",
    )
    .pip_install(
        "torch==2.5.0",
        "torchvision==0.20.0",
        "torchaudio==2.5.0",
        extra_index_url="https://download.pytorch.org/whl/cu124",
    )
    .pip_install(
        "huggingface_hub[cli]",
        "transformers==4.51.0",
        "diffusers==0.34.0",
        "accelerate==1.6.0",
        "tokenizers==0.21.1",
        "safetensors==0.5.3",
        "sentencepiece==0.2.0",
        "peft==0.15.0",
        "einops==0.4.1",
        "timm==1.0.13",
        "opencv-python==4.11.0.86",
        "opencv-python-headless==4.11.0.86",
        "scikit-image==0.24.0",
        "imageio==2.37.0",
        "imageio-ffmpeg==0.4.9",
        "onnx==1.17.0",
        "onnxruntime-gpu==1.21.1",
        "open3d>=0.18.0",
        "trimesh>=4.6.1",
        "xformers==0.0.28.post2",
        "fastapi",
        "uvicorn",
        "python-multipart",
    )
    .run_commands(
        f"git clone {REPO_URL} {REPO_DIR}",
        # Official docs recommend conda; this pip fallback is for Modal image builds.
        f"if [ -f {REPO_DIR}/requirements.txt ]; then pip install -r {REPO_DIR}/requirements.txt; fi",
        # Real-ESRGAN dependency chain used by scene generation.
        "git clone https://github.com/xinntao/Real-ESRGAN.git /opt/Real-ESRGAN",
        "pip install basicsr-fixed facexlib gfpgan",
        "if [ -f /opt/Real-ESRGAN/requirements.txt ]; then pip install -r /opt/Real-ESRGAN/requirements.txt; fi",
        "cd /opt/Real-ESRGAN && python setup.py develop",
        # ZIM dependencies used by semantic layering in the pipeline.
        "git clone https://github.com/naver-ai/ZIM.git /opt/ZIM",
        "cd /opt/ZIM && pip install -e .",
        "mkdir -p /opt/ZIM/zim_vit_l_2092",
        "wget -q -O /opt/ZIM/zim_vit_l_2092/encoder.onnx https://huggingface.co/naver-iv/zim-anything-vitl/resolve/main/zim_vit_l_2092/encoder.onnx",
        "wget -q -O /opt/ZIM/zim_vit_l_2092/decoder.onnx https://huggingface.co/naver-iv/zim-anything-vitl/resolve/main/zim_vit_l_2092/decoder.onnx",
    )
)


class CommandError(RuntimeError):
    pass


def _run(command: list[str], cwd: Path | None = None) -> None:
    result = subprocess.run(
        command,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise CommandError(
            "\n".join(
                [
                    f"Command failed: {' '.join(command)}",
                    f"exit_code={result.returncode}",
                    "stdout:",
                    result.stdout,
                    "stderr:",
                    result.stderr,
                ]
            )
        )


def _list_files(root: Path) -> list[str]:
    if not root.exists():
        return []

    out: list[str] = []
    for p in sorted(root.rglob("*")):
        if p.is_file():
            out.append(str(p.relative_to(root)))
    return out


def _safe_mkdir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _join_labels(labels: Iterable[str] | None) -> list[str]:
    if not labels:
        return []
    return [label for label in labels if label.strip()]


def _login_hf(token: str) -> None:
    # Prefer Python API because CLI executable name differs across versions.
    try:
        hf_login(token=token, add_to_git_credential=False)
        return
    except Exception:
        pass

    hf_cli = shutil.which("hf")
    if hf_cli:
        _run([hf_cli, "auth", "login", "--token", token])
        return

    huggingface_cli = shutil.which("huggingface-cli")
    if huggingface_cli:
        _run([huggingface_cli, "login", "--token", token])
        return

    raise RuntimeError("No Hugging Face login method available in container")


@app.function(
    image=image,
    gpu="A100-80GB",
    timeout=60 * 60,
    volumes={"/data": world_volume},
    secrets=[modal.Secret.from_name("huggingface-token")],
)
def generate_world(
    prompt: str = "",
    image_bytes: bytes | None = None,
    image_filename: str = "input.png",
    run_id: str | None = None,
    classes: str = "outdoor",
    labels_fg1: list[str] | None = None,
    labels_fg2: list[str] | None = None,
    fp8_gemm: bool = False,
    fp8_attention: bool = False,
    cache: bool = False,
) -> dict[str, Any]:
    if not prompt and image_bytes is None:
        raise ValueError("Provide either prompt or image_bytes")

    run_id = run_id or uuid.uuid4().hex[:12]
    run_dir = RUNS_DIR / run_id
    _safe_mkdir(run_dir)

    # Ensure HF auth is available for checkpoint download.
    hf_token = os.environ.get("HUGGINGFACE_TOKEN")
    if hf_token:
        _login_hf(hf_token)

    panogen_args = [
        "python3",
        str(REPO_DIR / "demo_panogen.py"),
        "--prompt",
        prompt,
        "--output_path",
        str(run_dir),
    ]

    if image_bytes is not None:
        image_path = run_dir / image_filename
        image_path.write_bytes(image_bytes)
        panogen_args += ["--image_path", str(image_path)]

    if fp8_gemm:
        panogen_args.append("--fp8_gemm")
    if fp8_attention:
        panogen_args.append("--fp8_attention")
    if cache:
        panogen_args.append("--cache")

    _run(panogen_args, cwd=REPO_DIR)

    panorama_path = run_dir / "panorama.png"
    if not panorama_path.exists():
        raise FileNotFoundError(f"Expected panorama output at {panorama_path}")

    scenegen_args = [
        "python3",
        str(REPO_DIR / "demo_scenegen.py"),
        "--image_path",
        str(panorama_path),
        "--classes",
        classes,
        "--output_path",
        str(run_dir),
    ]

    for lbl in _join_labels(labels_fg1):
        scenegen_args += ["--labels_fg1", lbl]
    for lbl in _join_labels(labels_fg2):
        scenegen_args += ["--labels_fg2", lbl]

    if fp8_gemm:
        scenegen_args.append("--fp8_gemm")
    if fp8_attention:
        scenegen_args.append("--fp8_attention")
    if cache:
        scenegen_args.append("--cache")

    env = os.environ.copy()
    env["CUDA_VISIBLE_DEVICES"] = "0"
    result = subprocess.run(
        scenegen_args,
        cwd=str(REPO_DIR),
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    if result.returncode != 0:
        raise CommandError(
            "\n".join(
                [
                    "demo_scenegen.py failed",
                    f"exit_code={result.returncode}",
                    "stdout:",
                    result.stdout,
                    "stderr:",
                    result.stderr,
                ]
            )
        )

    # Copy modelviewer into each run folder for self-contained serving.
    viewer_src = REPO_DIR / "modelviewer.html"
    if viewer_src.exists():
        shutil.copy2(viewer_src, run_dir / "modelviewer.html")

    files = _list_files(run_dir)
    world_volume.commit()

    return {
        "run_id": run_id,
        "run_dir": str(run_dir),
        "files": files,
    }


@app.function(image=image, volumes={"/data": world_volume})
@modal.asgi_app()
def viewer() -> FastAPI:
    api = FastAPI(title="HunyuanWorld Artifact Viewer")

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
    classes: str = "outdoor",
    labels_fg1: str = "",
    labels_fg2: str = "",
    fp8_gemm: bool = False,
    fp8_attention: bool = False,
    cache: bool = False,
) -> None:
    image_bytes = None
    image_filename = "input.png"

    if image_path:
        p = Path(image_path)
        image_bytes = p.read_bytes()
        image_filename = p.name

    result = generate_world.remote(
        prompt=prompt,
        image_bytes=image_bytes,
        image_filename=image_filename,
        classes=classes,
        labels_fg1=[x.strip() for x in labels_fg1.split(",") if x.strip()],
        labels_fg2=[x.strip() for x in labels_fg2.split(",") if x.strip()],
        fp8_gemm=fp8_gemm,
        fp8_attention=fp8_attention,
        cache=cache,
    )
    print(json.dumps(result, indent=2))
    print("Deploy viewer with: modal deploy modal_hunyuanworld.py")
