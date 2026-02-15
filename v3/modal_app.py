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
from fastapi import FastAPI, HTTPException, Request
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
WEB_PREVIEW_FILENAME = "gaussians_web_preview.ply"
DEFAULT_WEB_MAX_SPLATS = 200_000

# ---------------------------------------------------------------------------
# HTML templates
# ---------------------------------------------------------------------------

FRONTEND_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Scenario Generator</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { background: #0a0c12; color: #f2f4f8; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; min-height: 100vh; }

  .header { text-align: center; padding: 48px 20px 24px; }
  .header h1 { font-size: 40px; font-weight: 700; background: linear-gradient(135deg, #60a5fa 0%, #a78bfa 50%, #f472b6 100%); -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text; }
  .header p { color: #9ca3af; margin-top: 8px; font-size: 16px; }

  .main { max-width: 700px; margin: 0 auto; padding: 0 20px 60px; }

  .input-area { background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.1); border-radius: 16px; padding: 24px; margin-bottom: 24px; }
  .input-area textarea { width: 100%; background: rgba(0,0,0,0.3); border: 1px solid rgba(255,255,255,0.15); border-radius: 10px; color: #f2f4f8; font-size: 16px; padding: 14px 16px; resize: vertical; min-height: 80px; font-family: inherit; outline: none; transition: border-color 0.2s; }
  .input-area textarea:focus { border-color: #60a5fa; }
  .input-area textarea::placeholder { color: #6b7280; }

  .examples { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 12px; }
  .examples button { background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.1); border-radius: 20px; color: #9ca3af; font-size: 13px; padding: 6px 14px; cursor: pointer; transition: all 0.2s; }
  .examples button:hover { background: rgba(255,255,255,0.1); color: #e5e7eb; border-color: #60a5fa; }

  .generate-btn { width: 100%; padding: 16px; font-size: 17px; font-weight: 600; border: none; border-radius: 12px; cursor: pointer; background: linear-gradient(135deg, #3b82f6 0%, #8b5cf6 100%); color: white; transition: all 0.2s; box-shadow: 0 4px 16px rgba(59, 130, 246, 0.3); }
  .generate-btn:hover { transform: translateY(-1px); box-shadow: 0 6px 20px rgba(59, 130, 246, 0.4); }
  .generate-btn:disabled { opacity: 0.5; cursor: not-allowed; transform: none; box-shadow: none; }

  .progress { margin-top: 24px; display: none; }
  .progress.active { display: block; }
  .step { display: flex; align-items: center; gap: 12px; padding: 12px 16px; border-radius: 10px; margin-bottom: 8px; background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.06); transition: all 0.3s; }
  .step.active { background: rgba(96, 165, 250, 0.1); border-color: rgba(96, 165, 250, 0.3); }
  .step.done { background: rgba(34, 197, 94, 0.1); border-color: rgba(34, 197, 94, 0.2); }
  .step.error { background: rgba(239, 68, 68, 0.1); border-color: rgba(239, 68, 68, 0.3); }
  .step-icon { width: 28px; height: 28px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 14px; flex-shrink: 0; }
  .step.pending .step-icon { background: rgba(255,255,255,0.1); color: #6b7280; }
  .step.active .step-icon { background: rgba(96, 165, 250, 0.2); color: #60a5fa; }
  .step.done .step-icon { background: rgba(34, 197, 94, 0.2); color: #22c55e; }
  .step.error .step-icon { background: rgba(239, 68, 68, 0.2); color: #ef4444; }
  .step-text { font-size: 14px; color: #d1d5db; }
  .step.active .step-text { color: #f2f4f8; }
  .step-detail { font-size: 12px; color: #6b7280; margin-top: 2px; }

  @keyframes spin { to { transform: rotate(360deg); } }
  .spinner { display: inline-block; width: 16px; height: 16px; border: 2px solid rgba(96,165,250,0.3); border-top-color: #60a5fa; border-radius: 50%; animation: spin 0.8s linear infinite; }

  .debug-section { margin-top: 24px; display: none; }
  .debug-section.active { display: block; }
  .debug-panel { background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.1); border-radius: 12px; padding: 16px; margin-bottom: 16px; }
  .debug-panel h3 { color: #60a5fa; font-size: 14px; margin-bottom: 8px; text-transform: uppercase; letter-spacing: 0.5px; }
  .debug-panel .content { color: #d1d5db; font-size: 13px; line-height: 1.6; white-space: pre-wrap; word-break: break-word; max-height: 200px; overflow-y: auto; }
  .debug-panel video { width: 100%; max-width: 600px; border-radius: 8px; margin-top: 8px; }
  .file-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 8px; margin-top: 8px; }
  .file-item { padding: 8px 12px; background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.08); border-radius: 6px; font-family: monospace; font-size: 11px; color: #9ca3af; word-break: break-all; }
  .file-item:hover { background: rgba(255,255,255,0.08); color: #60a5fa; }
  .file-category { margin-top: 16px; }
  .file-category h4 { color: #9ca3af; font-size: 12px; margin-bottom: 8px; font-weight: 600; }

  .result { margin-top: 24px; display: none; }
  .result.active { display: block; }
  .result .viewer-frame { width: 100%; height: 500px; border: 1px solid rgba(255,255,255,0.1); border-radius: 12px; background: #000; }
  .result-links { display: flex; gap: 10px; margin-top: 12px; flex-wrap: wrap; }
  .result-links a { padding: 10px 18px; background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.1); border-radius: 8px; color: #60a5fa; text-decoration: none; font-size: 14px; transition: all 0.2s; }
  .result-links a:hover { background: rgba(255,255,255,0.1); border-color: #60a5fa; }

  .past-runs { margin-top: 40px; }
  .past-runs h3 { color: #9ca3af; font-size: 14px; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 12px; }
  .run-item { display: flex; align-items: center; justify-content: space-between; padding: 12px 16px; background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.06); border-radius: 10px; margin-bottom: 6px; }
  .run-item a { color: #60a5fa; text-decoration: none; font-family: monospace; font-size: 13px; }
</style>
</head>
<body>
<div class="header">
  <h1>Scenario Generator</h1>
  <p>Describe any scenario. We'll generate a 3D world you can explore.</p>
</div>

<div class="main">
  <div class="input-area">
    <textarea id="prompt" placeholder="Describe a scenario... e.g. 'highway with a fallen tree blocking the right lane'" rows="3"></textarea>
    <div class="examples">
      <button onclick="setPrompt('road with fallen tree blocking traffic')">Fallen tree</button>
      <button onclick="setPrompt('flooded suburban street with abandoned cars')">Flood</button>
      <button onclick="setPrompt('construction zone on a highway with cones and barriers')">Construction</button>
      <button onclick="setPrompt('snowy mountain road with ice patches')">Snow road</button>
      <button onclick="setPrompt('city intersection at night with rain')">Rain city</button>
    </div>
  </div>

  <button class="generate-btn" id="genBtn" onclick="generate()">Generate 3D World</button>

  <div class="progress" id="progress">
    <div class="step pending" id="step-expand">
      <div class="step-icon">1</div>
      <div>
        <div class="step-text">Expanding prompt with Gemini</div>
        <div class="step-detail" id="step-expand-detail"></div>
      </div>
    </div>
    <div class="step pending" id="step-video">
      <div class="step-icon">2</div>
      <div>
        <div class="step-text">Generating video with Veo 3.1</div>
        <div class="step-detail" id="step-video-detail"></div>
      </div>
    </div>
    <div class="step pending" id="step-world">
      <div class="step-icon">3</div>
      <div>
        <div class="step-text">Building 3D world with HunyuanWorld-Mirror</div>
        <div class="step-detail" id="step-world-detail"></div>
      </div>
    </div>
  </div>

  <div class="debug-section" id="debugSection">
    <div class="debug-panel">
      <h3>Original Prompt</h3>
      <div class="content" id="debugPrompt"></div>
    </div>
    <div class="debug-panel">
      <h3>Expanded Prompt (Gemini)</h3>
      <div class="content" id="debugExpandedPrompt"></div>
    </div>
    <div class="debug-panel">
      <h3>Generated Video (Veo 3.1)</h3>
      <video id="debugVideo" controls></video>
    </div>
    <div class="debug-panel">
      <h3>World Generation Outputs</h3>
      <div id="debugFiles"></div>
    </div>
  </div>

  <div class="result" id="result">
    <iframe id="viewerFrame" class="viewer-frame" frameborder="0"></iframe>
    <div class="result-links" id="resultLinks"></div>
  </div>
</div>

<script>
function setPrompt(text) {
  document.getElementById('prompt').value = text;
}

async function generate() {
  const prompt = document.getElementById('prompt').value.trim();
  if (!prompt) return;

  const btn = document.getElementById('genBtn');
  btn.disabled = true;
  btn.textContent = 'Generating...';

  const progress = document.getElementById('progress');
  progress.classList.add('active');
  document.getElementById('result').classList.remove('active');
  document.getElementById('debugSection').classList.remove('active');

  // Store original prompt
  document.getElementById('debugPrompt').textContent = prompt;

  // Reset steps
  ['expand', 'video', 'world'].forEach(s => {
    const el = document.getElementById('step-' + s);
    el.className = 'step pending';
    document.getElementById('step-' + s + '-detail').textContent = '';
  });

  try {
    const resp = await fetch('/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ prompt })
    });

    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\\n');
      buffer = lines.pop();
      for (const line of lines) {
        if (line.startsWith('data: ')) {
          try {
            const data = JSON.parse(line.slice(6));
            handleEvent(data);
          } catch {}
        }
      }
    }
  } catch (err) {
    setStepState('expand', 'error');
    document.getElementById('step-expand-detail').textContent = err.message;
  }

  btn.disabled = false;
  btn.textContent = 'Generate 3D World';
}

function setStepState(step, state) {
  document.getElementById('step-' + step).className = 'step ' + state;
}

function handleEvent(data) {
  if (data.step === 'expand_start') setStepState('expand', 'active');
  if (data.step === 'expand_done') {
    setStepState('expand', 'done');
    document.getElementById('step-expand-detail').textContent = data.expanded_prompt?.slice(0, 120) + '...';
    document.getElementById('debugExpandedPrompt').textContent = data.expanded_prompt || '';
    document.getElementById('debugSection').classList.add('active');
  }
  if (data.step === 'video_start') setStepState('video', 'active');
  if (data.step === 'video_polling') {
    document.getElementById('step-video-detail').textContent = 'Generating... (' + (data.elapsed || 0) + 's)';
  }
  if (data.step === 'video_done') {
    setStepState('video', 'done');
    document.getElementById('step-video-detail').textContent = 'Video ready';
    if (data.run_id) {
      const videoEl = document.getElementById('debugVideo');
      videoEl.src = '/runs/' + data.run_id + '/file?path=generated_video.mp4';
    }
  }
  if (data.step === 'world_start') setStepState('world', 'active');
  if (data.step === 'world_done') {
    setStepState('world', 'done');
    showResult(data);
    showDebugFiles(data);
  }
  if (data.step === 'error') {
    ['expand', 'video', 'world'].forEach(s => {
      const el = document.getElementById('step-' + s);
      if (el.classList.contains('active')) {
        el.className = 'step error';
        document.getElementById('step-' + s + '-detail').textContent = data.message || 'Failed';
      }
    });
  }
}

function showDebugFiles(data) {
  const filesEl = document.getElementById('debugFiles');
  const files = data.files || [];
  const runId = data.run_id;

  // Categorize files
  const categories = {
    'Final Outputs': [],
    'Depth Maps': [],
    'Normal Maps': [],
    'RGB Images': [],
    'Resized Images': [],
    'Input Frames': [],
    'Rendered Videos': [],
    'COLMAP Data': [],
    'Other': []
  };

  files.forEach(file => {
    const lower = file.toLowerCase();
    if (file.includes('gaussians.ply') || file === 'generated_video.mp4') {
      categories['Final Outputs'].push(file);
    } else if (file.includes('depth/')) {
      categories['Depth Maps'].push(file);
    } else if (file.includes('normal/')) {
      categories['Normal Maps'].push(file);
    } else if (file.includes('images/') && !file.includes('resized')) {
      categories['RGB Images'].push(file);
    } else if (file.includes('images_resized/')) {
      categories['Resized Images'].push(file);
    } else if (file.includes('input_frames/')) {
      categories['Input Frames'].push(file);
    } else if (file.includes('rendered_')) {
      categories['Rendered Videos'].push(file);
    } else if (file.includes('sparse/')) {
      categories['COLMAP Data'].push(file);
    } else {
      categories['Other'].push(file);
    }
  });

  let html = '';
  for (const [category, categoryFiles] of Object.entries(categories)) {
    if (categoryFiles.length > 0) {
      html += '<div class="file-category"><h4>' + category + ' (' + categoryFiles.length + ')</h4><div class="file-grid">';
      categoryFiles.forEach(file => {
        const url = '/runs/' + runId + '/file?path=' + encodeURIComponent(file);
        html += '<a href="' + url + '" target="_blank" class="file-item">' + file + '</a>';
      });
      html += '</div></div>';
    }
  }

  filesEl.innerHTML = html;
}

function showResult(data) {
  const result = document.getElementById('result');
  result.classList.add('active');

  const runId = data.run_id;
  document.getElementById('viewerFrame').src = '/runs/' + runId + '/view';

  const links = document.getElementById('resultLinks');
  const ply = data.gaussians_ply || 'gaussians.ply';
  links.innerHTML =
    '<a href="/runs/' + runId + '/file?path=' + encodeURIComponent(ply) + '">Download PLY</a>' +
    '<a href="https://antimatter15.com/splat/?url=' + encodeURIComponent(window.location.origin + '/runs/' + runId + '/file?path=' + encodeURIComponent(ply)) + '" target="_blank">Open in antimatter15</a>' +
    '<a href="/runs/' + runId + '" target="_blank">All files (JSON)</a>';
}
</script>
</body>
</html>"""

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
    "google-genai", "fastapi", "uvicorn", "python-multipart",
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


def _safe_reload(volume: modal.Volume) -> bool:
    """Safely reload volume, handling open file conflicts."""
    try:
        volume.reload()
        return True
    except Exception as e:
        # Common issue: files are open (being served), can't reload
        # This is OK - we'll work with stale data
        if "open files" in str(e).lower():
            return False
        # Other errors might be more serious, but don't crash
        print(f"Volume reload warning: {e}")
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


# ---------------------------------------------------------------------------
# Step 1: Expand prompt with Gemini
# ---------------------------------------------------------------------------


@app.function(
    image=light_image,
    secrets=[modal.Secret.from_name("gemini-api-key")],
    timeout=60,
)
def expand_prompt(short_prompt: str) -> str:
    """Use Gemini to expand a short scenario into a video prompt optimized for 3D reconstruction."""
    from google import genai

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not found in environment")

    client = genai.Client(api_key=api_key)

    response = client.models.generate_content(
        model="gemini-2.0-flash",
        contents=f"""You are an expert at creating prompts for AI video generation where the output video will be used for 3D Gaussian Splatting reconstruction.

Turn this scenario into a detailed 8-second video prompt optimized for 3D reconstruction:

CRITICAL RULES for good 3D reconstruction:
- PRIMARY MOTION: Smooth, slow camera movement (gentle dolly, slow orbit, or steady tracking shot)
- SCENE CONTENT: Rich geometric detail with visible surfaces, textures, and depth variation
- MINIMAL OBJECT MOTION: Objects should be mostly stationary (no fast-moving vehicles, no walking people, no rapid movement)
- Subtle environmental motion is OK: gentle breeze on leaves, slight water movement, ambient lighting - but nothing dramatic
- CONSISTENT LIGHTING: Daylight or consistent artificial lighting (avoid rapid shadow changes or flickering)
- CLEAR VISIBILITY: Photorealistic, high detail, sharp focus, good visibility throughout
- MULTIPLE VIEWPOINTS: Camera path should see the same objects from different angles for reconstruction

Scenario: {short_prompt}

Respond with ONLY the video prompt, nothing else. Make it vivid and specific, focusing on what the camera sees as it moves.""",
    )
    expanded = response.text.strip()
    print(f"Expanded prompt: {expanded}")
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
    video_bytes: bytes,
    run_id: str,
    fps: int = 1,
    target_size: int = 518,
    web_max_splats: int = DEFAULT_WEB_MAX_SPLATS,
) -> dict[str, Any]:
    """Convert video into 3D Gaussian Splat world."""
    if not video_bytes or len(video_bytes) < 1000:
        raise ValueError(f"Invalid video input: {len(video_bytes)} bytes")

    run_dir = RUNS_DIR / run_id
    _safe_mkdir(run_dir)
    for subdir in ("hub", "transformers", "torch"):
        _safe_mkdir(HF_CACHE_DIR / subdir)

    # Write video input
    video_path = run_dir / "input_video.mp4"
    try:
        video_path.write_bytes(video_bytes)
    except Exception as e:
        raise RuntimeError(f"Failed to write video file: {e}")

    if not video_path.exists() or video_path.stat().st_size == 0:
        raise RuntimeError("Video file was not written successfully")

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
            "--input_path", str(video_path),
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
@modal.concurrent(20)
@modal.asgi_app()
def viewer() -> FastAPI:
    api = FastAPI(title="Scenario Generator")

    @api.get("/", response_class=HTMLResponse)
    def frontend():
        return FRONTEND_HTML

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

        # Don't reload here - this is the hot path that causes open file conflicts
        # _safe_reload(artifacts_volume)

        try:
            run_dir = (RUNS_DIR / run_id).resolve()
            if not run_dir.exists():
                raise HTTPException(404, "run not found")

            # Security: prevent path traversal
            target = (run_dir / path).resolve()
            if not str(target).startswith(str(run_dir)):
                raise HTTPException(400, "invalid path - path traversal detected")

            if not target.exists():
                raise HTTPException(404, f"file not found: {path}")

            if not target.is_file():
                raise HTTPException(400, "path is not a file")

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
        if not prompt:
            raise HTTPException(400, "prompt is required")

        if len(prompt) > 2000:
            raise HTTPException(400, "prompt too long (max 2000 characters)")

        run_id = uuid.uuid4().hex[:12]

        async def stream():
            try:
                # Step 1: Expand prompt
                yield f"data: {json.dumps({'step': 'expand_start'})}\n\n"
                try:
                    expanded = expand_prompt.remote(prompt)
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
                    video_bytes = generate_video.remote(expanded, run_id)
                    if not video_bytes or len(video_bytes) < 1000:
                        raise ValueError(f"Video generation produced invalid output ({len(video_bytes)} bytes)")
                    yield f"data: {json.dumps({'step': 'video_done', 'run_id': run_id})}\n\n"
                except Exception as e:
                    yield f"data: {json.dumps({'step': 'error', 'message': f'Video generation failed: {str(e)}'})}\n\n"
                    return

                # Step 3: Generate 3D world
                yield f"data: {json.dumps({'step': 'world_start'})}\n\n"
                try:
                    result = generate_world.remote(video_bytes, run_id)
                    if not result or "gaussians_ply" not in result:
                        raise ValueError("World generation did not produce expected output")
                    yield f"data: {json.dumps({'step': 'world_done', **result})}\n\n"
                except Exception as e:
                    yield f"data: {json.dumps({'step': 'error', 'message': f'World generation failed: {str(e)}'})}\n\n"
                    return

            except Exception as exc:
                import traceback
                traceback.print_exc()
                yield f"data: {json.dumps({'step': 'error', 'message': f'Unexpected error: {str(exc)}'})}\n\n"

        return StreamingResponse(stream(), media_type="text/event-stream")

    return api


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------


@app.local_entrypoint()
def main(
    prompt: str = "",
    run_id: str = "",
    fps: int = 1,
    target_size: int = 518,
    viewer_url: str = "",
) -> None:
    """Generate a 3D world from a text prompt.

    Example: modal run v3/modal_app.py --prompt "road with fallen tree blocking traffic"
    """
    import sys

    if not prompt.strip():
        print("Usage: modal run v3/modal_app.py --prompt 'road with fallen tree'")
        sys.exit(1)

    run_id = run_id or uuid.uuid4().hex[:12]

    # Step 1: Expand prompt
    print(f"\n[1/3] Expanding prompt with Gemini...")
    expanded = expand_prompt.remote(prompt)
    print(f"  Expanded: {expanded}\n")

    # Step 2: Generate video
    print(f"[2/3] Generating video with Veo 3.1...")
    video_bytes = generate_video.remote(expanded, run_id)
    print(f"  Video: {len(video_bytes)} bytes\n")

    # Step 3: Generate 3D world
    print(f"[3/3] Building 3D world on H100...")
    result = generate_world.remote(video_bytes, run_id, fps=fps, target_size=target_size)
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
