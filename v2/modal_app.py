"""
World Mirror v2 — Clean 3D world generation from any address.

Usage:
    # Generate from address
    modal run v2/modal_app.py --address "Stanford Main Quad"

    # Generate from coordinates
    modal run v2/modal_app.py --lat 37.4260 --lng -122.1672

    # Generate from local images
    modal run v2/modal_app.py --input-dir ./my-photos

    # Generate route with parallel processing (4 GPU instances)
    modal run v2/modal_app.py --lat 30.2885 --lng -97.7275 \
        --end-lat 30.2900 --end-lng -97.7262 --parallel --num-chunks 4

    # Generate with multiple GPUs on single instance
    modal run v2/modal_app.py --address "Stanford" --num-gpus 4

    # Deploy viewer
    modal deploy v2/modal_app.py
"""

from __future__ import annotations

import json
import os
import subprocess
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import quote

import modal
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

APP_NAME = "world-mirror-v2"
REPO_URL = "https://github.com/Tencent-Hunyuan/HunyuanWorld-Mirror.git"
REPO_DIR = Path("/opt/HunyuanWorld-Mirror")
RUNS_DIR = Path("/data/runs")
HF_CACHE_DIR = Path("/cache/hf")

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
VIDEO_EXTS = {".mp4", ".avi", ".mov", ".webm", ".gif"}
SPLAT_VIEW_EXTS = {".splat", ".ply", ".ksplat"}
WEB_PREVIEW_FILENAME = "gaussians_web_preview.ply"
DEFAULT_WEB_MAX_SPLATS = 200_000

SPLAT_VIEWER_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>World Mirror | __RUN_ID__</title>
  <style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    html, body { width: 100%; height: 100%; background: linear-gradient(135deg, #0a0c12 0%, #1a1c2e 100%); color: #f2f4f8; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; overflow: hidden; }

    .container { display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100vh; padding: 40px; text-align: center; }

    h1 { font-size: 42px; font-weight: 700; margin-bottom: 12px; background: linear-gradient(135deg, #60a5fa 0%, #a78bfa 100%); -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text; }

    .run-id { font-size: 14px; color: #9ca3af; font-family: 'SF Mono', Monaco, monospace; margin-bottom: 40px; padding: 8px 16px; background: rgba(255,255,255,0.05); border-radius: 8px; display: inline-block; }

    .card { background: rgba(255,255,255,0.08); backdrop-filter: blur(20px); border: 1px solid rgba(255,255,255,0.1); border-radius: 16px; padding: 40px; max-width: 700px; box-shadow: 0 20px 60px rgba(0,0,0,0.3); }

    h2 { font-size: 24px; margin-bottom: 20px; color: #e5e7eb; }

    .viewer-options { display: flex; flex-direction: column; gap: 16px; margin: 32px 0; }

    .option-btn { display: flex; align-items: center; gap: 16px; padding: 20px 24px; background: linear-gradient(135deg, #3b82f6 0%, #8b5cf6 100%); border: none; border-radius: 12px; color: white; font-size: 16px; font-weight: 600; cursor: pointer; text-decoration: none; transition: all 0.2s; box-shadow: 0 4px 12px rgba(59, 130, 246, 0.3); }

    .option-btn:hover { transform: translateY(-2px); box-shadow: 0 6px 20px rgba(59, 130, 246, 0.4); }

    .option-btn.secondary { background: rgba(255,255,255,0.1); box-shadow: none; }

    .option-btn.secondary:hover { background: rgba(255,255,255,0.15); box-shadow: 0 4px 12px rgba(255,255,255,0.1); }

    .icon { font-size: 28px; }

    .option-text { flex: 1; text-align: left; }

    .option-title { font-size: 16px; font-weight: 600; margin-bottom: 4px; }

    .option-desc { font-size: 13px; opacity: 0.8; font-weight: 400; }

    .desktop-apps { margin-top: 32px; padding-top: 32px; border-top: 1px solid rgba(255,255,255,0.1); }

    .desktop-apps h3 { font-size: 18px; margin-bottom: 16px; color: #e5e7eb; }

    .app-links { display: flex; gap: 12px; justify-content: center; flex-wrap: wrap; }

    .app-link { padding: 10px 18px; background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.1); border-radius: 8px; color: #60a5fa; text-decoration: none; font-size: 14px; transition: all 0.2s; }

    .app-link:hover { background: rgba(255,255,255,0.1); border-color: #60a5fa; }

    .modes { margin-top: 24px; font-size: 13px; color: #9ca3af; }

    .modes a { color: #60a5fa; text-decoration: none; }

    .modes a:hover { text-decoration: underline; }
  </style>
</head>
<body>
  <div class="container">
    <h1>🌍 World Mirror</h1>
    <div class="run-id">__RUN_ID__</div>

    <div class="card">
      <h2>Choose Your Viewer</h2>
      <p style="color: #9ca3af; margin-bottom: 20px; font-size: 14px;">
        Web viewers can be slow for large splats. For best performance, use desktop apps!
      </p>

      <div class="viewer-options">
        <a href="https://antimatter15.com/splat/?url=__FILE_URL_ENCODED__" target="_blank" class="option-btn">
          <span class="icon">⚡</span>
          <div class="option-text">
            <div class="option-title">Fast Web Viewer</div>
            <div class="option-desc">antimatter15/splat - optimized WebGL renderer</div>
          </div>
        </a>

        <a href="https://playcanvas.com/supersplat/editor?assetUrl=__FILE_URL_ENCODED__" target="_blank" class="option-btn">
          <span class="icon">🎮</span>
          <div class="option-text">
            <div class="option-title">SuperSplat Editor</div>
            <div class="option-desc">Professional viewer with editing tools</div>
          </div>
        </a>

        <a href="__FILE_URL__" class="option-btn secondary">
          <span class="icon">⬇️</span>
          <div class="option-text">
            <div class="option-title">Download PLY</div>
            <div class="option-desc">Use with desktop apps (recommended for large files)</div>
          </div>
        </a>
      </div>

      <div class="desktop-apps">
        <h3>🖥️ Recommended Desktop Viewers</h3>
        <div class="app-links">
          <a href="https://github.com/antimatter15/splat" target="_blank" class="app-link">Splat (Mac/Win/Linux)</a>
          <a href="https://repo-sam.inria.fr/fungraph/3d-gaussian-splatting/" target="_blank" class="app-link">SIBR Viewer</a>
          <a href="https://github.com/playcanvas/supersplat" target="_blank" class="app-link">SuperSplat Desktop</a>
          <a href="https://poly.cam/" target="_blank" class="app-link">Polycam</a>
        </div>
      </div>

      <div class="modes">
        Current mode: __MODE_LABEL__ |
        <a href="__PREVIEW_URL__">fast preview</a> •
        <a href="__FULL_URL__">full quality</a>
      </div>
    </div>
  </div>
</body>
</html>"""

# ---------------------------------------------------------------------------
# Modal app setup
# ---------------------------------------------------------------------------

app = modal.App(APP_NAME)
artifacts_volume = modal.Volume.from_name("world-mirror-v2-artifacts", create_if_missing=True)
weights_volume = modal.Volume.from_name("world-mirror-v2-weights", create_if_missing=True)

image = (
    modal.Image.from_registry("nvidia/cuda:12.4.1-devel-ubuntu22.04", add_python="3.10")
    .apt_install("git", "ffmpeg", "cmake", "build-essential", "libgl1", "libglib2.0-0")
    .pip_install("torch==2.4.0", "torchvision==0.19.0", "torchaudio==2.4.0", extra_index_url="https://download.pytorch.org/whl/cu124")
    .run_commands(
        "python3 -m pip install --upgrade pip",
        f"git clone --recursive --depth 1 {REPO_URL} {REPO_DIR}",
        f"python3 -m pip install --no-cache-dir --extra-index-url https://docs.gsplat.studio/whl/pt24cu124 -r {REPO_DIR}/requirements.txt",
        "python3 -m pip install --no-cache-dir gsplat --index-url https://docs.gsplat.studio/whl/pt24cu124",
        "python3 -m pip install --no-cache-dir onnxruntime==1.19.2",
        "python3 -m pip install --no-cache-dir plyfile",
        "python3 -m pip install --no-cache-dir huggingface_hub[cli] fastapi uvicorn python-multipart",
    )
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class CommandError(RuntimeError):
    pass


def _run(command: list[str], cwd: Path | None = None, env: dict[str, str] | None = None) -> str:
    result = subprocess.run(command, cwd=str(cwd) if cwd else None, env=env, capture_output=True, text=True, check=False)
    if result.returncode == 0:
        return result.stdout
    raise CommandError(f"Command failed: {' '.join(command)}\nexit={result.returncode}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}")


def _safe_mkdir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _list_files(root: Path) -> list[str]:
    if not root.exists():
        return []
    return [str(p.relative_to(root)) for p in sorted(root.rglob("*")) if p.is_file()]


def _hf_env(base_env: dict[str, str]) -> dict[str, str]:
    env = dict(base_env)
    env["HF_HOME"] = str(HF_CACHE_DIR)
    env["HUGGINGFACE_HUB_CACHE"] = str(HF_CACHE_DIR / "hub")
    env["TRANSFORMERS_CACHE"] = str(HF_CACHE_DIR / "transformers")
    env["TORCH_HOME"] = str(HF_CACHE_DIR / "torch")
    return env


def _find_artifact(run_dir: Path, filename: str) -> Path | None:
    for candidate in (run_dir / filename, run_dir / "inputs" / filename):
        if candidate.exists():
            return candidate
    matches = sorted(p for p in run_dir.rglob(filename) if p.is_file())
    return matches[0] if matches else None


def _build_web_preview(source_ply: Path, max_splats: int = DEFAULT_WEB_MAX_SPLATS) -> Path | None:
    if max_splats <= 0:
        return None

    preview_path = source_ply.with_name(WEB_PREVIEW_FILENAME)
    if preview_path.exists():
        return preview_path

    try:
        import numpy as np
        from plyfile import PlyData, PlyElement
    except ImportError:
        return None

    ply = PlyData.read(str(source_ply))
    if "vertex" not in ply:
        return None

    vertices = ply["vertex"].data
    total = len(vertices)
    if total <= max_splats:
        return source_ply

    rng = np.random.default_rng(0)
    indices = np.sort(rng.choice(total, size=max_splats, replace=False))
    sampled = vertices[indices]

    preview = PlyData([PlyElement.describe(sampled, "vertex")], text=False)
    preview.write(str(preview_path))
    print(f"Web preview: {total} -> {max_splats} splats")
    return preview_path


def _find_viewable_splat(run_dir: Path, prefer_preview: bool = True) -> Path | None:
    for name in ("gaussians.splat", "gaussians.ksplat"):
        found = _find_artifact(run_dir, name)
        if found:
            return found

    if prefer_preview:
        preview = _find_artifact(run_dir, WEB_PREVIEW_FILENAME)
        if preview:
            return preview

    found_ply = _find_artifact(run_dir, "gaussians.ply")
    if found_ply:
        return found_ply

    matches = sorted(p for p in run_dir.rglob("*") if p.is_file() and p.suffix.lower() in SPLAT_VIEW_EXTS)
    return matches[0] if matches else None


# ---------------------------------------------------------------------------
# Modal functions
# ---------------------------------------------------------------------------


@app.function(
    image=image,
    gpu=modal.gpu.H100(count=2),  # Use 2 H100s on same instance
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
    web_max_splats: int = DEFAULT_WEB_MAX_SPLATS,
    num_gpus: int = 2,  # Number of GPUs to use
) -> dict[str, Any]:
    """Generate a 3D Gaussian Splat world from images or video."""
    if image_payloads is None and video_bytes is None:
        raise ValueError("Provide either image_payloads or video_bytes")

    run_id = run_id or uuid.uuid4().hex[:12]
    run_dir = RUNS_DIR / run_id
    _safe_mkdir(run_dir)
    for subdir in ("hub", "transformers", "torch"):
        _safe_mkdir(HF_CACHE_DIR / subdir)

    # Write inputs
    if image_payloads is not None:
        input_dir = run_dir / "inputs"
        _safe_mkdir(input_dir)
        for name, data in sorted(image_payloads, key=lambda x: x[0].lower()):
            suffix = Path(name).suffix.lower()
            if suffix not in IMAGE_EXTS:
                raise ValueError(f"Unsupported image type: {name}")
            (input_dir / (Path(name).stem + suffix)).write_bytes(data)
        input_path = input_dir
    else:
        suffix = Path(video_filename).suffix.lower()
        if suffix not in VIDEO_EXTS:
            raise ValueError(f"Unsupported video type: {video_filename}")
        input_path = run_dir / Path(video_filename).name
        input_path.write_bytes(video_bytes or b"")

    # HuggingFace login
    hf_token = os.environ.get("HUGGINGFACE_TOKEN")
    if hf_token:
        from huggingface_hub import login as hf_login
        try:
            hf_login(token=hf_token, add_to_git_credential=False)
        except Exception as exc:
            print(f"WARNING: HuggingFace login failed: {exc}. Model download may fail if weights aren't cached.")

    # Run inference
    # For multi-GPU, use torchrun if num_gpus > 1 and model supports it
    env = _hf_env(os.environ)
    if num_gpus > 1:
        # Try using PyTorch distributed (torchrun)
        # This may need adjustment based on HunyuanWorld-Mirror's actual multi-GPU support
        infer_args = [
            "torchrun",
            f"--nproc_per_node={num_gpus}",
            "--standalone",
            str(REPO_DIR / "infer.py"),
            "--input_path", str(input_path),
            "--output_path", str(run_dir),
            "--fps", str(fps),
            "--target_size", str(target_size),
            "--save_gs",
        ]
        env["CUDA_VISIBLE_DEVICES"] = ",".join(str(i) for i in range(num_gpus))
    else:
        infer_args = [
            "python3", str(REPO_DIR / "infer.py"),
            "--input_path", str(input_path),
            "--output_path", str(run_dir),
            "--fps", str(fps),
            "--target_size", str(target_size),
            "--save_gs",
        ]

    try:
        _run(infer_args, cwd=REPO_DIR, env=env)
    except CommandError as e:
        # If torchrun fails, fallback to single GPU
        if num_gpus > 1:
            print(f"WARNING: Multi-GPU inference failed, falling back to single GPU: {e}")
            infer_args = [
                "python3", str(REPO_DIR / "infer.py"),
                "--input_path", str(input_path),
                "--output_path", str(run_dir),
                "--fps", str(fps),
                "--target_size", str(target_size),
                "--save_gs",
            ]
            _run(infer_args, cwd=REPO_DIR, env=_hf_env(os.environ))
        else:
            raise

    # Find outputs
    gaussians_ply = _find_artifact(run_dir, "gaussians.ply")
    if gaussians_ply is None:
        raise FileNotFoundError(f"gaussians.ply not produced. Files: {_list_files(run_dir)}")

    web_preview = _build_web_preview(gaussians_ply, max_splats=web_max_splats)

    artifacts_volume.commit()
    weights_volume.commit()

    return {
        "run_id": run_id,
        "gaussians_ply": str(gaussians_ply.relative_to(run_dir)),
        "web_preview_ply": str(web_preview.relative_to(run_dir)) if web_preview else None,
        "files": _list_files(run_dir),
    }


# Parallel batch processing across multiple instances
@app.function(
    image=image,
    gpu="H100",  # Each instance gets 1 H100
    timeout=60 * 60,
    volumes={"/data": artifacts_volume, "/cache": weights_volume},
)
def generate_world_single_gpu(
    image_payloads: list[tuple[str, bytes]] | None = None,
    video_bytes: bytes | None = None,
    video_filename: str = "input.mp4",
    run_id: str | None = None,
    fps: int = 1,
    target_size: int = 518,
    web_max_splats: int = DEFAULT_WEB_MAX_SPLATS,
) -> dict[str, Any]:
    """Single GPU version for parallel batch processing."""
    return generate_world(
        image_payloads=image_payloads,
        video_bytes=video_bytes,
        video_filename=video_filename,
        run_id=run_id,
        fps=fps,
        target_size=target_size,
        web_max_splats=web_max_splats,
        num_gpus=1,
    )


@app.function()
def batch_generate_worlds(
    batch_inputs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Process multiple scenes in parallel across multiple GPU instances.

    Example:
        batch_inputs = [
            {"image_payloads": images1, "run_id": "scene1"},
            {"image_payloads": images2, "run_id": "scene2"},
            {"video_bytes": video_data, "run_id": "scene3"},
        ]
    """
    results = list(generate_world_single_gpu.map(batch_inputs))
    return results


@app.function(
    image=image,
    gpu="H100",
    timeout=60 * 60,
    volumes={"/data": artifacts_volume, "/cache": weights_volume},
)
def process_route_chunk(
    chunk_images: list[tuple[str, bytes]],
    chunk_id: str,
    fps: int = 1,
    target_size: int = 518,
    web_max_splats: int = DEFAULT_WEB_MAX_SPLATS,
) -> dict[str, Any]:
    """Process a chunk of route images on a single GPU."""
    run_id = f"route_chunk_{chunk_id}"
    return generate_world(
        image_payloads=chunk_images,
        run_id=run_id,
        fps=fps,
        target_size=target_size,
        web_max_splats=web_max_splats,
        num_gpus=1,
    )


@app.function()
def generate_world_parallel_route(
    image_payloads: list[tuple[str, bytes]],
    num_chunks: int = 4,
    fps: int = 1,
    target_size: int = 518,
    web_max_splats: int = DEFAULT_WEB_MAX_SPLATS,
) -> dict[str, Any]:
    """
    Process a route's images in parallel by splitting into chunks.
    Each chunk is processed on a separate GPU instance concurrently.

    Args:
        image_payloads: List of (filename, bytes) tuples
        num_chunks: Number of parallel GPU instances to use
        fps: Frames per second for video extraction
        target_size: Target image size
        web_max_splats: Maximum splats for web preview

    Returns:
        Combined results from all chunks
    """
    # Split images into chunks
    chunk_size = max(1, len(image_payloads) // num_chunks)
    chunks = []
    for i in range(0, len(image_payloads), chunk_size):
        chunk = image_payloads[i:i + chunk_size]
        chunks.append({
            "chunk_images": chunk,
            "chunk_id": f"{uuid.uuid4().hex[:8]}_{i // chunk_size}",
            "fps": fps,
            "target_size": target_size,
            "web_max_splats": web_max_splats,
        })

    print(f"Processing {len(image_payloads)} images across {len(chunks)} parallel GPU instances...")

    # Process all chunks in parallel using .starmap()
    results = list(process_route_chunk.starmap(
        [(c["chunk_images"], c["chunk_id"], c["fps"], c["target_size"], c["web_max_splats"])
         for c in chunks]
    ))

    # Return combined results
    return {
        "num_chunks": len(chunks),
        "chunk_results": results,
        "total_images": len(image_payloads),
    }


# ---------------------------------------------------------------------------
# Viewer (FastAPI)
# ---------------------------------------------------------------------------


@app.function(image=image, volumes={"/data": artifacts_volume})
@modal.asgi_app()
def viewer() -> FastAPI:
    api = FastAPI(title="World Mirror v2")

    @api.get("/")
    def root():
        run_ids = sorted(p.name for p in RUNS_DIR.glob("*") if p.is_dir())
        return JSONResponse({"runs": run_ids})

    @api.get("/runs/{run_id}")
    def list_run(run_id: str):
        run_dir = RUNS_DIR / run_id
        if not run_dir.exists():
            raise HTTPException(404, "run not found")
        return JSONResponse({"run_id": run_id, "files": _list_files(run_dir)})

    @api.get("/runs/{run_id}/file")
    def get_file(run_id: str, path: str):
        run_dir = (RUNS_DIR / run_id).resolve()
        if not run_dir.exists():
            raise HTTPException(404, "run not found")
        target = (run_dir / path).resolve()
        if not str(target).startswith(str(run_dir)):
            raise HTTPException(400, "invalid path")
        if not target.exists() or not target.is_file():
            raise HTTPException(404, "file not found")
        return FileResponse(target)

    @api.get("/runs/{run_id}/splat-viewer")
    def splat_viewer(run_id: str, path: str = "", full: bool = False, request: Request = None):
        run_dir = (RUNS_DIR / run_id).resolve()
        if not run_dir.exists():
            raise HTTPException(404, "run not found")

        chosen: Path | None = None
        if path:
            candidate = (run_dir / path).resolve()
            if not str(candidate).startswith(str(run_dir)):
                raise HTTPException(400, "invalid path")
            if not candidate.exists() or candidate.suffix.lower() not in SPLAT_VIEW_EXTS:
                raise HTTPException(404, "splat file not found")
            chosen = candidate
        else:
            if not full:
                base_ply = _find_artifact(run_dir, "gaussians.ply")
                if base_ply and not _find_artifact(run_dir, WEB_PREVIEW_FILENAME):
                    preview = _build_web_preview(base_ply)
                    if preview and preview != base_ply:
                        artifacts_volume.commit()
            chosen = _find_viewable_splat(run_dir, prefer_preview=not full)

        if chosen is None:
            raise HTTPException(404, "No splat file found. Run generation first.")

        rel_path = str(chosen.relative_to(run_dir))
        file_url = f"/runs/{run_id}/file?path={quote(rel_path, safe='')}"

        # Get the full absolute URL for external viewers
        if request:
            base_url = str(request.base_url).rstrip('/')
            full_file_url = f"{base_url}{file_url}"
        else:
            full_file_url = file_url

        file_url_encoded = quote(full_file_url, safe='')
        preview_url = f"/runs/{run_id}/splat-viewer?full=false"
        full_url = f"/runs/{run_id}/splat-viewer?full=true"
        mode_label = "full quality" if full else "fast preview"

        html = (
            SPLAT_VIEWER_HTML
            .replace("__RUN_ID__", run_id)
            .replace("__FILE_URL__", file_url)
            .replace("__FILE_URL_ENCODED__", file_url_encoded)
            .replace("__MODE_LABEL__", mode_label)
            .replace("__PREVIEW_URL__", preview_url)
            .replace("__FULL_URL__", full_url)
        )
        return HTMLResponse(html)

    return api


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------


@app.local_entrypoint()
def main(
    address: str = "",
    lat: float = 0.0,
    lng: float = 0.0,
    end_address: str = "",
    end_lat: float = 0.0,
    end_lng: float = 0.0,
    input_dir: str = "",
    video_path: str = "",
    num_images: int = 100,
    num_points: int = 10,
    target_size: int = 518,
    fps: int = 1,
    grid: int = 0,
    grid_spacing: float = 30,
    viewer_url: str = "",
    parallel: bool = False,
    num_chunks: int = 4,
    num_gpus: int = 2,
) -> None:
    """Generate a 3D world from an address, coordinates, route, images, or video.

    Route mode: provide --address + --end-address (or --lat/--lng + --end-lat/--end-lng)
    to sample forward-facing views along a road between two points.

    Multi-GPU options:
        --num-gpus N: Use N GPUs on a single instance (default: 2)
        --parallel: Split route images across multiple GPU instances
        --num-chunks N: Number of parallel GPU instances when using --parallel (default: 4)
    """
    import sys
    import tempfile

    has_address = bool(address.strip())
    has_coords = lat != 0.0 or lng != 0.0
    has_end = bool(end_address.strip()) or end_lat != 0.0 or end_lng != 0.0
    has_images = bool(input_dir.strip())
    has_video = bool(video_path.strip())

    has_location = has_address or has_coords
    if sum([has_location, has_images, has_video]) != 1:
        print("Provide exactly one of: --address/--lat+lng, --input-dir, --video-path")
        sys.exit(1)

    image_payloads: list[tuple[str, bytes]] | None = None
    video_bytes: bytes | None = None
    video_filename = "input.mp4"

    if has_location:
        sys.path.insert(0, str(Path(__file__).parent))
        from fetch_streetview import geocode_address, fetch_scene, fetch_route

        if has_address:
            lat, lng = geocode_address(address)

        # Route mode: start + end point -> forward-facing views along the road
        if has_end:
            if end_address.strip():
                end_lat, end_lng = geocode_address(end_address)
            elif end_lat == 0.0 and end_lng == 0.0:
                print("Provide --end-address or --end-lat/--end-lng for route mode")
                sys.exit(1)

            with tempfile.TemporaryDirectory() as tmpdir:
                scene_dir = Path(tmpdir) / "scene"
                fetch_route(
                    lat, lng, end_lat, end_lng, scene_dir,
                    num_points=num_points,
                    total_images=num_images,
                )
                files = sorted(p for p in scene_dir.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTS)
                if not files:
                    print("No images fetched along route!")
                    sys.exit(1)
                image_payloads = [(p.name, p.read_bytes()) for p in files]
                print(f"\nUploading {len(image_payloads)} route images to Modal...")

        # Area mode: single point or grid
        else:
            with tempfile.TemporaryDirectory() as tmpdir:
                scene_dir = Path(tmpdir) / "scene"
                fetch_scene(
                    lat, lng, scene_dir,
                    total_images=num_images,
                    grid_size=grid,
                    grid_spacing=grid_spacing,
                )
                files = sorted(p for p in scene_dir.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTS)
                if not files:
                    print("No images fetched from street view!")
                    sys.exit(1)
                image_payloads = [(p.name, p.read_bytes()) for p in files]
                print(f"\nUploading {len(image_payloads)} images to Modal...")

    elif has_images:
        src = Path(input_dir)
        files = sorted(p for p in src.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTS)
        if not files:
            print(f"No images found in {input_dir}")
            sys.exit(1)
        image_payloads = [(p.name, p.read_bytes()) for p in files]

    elif has_video:
        src = Path(video_path)
        video_bytes = src.read_bytes()
        video_filename = src.name

    # Call Modal
    if parallel and image_payloads and len(image_payloads) > 10:
        print(f"Starting PARALLEL world generation on Modal ({num_chunks} x H100)...")
        result = generate_world_parallel_route.remote(
            image_payloads=image_payloads,
            num_chunks=num_chunks,
            fps=fps,
            target_size=target_size,
        )
    else:
        gpu_label = f"{num_gpus}x H100" if num_gpus > 1 else "H100"
        print(f"Starting world generation on Modal ({gpu_label})...")
        result = generate_world.remote(
            image_payloads=image_payloads,
            video_bytes=video_bytes,
            video_filename=video_filename,
            fps=fps,
            target_size=target_size,
            num_gpus=num_gpus,
        )

    print("\n" + json.dumps(result, indent=2))

    # Print viewer URL
    run_id = result["run_id"]
    if viewer_url:
        base = viewer_url.rstrip("/")
    else:
        try:
            deployed = modal.Function.from_name(APP_NAME, "viewer")
            base = (deployed.get_web_url() or "").rstrip("/")
        except Exception:
            base = ""

    if base:
        print(f"\nViewer: {base}/runs/{run_id}/splat-viewer")
        ply = result.get("gaussians_ply")
        if ply:
            print(f"Download: {base}/runs/{run_id}/file?path={quote(ply, safe='')}")
    else:
        print("\nDeploy viewer: modal deploy v2/modal_app.py")
