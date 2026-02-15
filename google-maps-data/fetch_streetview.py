"""
Street View Data Fetcher (optimized for HunyuanWorld-Mirror / Gaussian Splatting)

Downloads equirectangular panoramas from Google Map Tiles API, then
reprojects into clean perspective views with proper spherical math.

Supports multi-location capture: samples a grid of street view positions,
extracts views from each, and outputs everything into one flat folder
with sequential naming (000.jpg, 001.jpg, ...) and a camera_meta.json
containing intrinsics + per-image camera-to-world poses with real
translation offsets between capture positions.

Usage:
    # Single point, 20 views
    python3 fetch_streetview.py --lat 37.4260 --lng -122.1672

    # Area coverage: 7x7 grid, 30m spacing, ~100 total images
    python3 fetch_streetview.py --lat 37.4301 --lng -122.1694 --grid 7 --grid-spacing 30 --total-images 100

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

# Approx meters per degree at mid-latitudes
METERS_PER_DEG_LAT = 111320.0


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
    print(f"    Downloading {cols * rows} tiles...")

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
    pano_arr = np.array(pano)
    h_pano, w_pano = pano_arr.shape[:2]

    fov = math.radians(fov_deg)
    heading = math.radians(heading_deg)
    pitch = math.radians(pitch_deg)

    f = out_size / (2 * math.tan(fov / 2))

    u = np.arange(out_size, dtype=np.float64) - out_size / 2
    v = np.arange(out_size, dtype=np.float64) - out_size / 2
    u, v = np.meshgrid(u, v)

    x, y, z = u, v, np.full_like(u, f)
    norm = np.sqrt(x**2 + y**2 + z**2)
    x, y, z = x / norm, y / norm, z / norm

    cp, sp = math.cos(pitch), math.sin(pitch)
    y, z = cp * y + sp * z, -sp * y + cp * z

    ch, sh_ = math.cos(heading), math.sin(heading)
    x, z = ch * x + sh_ * z, -sh_ * x + ch * z

    lon = np.arctan2(x, z)
    lat = np.arcsin(np.clip(y, -1, 1))

    px = np.clip((lon / (2 * math.pi) + 0.5) * w_pano, 0, w_pano - 1)
    py = np.clip((lat / math.pi + 0.5) * h_pano, 0, h_pano - 1)

    x0, y0 = np.floor(px).astype(int), np.floor(py).astype(int)
    x1, y1 = np.minimum(x0 + 1, w_pano - 1), np.minimum(y0 + 1, h_pano - 1)
    dx, dy = (px - x0)[:, :, None], (py - y0)[:, :, None]

    result = (pano_arr[y0, x0] * (1-dx) * (1-dy) + pano_arr[y0, x1] * dx * (1-dy) +
              pano_arr[y1, x0] * (1-dx) * dy + pano_arr[y1, x1] * dx * dy)

    return Image.fromarray(result.astype(np.uint8))


def compute_intrinsics(fov_deg: float, image_size: int) -> list:
    f = image_size / (2 * math.tan(math.radians(fov_deg) / 2))
    cx = cy = image_size / 2.0
    return [[f, 0, cx], [0, f, cy], [0, 0, 1]]


def latlng_to_meters(lat, lng, ref_lat, ref_lng):
    """Convert lat/lng offset to meters relative to a reference point."""
    dx = (lng - ref_lng) * METERS_PER_DEG_LAT * math.cos(math.radians(ref_lat))
    dy = (lat - ref_lat) * METERS_PER_DEG_LAT
    return dx, dy


def compute_camera_pose(heading_deg: float, pitch_deg: float, tx: float, ty: float, tz: float = 1.6) -> list:
    """
    Build [4,4] camera-to-world matrix (OpenCV convention).
    tx/ty = ground position in meters, tz = camera height (1.6m for street view car).
    """
    h = math.radians(heading_deg)
    p = math.radians(pitch_deg)

    ch, sh_ = math.cos(h), math.sin(h)
    cp, sp = math.cos(p), math.sin(p)

    return [
        [ch,    sh_ * sp,   sh_ * cp,  tx],
        [0,     cp,         -sp,       tz],
        [-sh_,  ch * sp,    ch * cp,   ty],
        [0,     0,          0,         1],
    ]


def generate_grid_points(center_lat, center_lng, grid_size, spacing_meters=30):
    points = []
    lat_per_m = 1 / METERS_PER_DEG_LAT
    lng_per_m = 1 / (METERS_PER_DEG_LAT * math.cos(math.radians(center_lat)))
    half = grid_size // 2
    for dy in range(-half, half + 1):
        for dx in range(-half, half + 1):
            points.append((center_lat + dy * spacing_meters * lat_per_m,
                           center_lng + dx * spacing_meters * lng_per_m))
    return points


def fetch_scene(center_lat, center_lng, scene_dir, quality="medium", radius=30,
                fov=80, pitch=0, pitch_levels=None, target_size=720,
                grid_size=0, grid_spacing=30, total_images=100):
    """
    Fetch a multi-position scene. Discovers unique panos on a grid,
    distributes views across them, outputs sequentially numbered images.
    """
    http = create_http_client()
    session_token = create_tiles_session(http)
    scene_dir.mkdir(parents=True, exist_ok=True)

    # Generate sample points
    if grid_size > 0:
        points = generate_grid_points(center_lat, center_lng, grid_size, grid_spacing)
    else:
        points = [(center_lat, center_lng)]

    # Discover unique panos
    print(f"Probing {len(points)} grid points for unique panos...")
    pano_map = {}  # pano_id -> metadata + location
    for lat, lng in points:
        try:
            meta = get_pano_metadata(http, session_token, lat, lng, radius)
        except Exception:
            continue
        if "panoId" not in meta:
            continue
        pid = meta["panoId"]
        # Skip photospheres (small image size = user-uploaded)
        if meta.get("imageWidth", 0) < 10000:
            continue
        if pid not in pano_map:
            pano_map[pid] = meta
            print(f"  Found pano {pid} at ({meta.get('lat', lat):.6f}, {meta.get('lng', lng):.6f}) — {meta.get('date', '?')}")

    num_panos = len(pano_map)
    if num_panos == 0:
        print("No street view panos found in area!")
        return

    # Pitch levels
    pitches = pitch_levels if pitch_levels else [pitch]
    num_pitches = len(pitches)

    # Distribute views across panos
    views_per_pano = max(4, total_images // (num_panos * num_pitches))
    total_per_pano = views_per_pano * num_pitches

    print(f"\n{num_panos} unique panos found.")
    print(f"  {views_per_pano} headings x {num_pitches} pitch levels = {total_per_pano} views/pano")
    print(f"  ≈ {total_per_pano * num_panos} total images.\n")

    intrinsics = compute_intrinsics(fov, target_size)
    all_poses = []
    all_sources = []
    img_idx = 0

    for pano_id, meta in pano_map.items():
        pano_lat = meta.get("lat", center_lat)
        pano_lng = meta.get("lng", center_lng)

        if pano_lat == 0 and pano_lng == 0:
            continue

        print(f"  Pano {pano_id} ({pano_lat:.6f}, {pano_lng:.6f})...")
        pano_img = stitch_panorama(http, session_token, pano_id, meta, quality)

        tx, ty = latlng_to_meters(pano_lat, pano_lng, center_lat, center_lng)

        step = 360.0 / views_per_pano
        start_idx = img_idx
        for p in pitches:
            for j in range(views_per_pano):
                heading = j * step
                view = equirect_to_perspective(pano_img, heading, pitch_deg=p,
                                               fov_deg=fov, out_size=target_size)
                filename = f"{img_idx:03d}.jpg"
                view.save(scene_dir / filename, "JPEG", quality=95)

                pose = compute_camera_pose(heading, p, tx, ty)
                all_poses.append(pose)
                all_sources.append({
                    "image": filename,
                    "pano_id": pano_id,
                    "pano_lat": pano_lat,
                    "pano_lng": pano_lng,
                    "heading": heading,
                    "pitch": p,
                })
                img_idx += 1

        print(f"    {img_idx - start_idx} views extracted (idx {start_idx:03d}–{img_idx - 1:03d})")

    # Save camera metadata
    camera_data = {
        "scene_center": {"lat": center_lat, "lng": center_lng},
        "num_images": img_idx,
        "num_panos": num_panos,
        "fov_deg": fov,
        "pitch_deg": pitch,
        "image_size": target_size,
        "intrinsics": intrinsics,
        "poses": all_poses,
        "sources": all_sources,
    }
    with open(scene_dir / "camera_meta.json", "w") as f:
        json.dump(camera_data, f, indent=2)

    print(f"\nDone! {img_idx} images from {num_panos} panos saved to {scene_dir}/")
    print(f"Ready for: infer.py --input_path {scene_dir}")


def main():
    parser = argparse.ArgumentParser(description="Download Street View data for 3D reconstruction")
    parser.add_argument("--lat", type=float, required=True)
    parser.add_argument("--lng", type=float, required=True)
    parser.add_argument("--quality", choices=["low", "medium", "high"], default="medium")
    parser.add_argument("--radius", type=int, default=30, help="Pano search radius per point (default: 30)")
    parser.add_argument("--fov", type=float, default=80, help="FOV in degrees (default: 80)")
    parser.add_argument("--pitch", type=float, default=0)
    parser.add_argument("--pitch-levels", type=float, nargs="+", default=None,
                        help="Multiple pitch angles, e.g. --pitch-levels -15 15")
    parser.add_argument("--target-size", type=int, default=720, help="Output image size (default: 720)")
    parser.add_argument("--output", type=str, default="./scenes", help="Output base dir")
    parser.add_argument("--scene-name", type=str, default="", help="Scene folder name (default: auto)")
    parser.add_argument("--grid", type=int, default=0, help="NxN grid of sample points (default: single point)")
    parser.add_argument("--grid-spacing", type=float, default=30, help="Grid spacing in meters (default: 30)")
    parser.add_argument("--total-images", type=int, default=100, help="Target total images (default: 100)")

    args = parser.parse_args()

    if not API_KEY:
        print("Error: Set GOOGLE_MAPS_API_KEY environment variable.")
        sys.exit(1)

    output_dir = Path(args.output)
    scene_name = args.scene_name or f"{args.lat}_{args.lng}"
    scene_dir = output_dir / scene_name

    fetch_scene(
        args.lat, args.lng, scene_dir,
        quality=args.quality, radius=args.radius,
        fov=args.fov, pitch=args.pitch, pitch_levels=args.pitch_levels,
        target_size=args.target_size,
        grid_size=args.grid, grid_spacing=args.grid_spacing,
        total_images=args.total_images,
    )


if __name__ == "__main__":
    main()
