"""
Debug browser — generates a local HTML page showing all files from a run.
Shows input images, depth maps, normals, videos, PLY downloads, etc.

Usage:
    # Called automatically after generation, or standalone:
    python v2/browse.py --run-id abc123 --viewer-url https://treehacks-26--world-mirror-v2-viewer.modal.run
"""

import json
import os
import tempfile
import webbrowser
from pathlib import Path
from urllib.parse import quote


def _file_url(base: str, run_id: str, path: str) -> str:
    return f"{base}/runs/{run_id}/file?path={quote(path, safe='')}"


def _categorize_files(files: list[str]) -> dict[str, list[str]]:
    categories = {
        "input_images": [],
        "generated_images": [],
        "depth_maps": [],
        "normal_maps": [],
        "videos": [],
        "splats": [],
        "colmap": [],
        "other": [],
    }
    for f in files:
        fl = f.lower()
        if fl.endswith((".jpg", ".jpeg", ".png", ".webp")):
            if "/depth/" in fl:
                categories["depth_maps"].append(f)
            elif "/normal/" in fl:
                categories["normal_maps"].append(f)
            elif "/images/" in fl or "/images_resized/" in fl:
                categories["generated_images"].append(f)
            elif f.startswith("inputs/") and "/" not in f[len("inputs/"):]:
                categories["input_images"].append(f)
            else:
                categories["other"].append(f)
        elif fl.endswith((".mp4", ".avi", ".mov", ".webm")):
            categories["videos"].append(f)
        elif fl.endswith((".ply", ".splat", ".ksplat")):
            categories["splats"].append(f)
        elif "/sparse/" in fl:
            categories["colmap"].append(f)
        elif fl.endswith(".npy"):
            pass  # skip binary numpy files
        else:
            categories["other"].append(f)
    return categories


def generate_browse_html(run_id: str, base_url: str, files: list[str]) -> str:
    cats = _categorize_files(files)

    def img_grid(file_list: list[str], max_show: int = 50) -> str:
        if not file_list:
            return "<p style='color:#666'>None</p>"
        html = '<div class="grid">'
        for f in file_list[:max_show]:
            url = _file_url(base_url, run_id, f)
            label = f.split("/")[-1]
            html += f'''<div class="card">
                <a href="{url}" target="_blank"><img src="{url}" loading="lazy" /></a>
                <div class="label">{label}</div>
            </div>'''
        if len(file_list) > max_show:
            html += f'<p style="color:#888">...and {len(file_list) - max_show} more</p>'
        html += "</div>"
        return html

    def file_list_html(file_list: list[str]) -> str:
        if not file_list:
            return "<p style='color:#666'>None</p>"
        html = "<ul>"
        for f in file_list:
            url = _file_url(base_url, run_id, f)
            size_hint = ""
            if f.endswith(".ply"):
                size_hint = " (PLY)"
            html += f'<li><a href="{url}" target="_blank">{f}</a>{size_hint}</li>'
        html += "</ul>"
        return html

    def video_embeds(file_list: list[str]) -> str:
        if not file_list:
            return "<p style='color:#666'>None</p>"
        html = '<div class="video-grid">'
        for f in file_list:
            url = _file_url(base_url, run_id, f)
            label = f.split("/")[-1]
            html += f'''<div class="video-card">
                <video controls preload="metadata" src="{url}"></video>
                <div class="label">{label}</div>
            </div>'''
        html += "</div>"
        return html

    viewer_url = f"{base_url}/runs/{run_id}/splat-viewer"
    all_files_url = f"{base_url}/runs/{run_id}"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>Debug: {run_id}</title>
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ background:#111; color:#eee; font-family:-apple-system,system-ui,sans-serif; padding:20px; max-width:1400px; margin:0 auto; }}
  h1 {{ color:#4a9eff; margin-bottom:8px; }}
  h2 {{ color:#ccc; margin:24px 0 12px; border-bottom:1px solid #333; padding-bottom:6px; }}
  a {{ color:#5db3ff; text-decoration:none; }}
  a:hover {{ text-decoration:underline; }}
  .meta {{ color:#888; margin-bottom:16px; }}
  .links {{ display:flex; gap:16px; margin:12px 0; flex-wrap:wrap; }}
  .links a {{ background:#222; border:1px solid #444; padding:8px 16px; border-radius:6px; }}
  .links a:hover {{ background:#333; }}
  .grid {{ display:grid; grid-template-columns:repeat(auto-fill, minmax(160px, 1fr)); gap:8px; }}
  .card {{ background:#1a1a1a; border:1px solid #333; border-radius:6px; overflow:hidden; }}
  .card img {{ width:100%; height:140px; object-fit:cover; display:block; }}
  .card .label {{ padding:4px 6px; font-size:11px; color:#888; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
  .video-grid {{ display:grid; grid-template-columns:repeat(auto-fill, minmax(320px, 1fr)); gap:12px; }}
  .video-card {{ background:#1a1a1a; border:1px solid #333; border-radius:6px; overflow:hidden; }}
  .video-card video {{ width:100%; display:block; }}
  .video-card .label {{ padding:4px 8px; font-size:12px; color:#888; }}
  ul {{ list-style:none; }}
  ul li {{ padding:4px 0; }}
  ul li a {{ font-family:monospace; font-size:13px; }}
  .stats {{ display:grid; grid-template-columns:repeat(auto-fit, minmax(150px, 1fr)); gap:8px; margin:12px 0; }}
  .stat {{ background:#1a1a1a; border:1px solid #333; border-radius:6px; padding:12px; text-align:center; }}
  .stat .num {{ font-size:24px; color:#4a9eff; font-weight:bold; }}
  .stat .lbl {{ font-size:12px; color:#888; margin-top:4px; }}
</style>
</head>
<body>
<h1>Run: {run_id}</h1>
<div class="meta">{len(files)} total files</div>

<div class="links">
  <a href="{viewer_url}" target="_blank">Open Splat Viewer</a>
  <a href="{viewer_url}?full=true" target="_blank">Full Quality Viewer</a>
  <a href="{all_files_url}" target="_blank">JSON File List</a>
</div>

<div class="stats">
  <div class="stat"><div class="num">{len(cats['input_images'])}</div><div class="lbl">Input Images</div></div>
  <div class="stat"><div class="num">{len(cats['generated_images'])}</div><div class="lbl">Generated Views</div></div>
  <div class="stat"><div class="num">{len(cats['depth_maps'])}</div><div class="lbl">Depth Maps</div></div>
  <div class="stat"><div class="num">{len(cats['splats'])}</div><div class="lbl">Splat Files</div></div>
  <div class="stat"><div class="num">{len(cats['videos'])}</div><div class="lbl">Videos</div></div>
</div>

<h2>Splat Files (download)</h2>
{file_list_html(cats['splats'])}

<h2>Input Images (street view)</h2>
{img_grid(cats['input_images'])}

<h2>Generated Multi-View Images</h2>
{img_grid(cats['generated_images'])}

<h2>Depth Maps</h2>
{img_grid(cats['depth_maps'])}

<h2>Normal Maps</h2>
{img_grid(cats['normal_maps'])}

<h2>Videos</h2>
{video_embeds(cats['videos'])}

<h2>COLMAP Data</h2>
{file_list_html(cats['colmap'])}

<h2>Other Files</h2>
{file_list_html(cats['other'])}

</body>
</html>"""


def open_browse_page(run_id: str, base_url: str, files: list[str]) -> str:
    """Generate debug HTML and open in browser. Returns the HTML file path."""
    html = generate_browse_html(run_id, base_url, files)
    tmp = Path(tempfile.gettempdir()) / f"world_mirror_debug_{run_id}.html"
    tmp.write_text(html)
    print(f"\nDebug page: file://{tmp}")
    webbrowser.open(f"file://{tmp}")
    return str(tmp)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Open debug browser for a run")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--viewer-url", required=True)
    parser.add_argument("--files-json", default="", help="JSON file list, or fetch from viewer")
    args = parser.parse_args()

    if args.files_json:
        files = json.loads(args.files_json)
    else:
        import requests
        resp = requests.get(f"{args.viewer_url}/runs/{args.run_id}")
        resp.raise_for_status()
        files = resp.json()["files"]

    open_browse_page(args.run_id, args.viewer_url, files)
