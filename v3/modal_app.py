"""
Scenario Generator — Text prompt → AI video → 3D Gaussian Splat world.

Pipeline:
    1. Gemini expands short prompt into cinematic video description
    2. Google Veo 3.1 generates an 8-second video
    3. HunyuanWorld-Mirror converts video into 3D Gaussian Splat
    4. Spark.js viewer displays the result

Usage:
    # Generate from prompt
    modal run v3/modal_app.py --prompt "road with fallen tree blocking traffic"

    # Deploy persistent frontend + viewer
    modal deploy v3/modal_app.py
"""

from __future__ import annotations

import json
import os
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import quote

import modal
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

APP_NAME = "scenario-gen"
REPO_URL = "https://github.com/Tencent-Hunyuan/HunyuanWorld-Mirror.git"
REPO_DIR = Path("/opt/HunyuanWorld-Mirror")
RUNS_DIR = Path("/data/runs")
HF_CACHE_DIR = Path("/cache/hf")

SPLAT_VIEW_EXTS = {".splat", ".ply", ".ksplat", ".spz"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
VIDEO_EXTS = {".mp4", ".avi", ".mov", ".webm", ".gif"}
WEB_PREVIEW_FILENAME = "gaussians_web_preview.ply"
DEFAULT_WEB_MAX_SPLATS = 200_000

# ---------------------------------------------------------------------------
# HTML templates
# ---------------------------------------------------------------------------

SPARK_VIEWER_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>3D Viewer | __RUN_ID__</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  html, body { width: 100%; height: 100%; background: #2b2928; overflow: hidden; }
  canvas { display: block; width: 100%; height: 100%; }
  #loading { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; background: rgba(5, 5, 5, 0.8); backdrop-filter: blur(4px); z-index: 10; }
  #loading-content { display: flex; flex-direction: column; align-items: center; gap: 16px; }
  .spinner { position: relative; width: 40px; height: 40px; }
  .spinner-ring { position: absolute; inset: 0; border-radius: 50%; border: 2px solid transparent; animation: spin 1s linear infinite; }
  .spinner-ring:nth-child(1) { border-top-color: #60a5fa; }
  .spinner-ring:nth-child(2) { inset: 4px; border-bottom-color: #60a5fa; animation-direction: reverse; animation-duration: 1.5s; }
  @keyframes spin { to { transform: rotate(360deg); } }
  .loading-text { color: #f2f4f8; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; font-size: 14px; font-weight: 500; }
  .controls-hint { position: absolute; bottom: 16px; right: 16px; padding: 8px 16px; background: rgba(255, 255, 255, 0.08); border: 1px solid rgba(255, 255, 255, 0.1); border-radius: 8px; backdrop-filter: blur(8px); color: #9ca3af; font-family: monospace; font-size: 10px; text-transform: uppercase; letter-spacing: 0.05em; z-index: 5; }
</style>
<script type="importmap">
{
  "imports": {
    "three": "https://cdn.jsdelivr.net/npm/three@0.174.0/build/three.module.js",
    "@sparkjsdev/spark": "https://cdn.jsdelivr.net/npm/@sparkjsdev/spark@0.1.10/dist/spark.module.js"
  }
}
</script>
</head>
<body>
<div id="loading">
  <div id="loading-content">
    <div class="spinner">
      <div class="spinner-ring"></div>
      <div class="spinner-ring"></div>
    </div>
    <div class="loading-text">Loading splat...</div>
  </div>
</div>
<div class="controls-hint">Click + drag to look · WASD / Arrows to move · Scroll to zoom</div>
<script type="module">
import * as THREE from 'three';
import { SplatMesh, SparkControls } from '@sparkjsdev/spark';

const canvas = document.createElement('canvas');
canvas.style.display = 'block';
canvas.style.width = '100%';
canvas.style.height = '100%';
document.body.appendChild(canvas);

// Camera - same as official Spark viewer
const camera = new THREE.PerspectiveCamera(75, window.innerWidth / window.innerHeight, 0.01, 1000);
camera.position.set(0, 0, 1);

const scene = new THREE.Scene();

// Renderer
const renderer = new THREE.WebGLRenderer({ canvas, antialias: false });
renderer.setSize(window.innerWidth, window.innerHeight, false);
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));

// SparkControls - handles mouse orbit, scroll zoom, WASD, arrow keys
const controls = new SparkControls({ canvas });

// Load splat - matches official Spark viewer pattern
const splat = new SplatMesh({ url: "__PLY_URL__" });
splat.quaternion.set(1, 0, 0, 0);
scene.add(splat);

// Wait for splat to load before hiding loading screen
splat.initialized.then(() => {
  document.getElementById('loading').style.display = 'none';
  console.log('Splat loaded:', splat.numSplats, 'splats');
}).catch(err => {
  console.error('Failed to load splat:', err);
  document.querySelector('.loading-text').textContent = 'Failed to load splat';
});

// Resize handler
function resize() {
  const w = window.innerWidth;
  const h = window.innerHeight;
  if (w === 0 || h === 0) return;
  const needResize = canvas.width !== w || canvas.height !== h;
  if (needResize) {
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  }
}
window.addEventListener('resize', resize);

// Animation loop - exactly matches official viewer
renderer.setAnimationLoop(() => {
  resize();
  controls.update(camera);
  renderer.render(scene, camera);
});
</script>
</body>
</html>"""

# ---------------------------------------------------------------------------
# Modal app setup
# ---------------------------------------------------------------------------

app = modal.App(APP_NAME)
artifacts_volume = modal.Volume.from_name("scenario-gen-artifacts", create_if_missing=True)
weights_volume = modal.Volume.from_name("world-mirror-v2-weights", create_if_missing=True)

gpu_image = (
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

light_image = modal.Image.debian_slim(python_version="3.11").pip_install(
    "google-genai", "fastapi", "uvicorn", "python-multipart", "requests",
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
    """List all files in directory tree, with error handling."""
    if not root.exists():
        return []
    try:
        files = []
        for p in sorted(root.rglob("*")):
            try:
                if p.is_file():
                    files.append(str(p.relative_to(root)))
            except (OSError, PermissionError):
                continue
        return files
    except Exception as e:
        print(f"Warning: Error listing files in {root}: {e}")
        return []


def _hf_env(base_env: dict[str, str]) -> dict[str, str]:
    env = dict(base_env)
    env["HF_HOME"] = str(HF_CACHE_DIR)
    env["HUGGINGFACE_HUB_CACHE"] = str(HF_CACHE_DIR / "hub")
    env["TRANSFORMERS_CACHE"] = str(HF_CACHE_DIR / "transformers")
    env["TORCH_HOME"] = str(HF_CACHE_DIR / "torch")
    return env


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


def _find_artifact(run_dir: Path, filename: str) -> Path | None:
    """Find an artifact file in run directory, searching common locations."""
    if not run_dir.exists():
        return None
    for candidate in (run_dir / filename, run_dir / "inputs" / filename):
        if candidate.exists() and candidate.is_file():
            return candidate
    try:
        matches = sorted(p for p in run_dir.rglob(filename) if p.is_file())
        return matches[0] if matches else None
    except (OSError, PermissionError):
        return None


def _safe_reload(volume: modal.Volume, retries: int = 2) -> bool:
    """Safely reload volume, handling open file conflicts with retries."""
    for attempt in range(retries + 1):
        try:
            volume.reload()
            return True
        except Exception as e:
            # Common issue: files are open (being served), can't reload
            if "open files" in str(e).lower() and attempt < retries:
                time.sleep(0.5)
                continue
            if attempt == retries:
                print(f"Volume reload failed after {retries + 1} attempts: {e}")
                return False
            print(f"Volume reload warning (attempt {attempt + 1}): {e}")
    return False


def _validate_run_id(run_id: str) -> bool:
    """Validate run_id is safe (alphanumeric + dash only)."""
    import re
    return bool(re.match(r'^[a-zA-Z0-9_-]+$', run_id)) and len(run_id) <= 64


def _read_file_safe(file_path: Path, max_size_mb: int = 500) -> bytes:
    """Read file with size check to prevent memory issues."""
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    size_mb = file_path.stat().st_size / (1024 * 1024)
    if size_mb > max_size_mb:
        raise ValueError(f"File too large: {size_mb:.1f} MB (max {max_size_mb} MB)")

    return file_path.read_bytes()


def _get_video_duration(video_path: Path) -> float:
    """Get video duration in seconds using ffprobe."""
    try:
        output = _run([
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(video_path)
        ])
        return float(output.strip())
    except (CommandError, ValueError) as e:
        print(f"Warning: Could not determine video duration: {e}")
        return 8.0  # Default to 8 seconds (Veo's standard duration)


def _calculate_dynamic_fps(video_path: Path, target_frames: int = 23) -> float:
    """Calculate FPS to extract the target number of frames from video.

    Args:
        video_path: Path to the video file
        target_frames: Target number of frames to extract (default 23, which is in the 21-25 range)

    Returns:
        Calculated FPS value to achieve target frame count
    """
    duration = _get_video_duration(video_path)
    if duration <= 0:
        print(f"Warning: Invalid video duration {duration}, using default fps=3")
        return 3.0

    # Calculate fps to get target_frames
    fps = target_frames / duration

    # Ensure reasonable bounds (at least 1 fps)
    fps = max(1.0, fps)

    # Calculate actual frame count that will be extracted
    actual_frames = int(duration * fps)
    print(f"Video duration: {duration:.2f}s, target frames: {target_frames}, calculated fps: {fps:.2f}, expected frames: {actual_frames}")

    return fps


# ---------------------------------------------------------------------------
# Step 1: Expand prompt with Gemini
# ---------------------------------------------------------------------------


@app.function(
    image=light_image,
    secrets=[modal.Secret.from_name("gemini-api-key")],
    timeout=60,
)
def expand_prompt(short_prompt: str, category: str = "autonomous") -> str:
    """
    Uses Gemini to expand a scenario into a technically optimized video prompt 
    specifically for 3D Gaussian Splatting (3DGS) reconstruction.
    """
    from google import genai

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not found in environment")

    client = genai.Client(api_key=api_key)

    # 3DGS Technical Requirements (The "Secret Sauce")
    gs_technical_base = """
CRITICAL 3DGS RECONSTRUCTION RULES:
- CAMERA PATH: Must be a continuous, slow-speed orbital arc or curvilinear dolly move. NO stationary pans or tilts.
- PARALLAX: Ensure foreground objects shift significantly against the background to provide depth anchors.
- STATIC SCENE: 100% geometric stasis. No moving cars, no swaying trees, no walking people, no flickering lights.
- TEXTURE DENSITY: Include high-frequency details (asphalt grit, concrete cracks, fabric weave, surface scuffs) to avoid 'flat' artifacts.
- GLOBAL SHUTTER AESTHETIC: Zero motion blur. Every frame must be crisp, sharp, and high-resolution.
- LIGHTING: Baked, consistent global illumination. No moving shadows or lens flares.
- LOOP CLOSURE: The camera should see the same landmark from at least two distinct angles separated by 30-90 degrees."""

    # Domain-specific refinements
    if category == "autonomous":
        domain_instructions = """
AUTONOMOUS DOMAIN OPTIMIZATION:
- ENVIRONMENT: Focus on road fidelity—weathered asphalt, thermal cracks, grit on curbs, and paint peeling on lane markings.
- PERSPECTIVE: A low-altitude drone orbit or a wide-arc gimbal move around an intersection or obstacle.
- MULTI-VIEW: Explicitly capture 'Loop Closure' by orbiting a 360-degree path around the primary road feature.
- DEPTH: Clear separation between foreground (curbs/signs) and background (buildings/distant hills)."""
    else:  # humanoid / workspace
        domain_instructions = """
HUMANOID/WORKSPACE OPTIMIZATION:
- MANIPULATION TARGETS: Macro-level detail on objects—fingerprints on glass, texture on plastic, wood grain on tables.
- WORKSPACE: Include high clutter/detail in the background (bookshelves, tools, wires) to provide 'feature points' for the splat.
- VIEWPOINTS: A slow, spiraling orbit (corkscrew motion) that views the target from the top, sides, and slightly below."""

    system_prompt = f"""You are a Photogrammetry and 3D Reconstruction Expert. 
Your task is to turn a short scenario into a high-fidelity video prompt for AI video generators (like Sora or Kling) that will specifically be used to train 3D Gaussian Splats.

{gs_technical_base}

{domain_instructions}

Scenario: {short_prompt}

Respond ONLY with the expanded video prompt. Use technical, descriptive language. Focus on the camera's physical path and the minute surface details of the environment."""

    response = client.models.generate_content(
        model="gemini-2.0-flash",
        contents=system_prompt,
    )
    
    expanded = response.text.strip()
    print(f"Expanded 3DGS Prompt ({category}):\n{expanded}")
    return expanded

# ---------------------------------------------------------------------------
# Step 2: Generate video with Veo
# ---------------------------------------------------------------------------


@app.function(
    image=light_image,
    secrets=[modal.Secret.from_name("gemini-api-key")],
    timeout=15 * 60,  # Increased timeout
    volumes={"/data": artifacts_volume},
)
def generate_video(prompt: str, run_id: str) -> bytes:
    """Generate a video using Google Veo 3.1 and return the bytes."""
    from google import genai
    from google.genai import types

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not found in environment")

    client = genai.Client(api_key=api_key)

    print(f"Submitting video generation request...")
    print(f"Prompt for Veo: {prompt}")

    try:
        operation = client.models.generate_videos(
            model="veo-3.1-generate-preview",
            prompt=prompt,
            config=types.GenerateVideosConfig(
                aspect_ratio="16:9",
                resolution="720p",
            ),
        )
    except Exception as e:
        raise RuntimeError(f"Failed to submit video generation request: {e}")

    elapsed = 0
    max_wait = 600  # 10 minutes max
    while not operation.done and elapsed < max_wait:
        print(f"  Waiting for video... ({elapsed}s)")
        time.sleep(10)
        elapsed += 10
        try:
            operation = client.operations.get(operation)
        except Exception as e:
            print(f"Warning: Failed to check operation status: {e}")
            # Continue trying

    if not operation.done:
        raise TimeoutError(f"Video generation timed out after {elapsed}s")

    # Check for errors in the operation
    if hasattr(operation, 'error') and operation.error:
        error_msg = f"Veo video generation failed: {operation.error}"
        print(error_msg)
        raise RuntimeError(error_msg)

    # Check if we got a valid response
    if not hasattr(operation, 'response') or not operation.response:
        raise RuntimeError("Veo operation completed but no response received")

    if not hasattr(operation.response, 'generated_videos') or not operation.response.generated_videos:
        raise RuntimeError("Veo operation completed but no videos were generated")

    generated_video = operation.response.generated_videos[0]
    print(f"Video object received: {generated_video}")

    # Save to volume
    run_dir = RUNS_DIR / run_id
    _safe_mkdir(run_dir)
    video_path = run_dir / "generated_video.mp4"

    try:
        # Download the video first, then save it (working approach from commit 4d29989e)
        client.files.download(file=generated_video.video)
        generated_video.video.save(str(video_path))
    except Exception as e:
        raise RuntimeError(f"Failed to download/save video: {e}")

    try:
        artifacts_volume.commit()
    except Exception as e:
        print(f"Warning: Failed to commit volume: {e}")
        # Continue anyway - file is saved locally

    if not video_path.exists():
        raise RuntimeError("Video file was not saved successfully")

    video_bytes = video_path.read_bytes()
    video_size_mb = len(video_bytes) / (1024 * 1024)
    print(f"Video generated: {len(video_bytes)} bytes ({video_size_mb:.2f} MB) in {elapsed}s")

    # Warn if video is suspiciously small (likely blank/black)
    if video_size_mb < 0.1:
        print(f"WARNING: Video file is very small ({video_size_mb:.2f} MB) - may be blank or corrupted")
        raise RuntimeError(f"Video appears to be blank or corrupted ({video_size_mb:.2f} MB)")

    return video_bytes


# ---------------------------------------------------------------------------
# Step 3: Generate 3D world with HunyuanWorld-Mirror
# ---------------------------------------------------------------------------


@app.function(
    image=gpu_image,
    gpu="H100",
    timeout=90 * 60,  # Increased timeout for complex scenes
    volumes={"/data": artifacts_volume, "/cache": weights_volume},
)
def generate_world(
    video_bytes: bytes | None = None,
    run_id: str = "",
    image_payloads: list[tuple[str, bytes]] | None = None,
    fps: float | int = 3,
    target_size: int = 518,
    web_max_splats: int = DEFAULT_WEB_MAX_SPLATS,
) -> dict[str, Any]:
    """Convert video or images into 3D Gaussian Splat world.

    Note: fps parameter is used as a default/fallback. When processing videos,
    fps is dynamically calculated to extract 21-25 frames regardless of video duration.
    """
    if video_bytes is None and image_payloads is None:
        raise ValueError("Provide either video_bytes or image_payloads")

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
        print(f"Wrote {len(image_payloads)} images to {input_dir}")
    else:
        if not video_bytes or len(video_bytes) < 1000:
            raise ValueError(f"Invalid video input: {len(video_bytes)} bytes")
        input_path = run_dir / "input_video.mp4"
        try:
            input_path.write_bytes(video_bytes)
        except Exception as e:
            raise RuntimeError(f"Failed to write video file: {e}")
        if not input_path.exists() or input_path.stat().st_size == 0:
            raise RuntimeError("Video file was not written successfully")

        # Calculate dynamic FPS to extract 21-25 frames from video
        fps = _calculate_dynamic_fps(input_path, target_frames=23)
        print(f"Using dynamic FPS: {fps:.2f}")

    # HuggingFace login
    hf_token = os.environ.get("HUGGINGFACE_TOKEN")
    if hf_token:
        from huggingface_hub import login as hf_login
        try:
            hf_login(token=hf_token, add_to_git_credential=False)
        except Exception as exc:
            print(f"WARNING: HuggingFace login failed: {exc}")

    # Run inference
    env = _hf_env(os.environ)
    print(f"Starting HunyuanWorld-Mirror inference...")
    try:
        output = _run([
            "python3", str(REPO_DIR / "infer.py"),
            "--input_path", str(input_path),
            "--output_path", str(run_dir),
            "--fps", str(fps),
            "--target_size", str(target_size),
            "--save_gs",
        ], cwd=REPO_DIR, env=env)
        print(f"Inference completed successfully")
    except CommandError as e:
        raise RuntimeError(f"HunyuanWorld-Mirror inference failed: {e}")
    except Exception as e:
        raise RuntimeError(f"Unexpected error during inference: {e}")

    # Find outputs
    print(f"Looking for gaussians.ply in {run_dir}...")
    gaussians_ply = _find_artifact(run_dir, "gaussians.ply")
    if gaussians_ply is None:
        available_files = _list_files(run_dir)
        raise FileNotFoundError(
            f"gaussians.ply not produced by HunyuanWorld-Mirror. "
            f"Available files ({len(available_files)}): {available_files[:20]}"
        )

    print(f"Found gaussians.ply: {gaussians_ply}")

    # Build web preview (this can fail without breaking everything)
    try:
        preview = _build_web_preview(gaussians_ply, max_splats=web_max_splats)
        if preview:
            print(f"Created web preview: {preview}")
    except Exception as e:
        print(f"Warning: Failed to create web preview: {e}")
        # Continue anyway

    # Commit volumes (can fail without breaking)
    try:
        artifacts_volume.commit()
    except Exception as e:
        print(f"Warning: Failed to commit artifacts volume: {e}")

    try:
        weights_volume.commit()
    except Exception as e:
        print(f"Warning: Failed to commit weights volume: {e}")

    files = _list_files(run_dir)
    print(f"Generated {len(files)} output files")

    return {
        "run_id": run_id,
        "gaussians_ply": str(gaussians_ply.relative_to(run_dir)),
        "files": files,
    }


# ---------------------------------------------------------------------------
# Viewer (FastAPI)
# ---------------------------------------------------------------------------


@app.function(
    image=light_image,
    volumes={"/data": artifacts_volume},
)
@modal.concurrent(max_inputs=20)
@modal.asgi_app()
def viewer() -> FastAPI:
    api = FastAPI(title="Scenario Generator")

    api.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @api.get("/health")
    def health_check():
        """Health check endpoint."""
        return JSONResponse({
            "status": "healthy",
            "runs_dir_exists": RUNS_DIR.exists(),
            "timestamp": time.time()
        })

    @api.get("/runs")
    def list_runs():
        _safe_reload(artifacts_volume)
        try:
            if not RUNS_DIR.exists():
                return JSONResponse({"runs": []})
            run_ids = sorted((p.name for p in RUNS_DIR.glob("*") if p.is_dir()), reverse=True)
            return JSONResponse({"runs": run_ids})
        except Exception as e:
            print(f"Error listing runs: {e}")
            return JSONResponse({"runs": [], "error": str(e)})

    @api.get("/runs/{run_id}")
    def list_run(run_id: str):
        if not _validate_run_id(run_id):
            raise HTTPException(400, "invalid run_id format")

        _safe_reload(artifacts_volume)
        run_dir = RUNS_DIR / run_id
        if not run_dir.exists():
            raise HTTPException(404, "run not found")

        try:
            # Load metadata if exists
            meta_path = run_dir / "meta.json"
            meta = {}
            if meta_path.exists():
                try:
                    meta = json.loads(meta_path.read_text())
                except (json.JSONDecodeError, OSError) as e:
                    print(f"Failed to load meta.json: {e}")
                    meta = {"error": "metadata corrupted"}

            files = _list_files(run_dir)
            return JSONResponse({"run_id": run_id, "files": files, **meta})
        except Exception as e:
            print(f"Error reading run {run_id}: {e}")
            raise HTTPException(500, f"error reading run: {str(e)}")

    @api.get("/runs/{run_id}/file")
    def get_file(run_id: str, path: str):
        if not _validate_run_id(run_id):
            raise HTTPException(400, "invalid run_id format")

        def _resolve_target():
            """Resolve run dir and target file, returning (target_path, error_stage)."""
            run_dir = (RUNS_DIR / run_id).resolve()
            if not run_dir.exists():
                return None, "run"
            target = (run_dir / path).resolve()
            if not str(target).startswith(str(run_dir)):
                raise HTTPException(400, "invalid path - path traversal detected")
            if not target.exists() or not target.is_file():
                return None, "file"
            return target, None

        try:
            # Fast path: try without reload first
            target, miss = _resolve_target()

            # Reload-on-miss with retries: volume propagation can take
            # several seconds after commit on another container
            if target is None:
                for attempt in range(5):
                    _safe_reload(artifacts_volume)
                    target, miss = _resolve_target()
                    if target is not None:
                        break
                    time.sleep(1.5)

            if target is None:
                if miss == "run":
                    raise HTTPException(404, "run not found")
                raise HTTPException(404, f"file not found: {path}")

            # For large files, use FileResponse (streaming)
            # For small files, read into memory to avoid keeping files open
            file_size_mb = target.stat().st_size / (1024 * 1024)
            if file_size_mb > 50:
                # Large file: stream it (keeps file open, but necessary)
                return FileResponse(target)
            else:
                # Small file: read into memory and close immediately
                from fastapi.responses import Response
                content = target.read_bytes()
                # Infer media type
                import mimetypes
                media_type, _ = mimetypes.guess_type(str(target))
                return Response(content=content, media_type=media_type or "application/octet-stream")

        except HTTPException:
            raise
        except Exception as e:
            print(f"Error serving file {run_id}/{path}: {e}")
            raise HTTPException(500, f"error serving file: {str(e)}")

    @api.get("/runs/{run_id}/view", response_class=HTMLResponse)
    def splat_viewer(run_id: str, request: Request):
        if not _validate_run_id(run_id):
            raise HTTPException(400, "invalid run_id format")

        _safe_reload(artifacts_volume)

        try:
            run_dir = (RUNS_DIR / run_id).resolve()
            if not run_dir.exists():
                raise HTTPException(404, "run not found")

            # Find the PLY file
            ply = _find_artifact(run_dir, WEB_PREVIEW_FILENAME) or _find_artifact(run_dir, "gaussians.ply")
            if not ply:
                raise HTTPException(404, "No splat file found in run directory")

            rel_path = str(ply.relative_to(run_dir))
            ply_url = f"/runs/{run_id}/file?path={quote(rel_path, safe='')}"

            return SPARK_VIEWER_HTML.replace("__RUN_ID__", run_id).replace("__PLY_URL__", ply_url)

        except HTTPException:
            raise
        except Exception as e:
            print(f"Error loading viewer for {run_id}: {e}")
            raise HTTPException(500, f"error loading viewer: {str(e)}")

    @api.post("/generate")
    async def generate_endpoint(request: Request):
        try:
            body = await request.json()
        except json.JSONDecodeError:
            raise HTTPException(400, "invalid JSON in request body")

        prompt = body.get("prompt", "").strip()
        category = body.get("category", "autonomous").strip()

        if not prompt:
            raise HTTPException(400, "prompt is required")

        if len(prompt) > 2000:
            raise HTTPException(400, "prompt too long (max 2000 characters)")

        if category not in ["autonomous", "humanoid"]:
            category = "autonomous"

        run_id = uuid.uuid4().hex[:12]

        async def stream():
            try:
                # Step 1: Expand prompt
                yield f"data: {json.dumps({'step': 'expand_start'})}\n\n"
                try:
                    # Use .remote.aio() so we yield control to the event loop
                    # and SSE events flush to the client in real-time
                    expanded = await expand_prompt.remote.aio(prompt, category)
                    if not expanded or not expanded.strip():
                        raise ValueError("Prompt expansion returned empty result")
                    yield f"data: {json.dumps({'step': 'expand_done', 'expanded_prompt': expanded})}\n\n"
                except Exception as e:
                    yield f"data: {json.dumps({'step': 'error', 'message': f'Prompt expansion failed: {str(e)}'})}\n\n"
                    return

                # Save metadata
                try:
                    run_dir = RUNS_DIR / run_id
                    _safe_mkdir(run_dir)
                    meta = {
                        "prompt": prompt,
                        "category": category,
                        "expanded_prompt": expanded,
                        "created_at": time.time(),
                        "run_id": run_id
                    }
                    (run_dir / "meta.json").write_text(json.dumps(meta, indent=2))
                    artifacts_volume.commit()
                except Exception as e:
                    print(f"Warning: Failed to save metadata: {e}")
                    # Continue anyway

                # Step 2: Generate video
                yield f"data: {json.dumps({'step': 'video_start'})}\n\n"
                try:
                    video_bytes = await generate_video.remote.aio(expanded, run_id)
                    if not video_bytes or len(video_bytes) < 1000:
                        raise ValueError(f"Video generation produced invalid output ({len(video_bytes)} bytes)")
                    # Reload volume and verify the video file is visible before
                    # telling the frontend it's ready (volume propagation delay)
                    _safe_reload(artifacts_volume)
                    video_file = RUNS_DIR / run_id / "generated_video.mp4"
                    for _wait in range(6):
                        if video_file.exists():
                            break
                        time.sleep(1)
                        _safe_reload(artifacts_volume)
                    yield f"data: {json.dumps({'step': 'video_done', 'run_id': run_id})}\n\n"
                except Exception as e:
                    yield f"data: {json.dumps({'step': 'error', 'message': f'Video generation failed: {str(e)}'})}\n\n"
                    return

                # Step 3: Generate 3D world
                yield f"data: {json.dumps({'step': 'world_start'})}\n\n"
                try:
                    result = await generate_world.remote.aio(video_bytes, run_id)
                    if not result or "gaussians_ply" not in result:
                        raise ValueError("World generation did not produce expected output")
                    # Reload volume and verify PLY is visible before notifying frontend
                    _safe_reload(artifacts_volume)
                    ply_name = result.get("gaussians_ply", "gaussians.ply")
                    ply_file = RUNS_DIR / run_id / ply_name
                    for _wait in range(6):
                        if ply_file.exists():
                            break
                        time.sleep(1)
                        _safe_reload(artifacts_volume)
                    yield f"data: {json.dumps({'step': 'world_done', **result})}\n\n"
                except Exception as e:
                    yield f"data: {json.dumps({'step': 'error', 'message': f'World generation failed: {str(e)}'})}\n\n"
                    return

            except Exception as exc:
                import traceback
                traceback.print_exc()
                yield f"data: {json.dumps({'step': 'error', 'message': f'Unexpected error: {str(exc)}'})}\n\n"

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",  # Disable nginx/proxy buffering
            },
        )

    @api.post("/upload")
    async def upload_endpoint(
        files: list[UploadFile] = File(...),
    ):
        """Upload images or a video to generate a 3D world directly (skips prompt/video gen)."""
        if not files:
            raise HTTPException(400, "no files provided")

        run_id = uuid.uuid4().hex[:12]

        # Classify and read uploaded files
        image_payloads: list[tuple[str, bytes]] = []
        video_bytes: bytes | None = None

        for f in files:
            if not f.filename:
                continue
            suffix = Path(f.filename).suffix.lower()
            content = await f.read()
            if suffix in IMAGE_EXTS:
                image_payloads.append((f.filename, content))
            elif suffix in VIDEO_EXTS:
                if video_bytes is not None:
                    raise HTTPException(400, "only one video file allowed")
                video_bytes = content
            else:
                raise HTTPException(400, f"unsupported file type: {suffix}")

        if not image_payloads and video_bytes is None:
            raise HTTPException(400, "no valid image or video files found")
        if image_payloads and video_bytes:
            raise HTTPException(400, "provide either images or a video, not both")

        async def stream():
            try:
                yield f"data: {json.dumps({'step': 'upload_done', 'run_id': run_id, 'file_count': len(image_payloads) or 1})}\n\n"

                # Save metadata
                try:
                    run_dir = RUNS_DIR / run_id
                    _safe_mkdir(run_dir)
                    meta = {
                        "source": "upload",
                        "file_count": len(image_payloads) or 1,
                        "created_at": time.time(),
                        "run_id": run_id,
                    }
                    (run_dir / "meta.json").write_text(json.dumps(meta, indent=2))
                    artifacts_volume.commit()
                except Exception as e:
                    print(f"Warning: Failed to save metadata: {e}")

                # Generate 3D world
                yield f"data: {json.dumps({'step': 'world_start'})}\n\n"
                try:
                    if image_payloads:
                        result = await generate_world.remote.aio(
                            image_payloads=image_payloads, run_id=run_id,
                        )
                    else:
                        result = await generate_world.remote.aio(
                            video_bytes=video_bytes, run_id=run_id,
                        )
                    if not result or "gaussians_ply" not in result:
                        raise ValueError("World generation did not produce expected output")
                    _safe_reload(artifacts_volume)
                    ply_name = result.get("gaussians_ply", "gaussians.ply")
                    ply_file = RUNS_DIR / run_id / ply_name
                    for _wait in range(6):
                        if ply_file.exists():
                            break
                        time.sleep(1)
                        _safe_reload(artifacts_volume)
                    yield f"data: {json.dumps({'step': 'world_done', **result})}\n\n"
                except Exception as e:
                    yield f"data: {json.dumps({'step': 'error', 'message': f'World generation failed: {str(e)}'})}\n\n"
                    return

            except Exception as exc:
                import traceback
                traceback.print_exc()
                yield f"data: {json.dumps({'step': 'error', 'message': f'Unexpected error: {str(exc)}'})}\n\n"

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    return api


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------


@app.local_entrypoint()
def main(
    prompt: str = "",
    input_dir: str = "",
    video_path: str = "",
    run_id: str = "",
    fps: int = 3,
    target_size: int = 518,
    viewer_url: str = "",
) -> None:
    """Generate a 3D world from a text prompt, images, or video.

    Note: For video inputs (--prompt or --video-path), fps is calculated dynamically
    to extract 21-25 frames. The --fps parameter only applies to image inputs.

    Examples:
        modal run v3/modal_app.py --prompt "road with fallen tree blocking traffic"
        modal run v3/modal_app.py --input-dir ./my-photos
        modal run v3/modal_app.py --video-path ./scene.mp4
    """
    import sys

    has_prompt = bool(prompt.strip())
    has_images = bool(input_dir.strip())
    has_video = bool(video_path.strip())

    if sum([has_prompt, has_images, has_video]) != 1:
        print("Provide exactly one of: --prompt, --input-dir, or --video-path")
        sys.exit(1)

    run_id = run_id or uuid.uuid4().hex[:12]

    if has_images:
        src = Path(input_dir)
        files = sorted(p for p in src.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTS)
        if not files:
            print(f"No images found in {input_dir}")
            sys.exit(1)
        image_payloads = [(p.name, p.read_bytes()) for p in files]
        print(f"\n[1/1] Building 3D world from {len(image_payloads)} images on H100...")
        result = generate_world.remote(
            image_payloads=image_payloads, run_id=run_id, fps=fps, target_size=target_size,
        )

    elif has_video:
        src = Path(video_path)
        vbytes = src.read_bytes()
        print(f"\n[1/1] Building 3D world from video ({len(vbytes)} bytes) on H100...")
        result = generate_world.remote(
            video_bytes=vbytes, run_id=run_id, fps=fps, target_size=target_size,
        )

    else:
        # Text prompt flow: expand → generate video → build world
        print(f"\n[1/3] Expanding prompt with Gemini...")
        expanded = expand_prompt.remote(prompt)
        print(f"  Expanded: {expanded}\n")

        print(f"[2/3] Generating video with Veo 3.1...")
        video_bytes = generate_video.remote(expanded, run_id)
        print(f"  Video: {len(video_bytes)} bytes\n")

        print(f"[3/3] Building 3D world on H100...")
        result = generate_world.remote(
            video_bytes=video_bytes, run_id=run_id, fps=fps, target_size=target_size,
        )
    print(f"\n{json.dumps(result, indent=2)}")

    # Print viewer URL
    if viewer_url:
        base = viewer_url.rstrip("/")
    else:
        try:
            deployed = modal.Function.from_name(APP_NAME, "viewer")
            base = (deployed.get_web_url() or "").rstrip("/")
        except Exception:
            base = ""

    if base:
        print(f"\nViewer: {base}/runs/{run_id}/view")
        ply = result.get("gaussians_ply")
        if ply:
            print(f"Download: {base}/runs/{run_id}/file?path={quote(ply, safe='')}")

        # Auto-open debug browse page
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "v2"))
        from browse import open_browse_page
        files = result.get("files", [])
        if files:
            open_browse_page(run_id, base, files)
    else:
        print("\nDeploy viewer: modal deploy v3/modal_app.py")
