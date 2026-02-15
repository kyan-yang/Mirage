"""
Street View Data Fetcher (optimized for HunyuanWorld-Mirror)

Downloads equirectangular panoramas from Google Map Tiles API, then
reprojects into clean perspective views with proper spherical math.

Output: zero-padded sequential images (000.jpg, 001.jpg, ...) in a flat
folder, ready for infer.py --input_path.

Usage:
    python3 fetch_streetview.py --lat 37.4276085 --lng -122.1669747
    python3 fetch_streetview.py --lat 37.4276085 --lng -122.1669747 --num-views 8 --fov 80

Requires:
    - GOOGLE_MAPS_API_KEY env var
    - pip install requests Pillow numpy
"""

import os
import sys
import math
import json
import argparse
import requests
import numpy as np
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from PIL import Image
from io import BytesIO
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter

API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY", "")
TILES_BASE = "https://tile.googleapis.com"
ZOOM_LEVELS = {"low": 3, "medium": 4, "high": 5}


def create_http_client():
    session = requests.Session()
    retries = Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
    session.mount("https://", HTTPAdapter(max_retries=retries))
    return session


def create_tiles_session(http):
    resp = http.post(
        f"{TILES_BASE}/v1/createSession",
        params={"key": API_KEY},
        json={"mapType": "streetview", "language": "en-US", "region": "US"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["session"]


def get_pano_metadata(http, session_token, lat, lng, radius=50):
    resp = http.get(
        f"{TILES_BASE}/v1/streetview/metadata",
        params={"key": API_KEY, "session": session_token, "lat": lat, "lng": lng, "radius": radius},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def fetch_tile(http, session_token, pano_id, zoom, x, y):
    resp = http.get(
        f"{TILES_BASE}/v1/streetview/tiles/{zoom}/{x}/{y}",
        params={"key": API_KEY, "session": session_token, "panoId": pano_id},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.content


def stitch_panorama(http, session_token, pano_id, metadata, quality="medium"):
    zoom = ZOOM_LEVELS.get(quality, 4)
    pano_w, pano_h = metadata["imageWidth"], metadata["imageHeight"]
    tile_w, tile_h = metadata["tileWidth"], metadata["tileHeight"]

    scale = 2 ** (5 - zoom)
    sw, sh = math.ceil(pano_w / scale), math.ceil(pano_h / scale)
    cols, rows = math.ceil(sw / tile_w), math.ceil(sh / tile_h)

    canvas = Image.new("RGB", (cols * tile_w, rows * tile_h))
    print(f"  Downloading {cols * rows} tiles at zoom {zoom}...")

    tiles = {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(fetch_tile, http, session_token, pano_id, zoom, x, y): (x, y)
                   for y in range(rows) for x in range(cols)}
        for f in as_completed(futures):
            xy = futures[f]
            tiles[xy] = f.result()

    for (x, y), data in tiles.items():
        canvas.paste(Image.open(BytesIO(data)), (x * tile_w, y * tile_h))

    return canvas.crop((0, 0, sw, sh))


def equirect_to_perspective(pano: Image.Image, heading_deg: float, pitch_deg: float = 0,
                            fov_deg: float = 80, out_size: int = 720) -> Image.Image:
    """
    Proper spherical reprojection from equirectangular to perspective (rectilinear).
    """
    pano_arr = np.array(pano)
    h_pano, w_pano = pano_arr.shape[:2]

    fov = math.radians(fov_deg)
    heading = math.radians(heading_deg)
    pitch = math.radians(pitch_deg)

    f = out_size / (2 * math.tan(fov / 2))

    u = np.arange(out_size, dtype=np.float64) - out_size / 2
    v = np.arange(out_size, dtype=np.float64) - out_size / 2
    u, v = np.meshgrid(u, v)

    # Ray directions in camera space
    x, y, z = u, v, np.full_like(u, f)
    norm = np.sqrt(x**2 + y**2 + z**2)
    x, y, z = x / norm, y / norm, z / norm

    # Rotate by pitch (around x-axis)
    cp, sp = math.cos(pitch), math.sin(pitch)
    y, z = cp * y + sp * z, -sp * y + cp * z

    # Rotate by heading (around y-axis)
    ch, sh = math.cos(heading), math.sin(heading)
    x, z = ch * x + sh * z, -sh * x + ch * z

    # Spherical coordinates -> equirectangular pixel coords
    lon = np.arctan2(x, z)
    lat = np.arcsin(np.clip(y, -1, 1))

    px = np.clip((lon / (2 * math.pi) + 0.5) * w_pano, 0, w_pano - 1)
    py = np.clip((lat / math.pi + 0.5) * h_pano, 0, h_pano - 1)

    # Bilinear interpolation
    x0, y0 = np.floor(px).astype(int), np.floor(py).astype(int)
    x1, y1 = np.minimum(x0 + 1, w_pano - 1), np.minimum(y0 + 1, h_pano - 1)
    dx, dy = (px - x0)[:, :, None], (py - y0)[:, :, None]

    result = (pano_arr[y0, x0] * (1-dx) * (1-dy) + pano_arr[y0, x1] * dx * (1-dy) +
              pano_arr[y1, x0] * (1-dx) * dy + pano_arr[y1, x1] * dx * dy)

    return Image.fromarray(result.astype(np.uint8))


def compute_intrinsics(fov_deg: float, image_size: int) -> list:
    """Compute [3,3] camera intrinsics matrix from FOV and image size."""
    f = image_size / (2 * math.tan(math.radians(fov_deg) / 2))
    cx = cy = image_size / 2.0
    return [[f, 0, cx], [0, f, cy], [0, 0, 1]]


def compute_camera_pose(heading_deg: float, pitch_deg: float = 0) -> list:
    """
    Build a [4,4] camera-to-world matrix (OpenCV convention) from heading/pitch.
    For a single-point capture, translation is zero — all views share the same origin.
    """
    h = math.radians(heading_deg)
    p = math.radians(pitch_deg)

    # Rotation: heading around Y, then pitch around X
    ch, sh = math.cos(h), math.sin(h)
    cp, sp = math.cos(p), math.sin(p)

    R = [
        [ch,      sh * sp,   sh * cp,  0],
        [0,       cp,        -sp,      0],
        [-sh,     ch * sp,   ch * cp,  0],
        [0,       0,         0,        1],
    ]
    return R


def fetch_for_location(lat, lng, output_dir, quality="medium", radius=50,
                       fov=80, pitch=0, num_views=8, target_size=720):
    http = create_http_client()
    print(f"\nFetching Street View for ({lat}, {lng})...")

    session_token = create_tiles_session(http)
    metadata = get_pano_metadata(http, session_token, lat, lng, radius)

    if "panoId" not in metadata:
        print(f"  No Street View imagery found within {radius}m.")
        return None

    pano_id = metadata["panoId"]
    print(f"  Pano ID: {pano_id}")
    print(f"  Date: {metadata.get('date', 'unknown')}")
    print(f"  Size: {metadata.get('imageWidth', '?')}x{metadata.get('imageHeight', '?')}")

    # Output folder — flat, ready for infer.py --input_path
    scene_dir = output_dir / f"{lat}_{lng}"
    scene_dir.mkdir(parents=True, exist_ok=True)

    # Download and stitch full panorama
    pano_img = stitch_panorama(http, session_token, pano_id, metadata, quality)
    pano_img.save(scene_dir / "panorama_full.jpg", "JPEG", quality=95)
    print(f"  Full panorama: {pano_img.size[0]}x{pano_img.size[1]}")

    # Extract perspective views
    step = 360.0 / num_views
    headings = [i * step for i in range(num_views)]
    intrinsics = compute_intrinsics(fov, target_size)
    poses = []

    print(f"  Extracting {num_views} views (every {step:.0f}°, FOV {fov}°, {target_size}x{target_size})...")
    for i, heading in enumerate(headings):
        view = equirect_to_perspective(pano_img, heading, pitch_deg=pitch,
                                       fov_deg=fov, out_size=target_size)
        filename = f"{i:03d}.jpg"
        view.save(scene_dir / filename, "JPEG", quality=95)
        poses.append(compute_camera_pose(heading, pitch))
        print(f"  {filename} — heading {heading:.0f}°")

    # Save camera metadata for HunyuanWorld-Mirror priors
    camera_data = {
        "pano_id": pano_id,
        "lat": lat,
        "lng": lng,
        "date": metadata.get("date", ""),
        "fov_deg": fov,
        "pitch_deg": pitch,
        "num_views": num_views,
        "image_size": target_size,
        "intrinsics": intrinsics,
        "poses": poses,
        "headings": headings,
    }
    with open(scene_dir / "camera_meta.json", "w") as f:
        json.dump(camera_data, f, indent=2)

    print(f"  Camera intrinsics + poses saved to camera_meta.json")
    return pano_id


def generate_grid_points(center_lat, center_lng, grid_size, spacing_meters=50):
    points = []
    lat_per_m = 1 / 111320.0
    lng_per_m = 1 / (111320.0 * math.cos(math.radians(center_lat)))
    half = grid_size // 2
    for dy in range(-half, half + 1):
        for dx in range(-half, half + 1):
            points.append((center_lat + dy * spacing_meters * lat_per_m,
                           center_lng + dx * spacing_meters * lng_per_m))
    return points


def main():
    parser = argparse.ArgumentParser(description="Download Street View data for 3D reconstruction")
    parser.add_argument("--lat", type=float, required=True)
    parser.add_argument("--lng", type=float, required=True)
    parser.add_argument("--quality", choices=["low", "medium", "high"], default="medium")
    parser.add_argument("--radius", type=int, default=50)
    parser.add_argument("--fov", type=float, default=80, help="FOV in degrees (default: 80)")
    parser.add_argument("--pitch", type=float, default=0)
    parser.add_argument("--num-views", type=int, default=20, help="Number of views around 360 (default: 20)")
    parser.add_argument("--target-size", type=int, default=720, help="Output image size (default: 720)")
    parser.add_argument("--output", type=str, default="./scenes")
    parser.add_argument("--grid", type=int, default=0)
    parser.add_argument("--grid-spacing", type=float, default=50)

    args = parser.parse_args()

    if not API_KEY:
        print("Error: Set GOOGLE_MAPS_API_KEY environment variable.")
        sys.exit(1)

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    points = (generate_grid_points(args.lat, args.lng, args.grid, args.grid_spacing)
              if args.grid > 0 else [(args.lat, args.lng)])

    seen = set()
    for i, (lat, lng) in enumerate(points):
        print(f"\n--- Point {i+1}/{len(points)} ---")
        pid = fetch_for_location(lat, lng, output_dir, quality=args.quality, radius=args.radius,
                                 fov=args.fov, pitch=args.pitch, num_views=args.num_views,
                                 target_size=args.target_size)
        if pid and pid not in seen:
            seen.add(pid)

    print(f"\nDone! {len(seen)} unique panoramas to {output_dir}/")


if __name__ == "__main__":
    main()
