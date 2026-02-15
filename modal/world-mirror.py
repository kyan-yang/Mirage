from __future__ import annotations

import json
import os
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import quote

import modal
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from huggingface_hub import login as hf_login

APP_NAME = "hunyuanworld-mirror-modal"
REPO_URL = "https://github.com/Tencent-Hunyuan/HunyuanWorld-Mirror.git"
REPO_DIR = Path("/opt/HunyuanWorld-Mirror")
RUNS_DIR = Path("/data/runs")
HF_CACHE_DIR = Path("/cache/hf")

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
VIDEO_EXTS = {".mp4", ".avi", ".mov", ".webm", ".gif"}
SPLAT_VIEW_EXTS = {".splat", ".ply", ".ksplat"}
WEB_PREVIEW_FILENAME = "gaussians_web_preview.ply"
DEFAULT_WEB_MAX_SPLATS = 200_000

SPLAT_VIEWER_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>__TITLE__</title>
  <style>
    html, body, #viewer-root {
      width: 100%;
      height: 100%;
      margin: 0;
      background: #101217;
      color: #f2f4f8;
      font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Arial;
    }
    #viewer-root { position: fixed; inset: 0; }
    .hud {
      position: fixed;
      top: 12px;
      left: 12px;
      max-width: min(640px, calc(100vw - 24px));
      background: rgba(10, 12, 18, 0.8);
      border: 1px solid rgba(255, 255, 255, 0.14);
      border-radius: 10px;
      padding: 10px 12px;
      line-height: 1.35;
      font-size: 13px;
      backdrop-filter: blur(4px);
      z-index: 10;
    }
    .hud a { color: #9dd0ff; text-decoration: none; }
    .hud a:hover { text-decoration: underline; }
    .status { margin-top: 8px; color: #d7dbe5; }
    .status.error { color: #ffb0b0; }
    code { color: #d9e8ff; }
  </style>
</head>
<body>
  <div id="viewer-root"></div>
  <div class="hud">
    <div><strong>Run:</strong> <code>__RUN_ID__</code></div>
    <div><strong>Splat:</strong> <code>__SPLAT_PATH__</code></div>
    <div style="margin-top: 6px;">
      Controls: left drag = orbit, right drag = pan, scroll = zoom.
      Keys: <code>I</code> info, <code>P</code> point-cloud mode.
    </div>
    <div style="margin-top: 6px;">
      <a href="__FILE_URL__" target="_blank" rel="noopener">download splat</a>
    </div>
    <div style="margin-top: 6px;">
      Mode: __MODE_LABEL__ (<a href="__PREVIEW_URL__">fast preview</a> | <a href="__FULL_URL__">full quality</a>)
    </div>
    <div id="status" class="status">Loading viewer...</div>
  </div>

  <script type="module">
    const setStatus = (msg, isError = false) => {
      const el = document.getElementById("status");
      el.textContent = msg;
      el.classList.toggle("error", isError);
    };

    const root = document.getElementById("viewer-root");
    root.style.width = window.innerWidth + "px";
    root.style.height = window.innerHeight + "px";

    const splatUrl = "__FILE_URL__";

    try {
      const GaussianSplats3D = await import("https://cdn.jsdelivr.net/npm/@mkkellogg/gaussian-splats-3d@0.4.7/+esm");

      const viewer = new GaussianSplats3D.Viewer({
        rootElement: root,
        useBuiltInControls: true,
        initialCameraPosition: [0, 1.2, 3.2],
        initialCameraLookAt: [0, 0, 0],
        gpuAcceleratedSort: true,
        sharedMemoryForWorkers: true,
      });

      await viewer.addSplatScene(splatUrl, {
        showLoadingUI: true,
      });

      viewer.start();
      setStatus("Ready.");

      window.addEventListener("resize", () => {
        root.style.width = window.innerWidth + "px";
        root.style.height = window.innerHeight + "px";
      });
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      setStatus("Failed to load viewer: " + message, true);
      console.error(err);
    }
  </script>
</body>
</html>
"""

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
        "python3 -m pip install --no-cache-dir plyfile",
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


def _normalize_url(url: str) -> str:
    return url.rstrip("/")


def _resolve_viewer_base_url(explicit_viewer_url: str = "") -> str | None:
    if explicit_viewer_url.strip():
        return _normalize_url(explicit_viewer_url.strip())

    env_url = os.environ.get("WORLD_MIRROR_VIEWER_URL", "").strip()
    if env_url:
        return _normalize_url(env_url)

    try:
        deployed_viewer = modal.Function.from_name(APP_NAME, "viewer")
        web_url = deployed_viewer.get_web_url()
        if web_url:
            return _normalize_url(web_url)
    except Exception:
        pass

    return None


def _print_result_links(result: dict[str, Any], viewer_base_url: str | None = None) -> None:
    run_id = result.get("run_id")
    if not isinstance(run_id, str) or not run_id:
        return

    if not viewer_base_url:
        print(
            "Set --viewer-url https://<your-viewer-url> (or WORLD_MIRROR_VIEWER_URL) "
            "to print direct download links."
        )
        return

    def _print_file_link(label: str, rel_path: Any) -> None:
        if not isinstance(rel_path, str) or not rel_path:
            return
        print(
            f"{label}: "
            f"{viewer_base_url}/runs/{run_id}/file?path={quote(rel_path, safe='')}"
        )

    _print_file_link("gaussians_ply_url", result.get("gaussians_ply"))
    _print_file_link("web_preview_ply_url", result.get("web_preview_ply"))
    _print_file_link("refined_gaussians_ply_url", result.get("refined_gaussians_ply"))
    _print_file_link("refined_web_preview_ply_url", result.get("refined_web_preview_ply"))

    print(f"splat_viewer_url: {viewer_base_url}/runs/{run_id}/splat-viewer")
    refined_rel = result.get("refined_gaussians_ply")
    if isinstance(refined_rel, str) and refined_rel:
        print(
            "refined_splat_viewer_url: "
            f"{viewer_base_url}/runs/{run_id}/splat-viewer?path={quote(refined_rel, safe='')}"
        )


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
        stem = Path(name).stem
        out_name = stem + suffix  # suffix is already lowercased
        (input_dir / out_name).write_bytes(data)


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


def _build_web_preview_ply(
    source_ply: Path,
    max_splats: int = DEFAULT_WEB_MAX_SPLATS,
) -> tuple[Path | None, dict[str, Any]]:
    info: dict[str, Any] = {
        "source_ply": str(source_ply),
        "max_splats": max_splats,
    }

    if max_splats <= 0:
        info["status"] = "disabled"
        return None, info

    preview_path = source_ply.with_name(WEB_PREVIEW_FILENAME)
    if preview_path.exists():
        info["status"] = "existing"
        info["preview_ply"] = str(preview_path)
        return preview_path, info

    try:
        import numpy as np
        from plyfile import PlyData, PlyElement
    except Exception as exc:
        info["status"] = "missing_dependency"
        info["error"] = str(exc)
        return None, info

    try:
        ply = PlyData.read(str(source_ply))
        if "vertex" not in ply:
            info["status"] = "no_vertex_element"
            return None, info

        vertices = ply["vertex"].data
        total_vertices = int(len(vertices))
        info["source_vertices"] = total_vertices

        if total_vertices <= max_splats:
            info["status"] = "not_needed"
            info["preview_ply"] = str(source_ply)
            return source_ply, info

        rng = np.random.default_rng(0)
        indices = np.sort(rng.choice(total_vertices, size=max_splats, replace=False))
        sampled_vertices = vertices[indices]

        preview = PlyData([PlyElement.describe(sampled_vertices, "vertex")], text=False)
        preview.comments = list(ply.comments)
        preview.obj_info = list(getattr(ply, "obj_info", []))
        preview.write(str(preview_path))

        info["status"] = "created"
        info["preview_vertices"] = int(len(sampled_vertices))
        info["preview_ply"] = str(preview_path)
        return preview_path, info
    except Exception as exc:
        info["status"] = "failed"
        info["error"] = str(exc)
        return None, info


def _find_viewable_splat_path(run_dir: Path, prefer_preview: bool = True) -> Path | None:
    # Prefer ready-to-load splat formats first.
    for preferred in ("gaussians.splat", "gaussians.ksplat"):
        found = _find_artifact_path(run_dir, preferred)
        if found:
            return found

    if prefer_preview:
        preview = _find_artifact_path(run_dir, WEB_PREVIEW_FILENAME)
        if preview:
            return preview

    found_ply = _find_artifact_path(run_dir, "gaussians.ply")
    if found_ply:
        return found_ply

    matches = sorted(
        p
        for p in run_dir.rglob("*")
        if p.is_file() and p.suffix.lower() in SPLAT_VIEW_EXTS
    )
    if not matches:
        return None

    # Prioritize .splat over .ksplat over .ply when names are arbitrary.
    ext_rank = {".splat": 0, ".ksplat": 1, ".ply": 2}
    return sorted(matches, key=lambda p: (ext_rank.get(p.suffix.lower(), 9), str(p)))[0]


def _is_refine_data_dir(path: Path) -> bool:
    return (
        path.is_dir()
        and (path / "gaussians.ply").is_file()
        and (path / "images").is_dir()
        and (path / "sparse").exists()
    )


def _resolve_refine_data_dir(run_dir: Path, data_dir_hint: str = "") -> Path:
    if data_dir_hint:
        candidate_hint = Path(data_dir_hint)
        candidates = []
        if candidate_hint.is_absolute():
            candidates.append(candidate_hint)
        else:
            candidates.append(run_dir / candidate_hint)

        for candidate in candidates:
            resolved = candidate.resolve()
            if str(resolved).startswith(str(run_dir.resolve())) and _is_refine_data_dir(resolved):
                return resolved

    for candidate in (run_dir / "inputs", run_dir):
        if _is_refine_data_dir(candidate):
            return candidate

    for p in sorted(run_dir.rglob("*")):
        if p.is_dir() and _is_refine_data_dir(p):
            return p

    raise FileNotFoundError(
        "Could not find a refine-ready data dir with gaussians.ply + images/ + sparse/. "
        f"Run files: {_list_files(run_dir)}"
    )


def _find_refined_ply(result_dir: Path) -> Path | None:
    direct = result_dir / "gaussians.ply"
    if direct.exists():
        return direct

    ply_files = sorted(p for p in result_dir.rglob("*.ply") if p.is_file())
    if not ply_files:
        return None

    def _score(p: Path) -> tuple[int, float]:
        name = p.name.lower()
        score = 0
        if "gaussian" in name:
            score += 3
        if "point_cloud" in str(p).lower():
            score += 2
        if "iteration" in str(p).lower():
            score += 1
        return (score, p.stat().st_mtime)

    return sorted(ply_files, key=_score, reverse=True)[0]


def _can_import(module_name: str, env: dict[str, str] | None = None) -> bool:
    result = subprocess.run(
        ["python3", "-c", f"import {module_name}"],
        cwd=str(REPO_DIR),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0


def _module_has_attr(module_name: str, attr_name: str, env: dict[str, str] | None = None) -> bool:
    result = subprocess.run(
        [
            "python3",
            "-c",
            (
                "import importlib,sys; "
                f"m=importlib.import_module('{module_name}'); "
                f"sys.exit(0 if hasattr(m, '{attr_name}') else 1)"
            ),
        ],
        cwd=str(REPO_DIR),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0


def _candidate_pycolmap2_paths() -> list[Path]:
    out: list[Path] = []
    for p in REPO_DIR.rglob("pycolmap2.py"):
        out.append(p.parent)
    for p in REPO_DIR.rglob("pycolmap2"):
        if p.is_dir() and (p / "__init__.py").exists():
            out.append(p.parent)
    unique: list[Path] = []
    seen: set[str] = set()
    for p in out:
        k = str(p.resolve())
        if k not in seen:
            unique.append(p.resolve())
            seen.add(k)
    return unique


def _prepend_pythonpath(env: dict[str, str], paths: list[Path | str]) -> None:
    cleaned = [str(Path(p)) for p in paths if str(p).strip()]
    if not cleaned:
        return
    existing = env.get("PYTHONPATH", "")
    prefix = ":".join(cleaned)
    env["PYTHONPATH"] = f"{prefix}:{existing}" if existing else prefix


def _write_pycolmap2_compat_shim(shim_path: Path) -> None:
    shim_code = """from __future__ import annotations

from pathlib import Path

import numpy as np
import pycolmap


def _resolve_model_dir(path: str | Path) -> Path:
    p = Path(path)
    candidates = [p / "sparse" / "0", p / "sparse", p / "0", p]
    for c in candidates:
        if (c / "cameras.bin").exists() or (c / "cameras.txt").exists():
            return c
    return p


class _CompatCamera:
    def __init__(self, cam):
        self.id = int(getattr(cam, "camera_id", getattr(cam, "id", -1)))
        self.width = int(cam.width)
        self.height = int(cam.height)
        self.params = np.array(getattr(cam, "params", []), dtype=np.float64)
        model = getattr(cam, "model", None)
        self.model = getattr(model, "name", str(model))
        if len(self.params) >= 4:
            self.fx = float(self.params[0])
            self.fy = float(self.params[1])
            self.cx = float(self.params[2])
            self.cy = float(self.params[3])
        elif len(self.params) == 3:
            self.fx = float(self.params[0])
            self.fy = float(self.params[0])
            self.cx = float(self.params[1])
            self.cy = float(self.params[2])


class _CompatImage:
    def __init__(self, img):
        self.id = int(getattr(img, "image_id", getattr(img, "id", -1)))
        self.name = str(img.name)
        self.camera_id = int(img.camera_id)
        cam_from_world = img.cam_from_world()
        self._R = np.array(cam_from_world.rotation.matrix(), dtype=np.float64)
        self.tvec = np.array(cam_from_world.translation, dtype=np.float64).reshape(3)

    def qvec2rotmat(self):
        return self._R


class _CompatPoint3D:
    def __init__(self, pt):
        self.id = int(getattr(pt, "point3D_id", getattr(pt, "id", -1)))
        self.xyz = np.array(pt.xyz, dtype=np.float64)
        color = getattr(pt, "color", getattr(pt, "rgb", [255, 255, 255]))
        self.rgb = np.array(color, dtype=np.uint8)
        self.error = float(getattr(pt, "error", 0.0))
        image_ids = []
        track = getattr(pt, "track", None)
        if track is not None:
            elements = getattr(track, "elements", [])
            image_ids = [int(getattr(e, "image_id", -1)) for e in elements]
        self.image_ids = np.array(image_ids, dtype=np.int32)


class SceneManager:
    def __init__(self, path: str | Path):
        self.path = str(path)
        self._model_dir = _resolve_model_dir(path)
        self._reconstruction = None
        self.cameras = {}
        self.images = {}
        self.points3D = {}

    def _rec(self):
        if self._reconstruction is None:
            self._reconstruction = pycolmap.Reconstruction(str(self._model_dir))
        return self._reconstruction

    def load_cameras(self):
        rec = self._rec()
        self.cameras = {int(k): _CompatCamera(v) for k, v in rec.cameras.items()}

    def load_images(self):
        rec = self._rec()
        self.images = {int(k): _CompatImage(v) for k, v in rec.images.items()}

    def load_points3D(self):
        rec = self._rec()
        self.points3D = {int(k): _CompatPoint3D(v) for k, v in rec.points3D.items()}


__all__ = ["SceneManager"]
"""
    shim_path.write_text(shim_code)


def _ensure_pycolmap2_dependency(base_env: dict[str, str]) -> dict[str, str]:
    env = dict(base_env)
    if _module_has_attr("pycolmap2", "SceneManager", env=env):
        return env

    shim = REPO_DIR / "pycolmap2.py"
    if shim.exists():
        # Drop stale/incorrect shim from previous runs before trying again.
        try:
            shim.unlink()
        except Exception:
            pass

    path_candidates = _candidate_pycolmap2_paths()
    if path_candidates:
        _prepend_pythonpath(env, path_candidates)
        if _module_has_attr("pycolmap2", "SceneManager", env=env):
            return env

    install_attempts = [
        ["python3", "-m", "pip", "install", "--no-cache-dir", "pycolmap2"],
        ["python3", "-m", "pip", "install", "--no-cache-dir", "pycolmap==0.6.1"],
        ["python3", "-m", "pip", "install", "--no-cache-dir", "pycolmap"],
    ]
    install_errors: list[str] = []
    for cmd in install_attempts:
        try:
            _run(cmd, cwd=REPO_DIR, env=env)
        except Exception as exc:
            install_errors.append(f"{' '.join(cmd)} => {exc}")
        if _module_has_attr("pycolmap2", "SceneManager", env=env):
            return env

    if _module_has_attr("pycolmap", "SceneManager", env=env):
        shim.write_text("from pycolmap import SceneManager\n")
        _prepend_pythonpath(env, [REPO_DIR])
        if _module_has_attr("pycolmap2", "SceneManager", env=env):
            return env

    if _can_import("pycolmap", env=env):
        _write_pycolmap2_compat_shim(shim)
        _prepend_pythonpath(env, [REPO_DIR])
        if _module_has_attr("pycolmap2", "SceneManager", env=env):
            return env

    raise RuntimeError(
        "Missing pycolmap2.SceneManager required by simple_trainer_worldmirror.py. "
        "Automatic install attempts failed."
        + (f" Details: {' | '.join(install_errors)}" if install_errors else "")
    )


def _candidate_fused_ssim_paths() -> list[Path]:
    out: list[Path] = []
    for p in REPO_DIR.rglob("fused_ssim.py"):
        out.append(p.parent)
    for p in REPO_DIR.rglob("fused_ssim"):
        if p.is_dir() and (p / "__init__.py").exists():
            out.append(p.parent)

    unique: list[Path] = []
    seen: set[str] = set()
    for p in out:
        k = str(p.resolve())
        if k not in seen:
            unique.append(p.resolve())
            seen.add(k)
    return unique


def _write_fused_ssim_fallback_module(module_path: Path) -> None:
    module_code = """from __future__ import annotations

import torch
import torch.nn.functional as F


def _to_nchw(x: torch.Tensor) -> torch.Tensor:
    if x.ndim == 3:
        x = x.unsqueeze(0)
    if x.ndim != 4:
        raise ValueError(f"Expected 4D tensor, got shape={tuple(x.shape)}")

    # Accept both NCHW and NHWC.
    if x.shape[1] not in (1, 3, 4) and x.shape[-1] in (1, 3, 4):
        x = x.permute(0, 3, 1, 2).contiguous()
    return x.float()


def fused_ssim(x: torch.Tensor, y: torch.Tensor, *args, **kwargs) -> torch.Tensor:
    x = _to_nchw(x)
    y = _to_nchw(y)

    if x.shape != y.shape:
        raise ValueError(f"Shape mismatch: {tuple(x.shape)} vs {tuple(y.shape)}")

    c1 = 0.01 ** 2
    c2 = 0.03 ** 2
    kernel = int(kwargs.get("kernel_size", 11))
    kernel = max(3, kernel | 1)  # odd >= 3
    pad = kernel // 2

    mu_x = F.avg_pool2d(x, kernel, stride=1, padding=pad)
    mu_y = F.avg_pool2d(y, kernel, stride=1, padding=pad)

    sigma_x = F.avg_pool2d(x * x, kernel, stride=1, padding=pad) - mu_x * mu_x
    sigma_y = F.avg_pool2d(y * y, kernel, stride=1, padding=pad) - mu_y * mu_y
    sigma_xy = F.avg_pool2d(x * y, kernel, stride=1, padding=pad) - mu_x * mu_y

    num = (2.0 * mu_x * mu_y + c1) * (2.0 * sigma_xy + c2)
    den = (mu_x * mu_x + mu_y * mu_y + c1) * (sigma_x + sigma_y + c2)
    ssim_map = num / (den + 1e-12)
    return ssim_map.mean()


__all__ = ["fused_ssim"]
"""
    module_path.write_text(module_code)


def _best_effort_install_refine_packages(env: dict[str, str]) -> list[str]:
    errors: list[str] = []

    req_candidates = [
        REPO_DIR / "submodules/gsplat/examples/requirements.txt",
        REPO_DIR / "submodules/gsplat/requirements.txt",
    ]
    for req in req_candidates:
        if req.exists():
            try:
                _run(
                    ["python3", "-m", "pip", "install", "--no-cache-dir", "-r", str(req)],
                    cwd=REPO_DIR,
                    env=env,
                )
            except Exception as exc:
                errors.append(f"pip -r {req} => {exc}")

    # Proactively install common missing bits for worldmirror trainer.
    proactive_installs = [
        "pycolmap2",
        "pycolmap==0.6.1",
        "pycolmap",
        "fused-ssim",
        "fused_ssim",
        "viser",
        "tyro",
        "tensorboard",
    ]
    for pkg in proactive_installs:
        try:
            _run(
                ["python3", "-m", "pip", "install", "--no-cache-dir", pkg],
                cwd=REPO_DIR,
                env=env,
            )
        except Exception as exc:
            errors.append(f"pip install {pkg} => {exc}")

    return errors


def _ensure_fused_ssim_dependency(base_env: dict[str, str]) -> dict[str, str]:
    env = dict(base_env)
    if _can_import("fused_ssim", env=env):
        return env

    path_candidates = _candidate_fused_ssim_paths()
    if path_candidates:
        _prepend_pythonpath(env, path_candidates)
        if _can_import("fused_ssim", env=env):
            return env

    install_attempts = [
        ["python3", "-m", "pip", "install", "--no-cache-dir", "fused-ssim"],
        ["python3", "-m", "pip", "install", "--no-cache-dir", "fused_ssim"],
    ]
    install_errors: list[str] = []
    for cmd in install_attempts:
        try:
            _run(cmd, cwd=REPO_DIR, env=env)
        except Exception as exc:
            install_errors.append(f"{' '.join(cmd)} => {exc}")
        if _can_import("fused_ssim", env=env):
            return env

    shim = REPO_DIR / "fused_ssim.py"
    _write_fused_ssim_fallback_module(shim)
    _prepend_pythonpath(env, [REPO_DIR])
    if _can_import("fused_ssim", env=env):
        return env

    raise RuntimeError(
        "Missing fused_ssim module required by simple_trainer_worldmirror.py. "
        "Automatic install + fallback module setup failed."
        + (f" Details: {' | '.join(install_errors)}" if install_errors else "")
    )


def _ensure_refine_dependencies(base_env: dict[str, str]) -> dict[str, str]:
    env = dict(base_env)
    preflight_errors = _best_effort_install_refine_packages(env)

    env = _ensure_pycolmap2_dependency(env)
    env = _ensure_fused_ssim_dependency(env)

    # Log non-fatal preflight issues for debugging, but proceed if required imports are now ready.
    if preflight_errors:
        print("Refine dependency preflight warnings:")
        for err in preflight_errors:
            print(f"- {err}")
    return env


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
    web_max_splats: int = DEFAULT_WEB_MAX_SPLATS,
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
    web_preview_ply: Path | None = None
    web_preview_info: dict[str, Any] | None = None
    if gaussians_ply is not None:
        web_preview_ply, web_preview_info = _build_web_preview_ply(
            gaussians_ply,
            max_splats=web_max_splats,
        )

    artifacts_volume.commit()
    weights_volume.commit()

    return {
        "run_id": run_id,
        "run_dir": str(run_dir),
        "gaussians_ply": str(gaussians_ply.relative_to(run_dir)) if gaussians_ply else None,
        "web_preview_ply": str(web_preview_ply.relative_to(run_dir)) if web_preview_ply else None,
        "web_preview_info": web_preview_info,
        "splat_viewer": f"/runs/{run_id}/splat-viewer",
        "files": _list_files(run_dir),
    }


@app.function(
    image=image,
    gpu="H100",
    timeout=60 * 60,
    volumes={"/data": artifacts_volume, "/cache": weights_volume},
)
def refine_world(
    run_id: str,
    data_dir_hint: str = "",
    output_subdir: str = "refined",
    data_factor: int = 1,
    web_max_splats: int = DEFAULT_WEB_MAX_SPLATS,
) -> dict[str, Any]:
    run_dir = RUNS_DIR / run_id
    if not run_dir.exists() or not run_dir.is_dir():
        raise FileNotFoundError(f"run_id not found: {run_id}")

    data_dir = _resolve_refine_data_dir(run_dir, data_dir_hint=data_dir_hint)
    result_dir = (run_dir / output_subdir).resolve()
    if not str(result_dir).startswith(str(run_dir.resolve())):
        raise ValueError("output_subdir must stay inside run_dir")
    _safe_mkdir(result_dir)

    refine_script = REPO_DIR / "submodules/gsplat/examples/simple_trainer_worldmirror.py"
    if not refine_script.exists():
        raise FileNotFoundError(f"Refine script not found: {refine_script}")

    refine_args = [
        "python3",
        str(refine_script),
        "default",
        "--data_factor",
        str(data_factor),
        "--data_dir",
        str(data_dir),
        "--result_dir",
        str(result_dir),
    ]
    refine_env = _ensure_refine_dependencies(_default_hf_env(os.environ))
    _run(refine_args, cwd=REPO_DIR, env=refine_env)

    refined_ply = _find_refined_ply(result_dir)
    if refined_ply is None:
        raise FileNotFoundError(
            "Refinement finished but no .ply found in result_dir. "
            f"result_dir files: {_list_files(result_dir)}"
        )

    web_preview_ply, web_preview_info = _build_web_preview_ply(
        refined_ply,
        max_splats=web_max_splats,
    )

    artifacts_volume.commit()
    weights_volume.commit()

    return {
        "run_id": run_id,
        "data_dir_used": str(data_dir.relative_to(run_dir)),
        "refine_result_dir": str(result_dir.relative_to(run_dir)),
        "refined_gaussians_ply": str(refined_ply.relative_to(run_dir)),
        "refined_web_preview_ply": str(web_preview_ply.relative_to(run_dir)) if web_preview_ply else None,
        "refined_web_preview_info": web_preview_info,
        "splat_viewer": f"/runs/{run_id}/splat-viewer",
        "files": _list_files(result_dir),
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

    @api.get("/runs/{run_id}/splat-viewer")
    def splat_viewer(
        run_id: str,
        path: str = "",
        full: bool = False,
        max_splats: int = DEFAULT_WEB_MAX_SPLATS,
    ) -> HTMLResponse:
        run_dir = (RUNS_DIR / run_id).resolve()
        if not run_dir.exists():
            raise HTTPException(status_code=404, detail="run_id not found")

        chosen: Path | None = None
        if path:
            candidate = (run_dir / path).resolve()
            if not str(candidate).startswith(str(run_dir)):
                raise HTTPException(status_code=400, detail="invalid path")
            if not candidate.exists() or not candidate.is_file():
                raise HTTPException(status_code=404, detail="file not found")
            if candidate.suffix.lower() not in SPLAT_VIEW_EXTS:
                raise HTTPException(
                    status_code=400,
                    detail=f"path must be one of {sorted(SPLAT_VIEW_EXTS)}",
                )
            chosen = candidate
        else:
            if not full:
                base_ply = _find_artifact_path(run_dir, "gaussians.ply")
                if base_ply is not None and _find_artifact_path(run_dir, WEB_PREVIEW_FILENAME) is None:
                    preview_path, _ = _build_web_preview_ply(base_ply, max_splats=max_splats)
                    if preview_path is not None and preview_path != base_ply:
                        artifacts_volume.commit()

            chosen = _find_viewable_splat_path(run_dir, prefer_preview=not full)

        if chosen is None:
            raise HTTPException(
                status_code=404,
                detail=(
                    "No viewable splat artifact found (.splat/.ksplat/.ply). "
                    "Run infer.py with --save_gs, then check run files."
                ),
            )

        rel_path = str(chosen.relative_to(run_dir))
        file_url = f"/runs/{run_id}/file?path={quote(rel_path, safe='')}"

        path_q = f"path={quote(path, safe='')}&" if path else ""
        preview_url = f"/runs/{run_id}/splat-viewer?{path_q}full=false"
        full_url = f"/runs/{run_id}/splat-viewer?{path_q}full=true"
        mode_label = "full quality" if full else "fast preview"

        html = (
            SPLAT_VIEWER_HTML.replace("__TITLE__", f"Splat Viewer | {run_id}")
            .replace("__RUN_ID__", run_id)
            .replace("__SPLAT_PATH__", rel_path)
            .replace("__FILE_URL__", file_url)
            .replace("__MODE_LABEL__", mode_label)
            .replace("__PREVIEW_URL__", preview_url)
            .replace("__FULL_URL__", full_url)
        )
        return HTMLResponse(html)

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
    web_max_splats: int = DEFAULT_WEB_MAX_SPLATS,
    viewer_url: str = "",
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
        web_max_splats=web_max_splats,
    )
    print(json.dumps(result, indent=2))
    viewer_base_url = _resolve_viewer_base_url(viewer_url)
    _print_result_links(result, viewer_base_url=viewer_base_url)
    print("Deploy viewer with: modal deploy modal/world-mirror.py")


@app.local_entrypoint()
def refine(
    run_id: str,
    data_dir_hint: str = "",
    output_subdir: str = "refined",
    data_factor: int = 1,
    web_max_splats: int = DEFAULT_WEB_MAX_SPLATS,
    viewer_url: str = "",
) -> None:
    result = refine_world.remote(
        run_id=run_id,
        data_dir_hint=data_dir_hint,
        output_subdir=output_subdir,
        data_factor=data_factor,
        web_max_splats=web_max_splats,
    )
    print(json.dumps(result, indent=2))
    viewer_base_url = _resolve_viewer_base_url(viewer_url)
    _print_result_links(result, viewer_base_url=viewer_base_url)
