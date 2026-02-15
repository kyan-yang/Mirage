from __future__ import annotations

import json
import os
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Any

import modal
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from huggingface_hub import login as hf_login

APP_NAME = "hunyuanworld-mirror-modal"
REPO_URL = "https://github.com/Tencent-Hunyuan/HunyuanWorld-Mirror.git"
REPO_DIR = Path("/opt/HunyuanWorld-Mirror")
RUNS_DIR = Path("/data/runs")
HF_CACHE_DIR = Path("/cache/hf")

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
VIDEO_EXTS = {".mp4", ".avi", ".mov", ".webm", ".gif"}

app = modal.App(APP_NAME)
artifacts_volume = modal.Volume.from_name(
    "hunyuanworld-mirror-artifacts",
    create_if_missing=True,
)
weights_volume = modal.Volume.from_name(
    "hunyuanworld-mirror-weights",
    create_if_missing=True,
)

image = (
    modal.Image.from_registry(
        "nvidia/cuda:12.4.1-devel-ubuntu22.04",
        add_python="3.10",
    )
    .apt_install(
        "git",
        "ffmpeg",
        "cmake",
        "build-essential",
        "libgl1",
        "libglib2.0-0",
    )
    .pip_install(
        "torch==2.4.0",
        "torchvision==0.19.0",
        "torchaudio==2.4.0",
        extra_index_url="https://download.pytorch.org/whl/cu124",
    )
    .run_commands(
        "python3 -m pip install --upgrade pip",
        f"git clone --recursive --depth 1 {REPO_URL} {REPO_DIR}",
        (
            "python3 -m pip install --no-cache-dir "
            "--extra-index-url https://docs.gsplat.studio/whl/pt24cu124 "
            f"-r {REPO_DIR}/requirements.txt"
        ),
        (
            "python3 -m pip install --no-cache-dir gsplat "
            "--index-url https://docs.gsplat.studio/whl/pt24cu124"
        ),
        # infer.py imports onnxruntime directly; keep this explicit so build is deterministic.
        "python3 -m pip install --no-cache-dir onnxruntime==1.19.2",
        "python3 -c \"import onnxruntime; print('onnxruntime-ok')\"",
        "python3 -m pip install --no-cache-dir huggingface_hub[cli] fastapi uvicorn python-multipart",
    )
)


class CommandError(RuntimeError):
    pass


def _run(command: list[str], cwd: Path | None = None, env: dict[str, str] | None = None) -> str:
    result = subprocess.run(
        command,
        cwd=str(cwd) if cwd else None,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        return result.stdout

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


def _safe_mkdir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _list_files(root: Path) -> list[str]:
    if not root.exists():
        return []

    return [
        str(p.relative_to(root))
        for p in sorted(root.rglob("*"))
        if p.is_file()
    ]


def _login_hf(token: str) -> None:
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


def _write_input_images(image_payloads: list[tuple[str, bytes]], input_dir: Path) -> None:
    if not image_payloads:
        raise ValueError("image_payloads is empty")
    _safe_mkdir(input_dir)

    for name, data in sorted(image_payloads, key=lambda x: x[0].lower()):
        suffix = Path(name).suffix.lower()
        if suffix not in IMAGE_EXTS:
            raise ValueError(f"Unsupported image type: {name}")
        (input_dir / Path(name).name).write_bytes(data)


def _default_hf_env(base_env: dict[str, str]) -> dict[str, str]:
    env = dict(base_env)
    env["HF_HOME"] = str(HF_CACHE_DIR)
    env["HUGGINGFACE_HUB_CACHE"] = str(HF_CACHE_DIR / "hub")
    env["TRANSFORMERS_CACHE"] = str(HF_CACHE_DIR / "transformers")
    env["TORCH_HOME"] = str(HF_CACHE_DIR / "torch")
    return env


def _find_artifact_path(run_dir: Path, filename: str) -> Path | None:
    # Some infer.py codepaths write directly to run_dir, others under a nested folder.
    direct = run_dir / filename
    if direct.exists():
        return direct

    nested_common = run_dir / "inputs" / filename
    if nested_common.exists():
        return nested_common

    matches = sorted(p for p in run_dir.rglob(filename) if p.is_file())
    if matches:
        return matches[0]
    return None


@app.function(
    image=image,
    gpu="H100",
    timeout=60 * 60,
    volumes={"/data": artifacts_volume, "/cache": weights_volume},
)
def generate_world(
    image_payloads: list[tuple[str, bytes]] | None = None,
    video_bytes: bytes | None = None,
    video_filename: str = "input.mp4",
    run_id: str | None = None,
    fps: int = 1,
    target_size: int = 518,
    confidence_percentile: float = 0.0,
    save_gs: bool = True,
    save_colmap: bool = False,
) -> dict[str, Any]:
    if image_payloads is None and video_bytes is None:
        raise ValueError("Provide either image_payloads or video_bytes")

    run_id = run_id or uuid.uuid4().hex[:12]
    run_dir = RUNS_DIR / run_id
    _safe_mkdir(run_dir)
    _safe_mkdir(HF_CACHE_DIR / "hub")
    _safe_mkdir(HF_CACHE_DIR / "transformers")
    _safe_mkdir(HF_CACHE_DIR / "torch")

    input_path: Path
    if image_payloads is not None:
        input_dir = run_dir / "inputs"
        _write_input_images(image_payloads, input_dir)
        input_path = input_dir
    else:
        suffix = Path(video_filename).suffix.lower()
        if suffix not in VIDEO_EXTS:
            raise ValueError(f"Unsupported video type: {video_filename}")
        input_path = run_dir / Path(video_filename).name
        input_path.write_bytes(video_bytes or b"")

    hf_token = os.environ.get("HUGGINGFACE_TOKEN")
    if hf_token:
        _login_hf(hf_token)

    infer_args = [
        "python3",
        str(REPO_DIR / "infer.py"),
        "--input_path",
        str(input_path),
        "--output_path",
        str(run_dir),
        "--fps",
        str(fps),
        "--target_size",
        str(target_size),
        "--confidence_percentile",
        str(confidence_percentile),
    ]
    if save_gs:
        infer_args.append("--save_gs")
    if save_colmap:
        infer_args.append("--save_colmap")
    _run(infer_args, cwd=REPO_DIR, env=_default_hf_env(os.environ))

    gaussians_ply = _find_artifact_path(run_dir, "gaussians.ply")
    if save_gs and gaussians_ply is None:
        raise FileNotFoundError(
            "infer.py finished but gaussians.ply was not produced. "
            f"Run files: {_list_files(run_dir)}"
        )

    artifacts_volume.commit()
    weights_volume.commit()

    return {
        "run_id": run_id,
        "run_dir": str(run_dir),
        "gaussians_ply": str(gaussians_ply.relative_to(run_dir)) if gaussians_ply else None,
        "files": _list_files(run_dir),
    }


@app.function(
    image=image,
    volumes={"/data": artifacts_volume},
)
@modal.asgi_app()
def viewer() -> FastAPI:
    api = FastAPI(title="HunyuanWorld-Mirror Artifact Viewer")

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
    input_dir: str = "",
    video_path: str = "",
    fps: int = 1,
    target_size: int = 518,
    confidence_percentile: float = 0.0,
    conf_threshold: float = 0.0,
    save_gs: bool = True,
    save_colmap: bool = False,
) -> None:
    if not input_dir and not video_path:
        raise ValueError("Provide --input-dir (multi-image) or --video-path")
    if input_dir and video_path:
        raise ValueError("Provide only one of --input-dir or --video-path")

    image_payloads: list[tuple[str, bytes]] | None = None
    video_bytes: bytes | None = None
    video_filename = "input.mp4"

    if input_dir:
        src = Path(input_dir)
        if not src.exists() or not src.is_dir():
            raise ValueError(f"input_dir is not a directory: {input_dir}")
        files = [
            p
            for p in sorted(src.iterdir())
            if p.is_file() and p.suffix.lower() in IMAGE_EXTS
        ]
        if not files:
            raise ValueError(f"No supported image files found in {input_dir}")
        image_payloads = [(p.name, p.read_bytes()) for p in files]
    else:
        src = Path(video_path)
        if not src.exists() or not src.is_file():
            raise ValueError(f"video_path is not a file: {video_path}")
        if src.suffix.lower() not in VIDEO_EXTS:
            raise ValueError(f"Unsupported video type: {video_path}")
        video_bytes = src.read_bytes()
        video_filename = src.name

    result = generate_world.remote(
        image_payloads=image_payloads,
        video_bytes=video_bytes,
        video_filename=video_filename,
        fps=fps,
        target_size=target_size,
        confidence_percentile=confidence_percentile if confidence_percentile != 0.0 else conf_threshold,
        save_gs=save_gs,
        save_colmap=save_colmap,
    )
    print(json.dumps(result, indent=2))
    print("Deploy viewer with: modal deploy modal/world-mirror.py")
