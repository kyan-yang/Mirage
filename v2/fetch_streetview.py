"""
Street View fetcher with geocoding.
Fetches panoramas from Google Map Tiles API, reprojects to perspective views.
"""

import os
import math
import json
import requests
import numpy as np
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from PIL import Image
from io import BytesIO
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter

TILES_BASE = "https://tile.googleapis.com"
ZOOM_LEVELS = {"low": 3, "medium": 4, "high": 5}
METERS_PER_DEG_LAT = 111320.0


def get_api_key() -> str:
    key = os.environ.get("GOOGLE_MAPS_API_KEY", "")
    if not key:
        raise RuntimeError("Set GOOGLE_MAPS_API_KEY environment variable")
    return key


def geocode_address(address: str) -> tuple[float, float]:
    """Convert an address string to (lat, lng). Tries Google, falls back to OpenStreetMap."""
    # Try Google Geocoding API first
    try:
        api_key = get_api_key()
        resp = requests.get(
            "https://maps.googleapis.com/maps/api/geocode/json",
            params={"address": address, "key": api_key},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        if data["status"] == "OK" and data["results"]:
            loc = data["results"][0]["geometry"]["location"]
            print(f"Geocoded '{address}' -> ({loc['lat']:.6f}, {loc['lng']:.6f})")
            return loc["lat"], loc["lng"]
        print(f"Google geocoding failed ({data['status']}), trying OpenStreetMap...")
    except Exception as exc:
        print(f"Google geocoding error ({exc}), trying OpenStreetMap...")

    # Fallback: OpenStreetMap Nominatim (free, no API key)
    resp = requests.get(
        "https://nominatim.openstreetmap.org/search",
        params={"q": address, "format": "json", "limit": 1},
        headers={"User-Agent": "world-mirror-hackathon/1.0"},
        timeout=10,
    )
    resp.raise_for_status()
    results = resp.json()
    if not results:
        raise ValueError(f"Could not geocode '{address}' with any provider")
    lat, lng = float(results[0]["lat"]), float(results[0]["lon"])
    print(f"Geocoded '{address}' -> ({lat:.6f}, {lng:.6f})")
    return lat, lng


def _http_client():
    session = requests.Session()
    retries = Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
    session.mount("https://", HTTPAdapter(max_retries=retries))
    return session


def _create_tiles_session(http):
    api_key = get_api_key()
    resp = http.post(
        f"{TILES_BASE}/v1/createSession",
        params={"key": api_key},
        json={"mapType": "streetview", "language": "en-US", "region": "US"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["session"]


def _get_pano_metadata(http, session_token, lat, lng, radius=50):
    api_key = get_api_key()
    resp = http.get(
        f"{TILES_BASE}/v1/streetview/metadata",
        params={"key": api_key, "session": session_token, "lat": lat, "lng": lng, "radius": radius},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def _fetch_tile(http, session_token, pano_id, zoom, x, y):
    api_key = get_api_key()
    resp = http.get(
        f"{TILES_BASE}/v1/streetview/tiles/{zoom}/{x}/{y}",
        params={"key": api_key, "session": session_token, "panoId": pano_id},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.content


def _stitch_panorama(http, session_token, pano_id, metadata, quality="medium"):
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
        futures = {
            pool.submit(_fetch_tile, http, session_token, pano_id, zoom, x, y): (x, y)
            for y in range(rows) for x in range(cols)
        }
        for f in as_completed(futures):
            xy = futures[f]
            tiles[xy] = f.result()

    for (x, y), data in tiles.items():
        canvas.paste(Image.open(BytesIO(data)), (x * tile_w, y * tile_h))

    return canvas.crop((0, 0, sw, sh))


def _equirect_to_perspective(pano, heading_deg, pitch_deg=0, fov_deg=80, out_size=720):
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

    result = (
        pano_arr[y0, x0] * (1 - dx) * (1 - dy)
        + pano_arr[y0, x1] * dx * (1 - dy)
        + pano_arr[y1, x0] * (1 - dx) * dy
        + pano_arr[y1, x1] * dx * dy
    )
    return Image.fromarray(result.astype(np.uint8))


def _compute_intrinsics(fov_deg, image_size):
    f = image_size / (2 * math.tan(math.radians(fov_deg) / 2))
    cx = cy = image_size / 2.0
    return [[f, 0, cx], [0, f, cy], [0, 0, 1]]


def _latlng_to_meters(lat, lng, ref_lat, ref_lng):
    dx = (lng - ref_lng) * METERS_PER_DEG_LAT * math.cos(math.radians(ref_lat))
    dy = (lat - ref_lat) * METERS_PER_DEG_LAT
    return dx, dy


def _compute_camera_pose(heading_deg, pitch_deg, tx, ty, tz=1.6):
    h = math.radians(heading_deg)
    p = math.radians(pitch_deg)
    ch, sh_ = math.cos(h), math.sin(h)
    cp, sp = math.cos(p), math.sin(p)
    return [
        [ch, sh_ * sp, sh_ * cp, tx],
        [0, cp, -sp, tz],
        [-sh_, ch * sp, ch * cp, ty],
        [0, 0, 0, 1],
    ]


def _generate_grid_points(center_lat, center_lng, grid_size, spacing_meters=30):
    points = []
    lat_per_m = 1 / METERS_PER_DEG_LAT
    lng_per_m = 1 / (METERS_PER_DEG_LAT * math.cos(math.radians(center_lat)))
    half = grid_size // 2
    for dy in range(-half, half + 1):
        for dx in range(-half, half + 1):
            points.append((
                center_lat + dy * spacing_meters * lat_per_m,
                center_lng + dx * spacing_meters * lng_per_m,
            ))
    return points


def _bearing_between(lat1, lng1, lat2, lng2):
    """Compute bearing (heading) in degrees from point 1 to point 2."""
    lat1, lng1, lat2, lng2 = map(math.radians, [lat1, lng1, lat2, lng2])
    dlng = lng2 - lng1
    x = math.sin(dlng) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlng)
    bearing = math.degrees(math.atan2(x, y))
    return bearing % 360


def _generate_route_points(start_lat, start_lng, end_lat, end_lng, num_points):
    """Sample evenly spaced points along the line from start to end."""
    points = []
    for i in range(num_points):
        t = i / max(num_points - 1, 1)
        lat = start_lat + t * (end_lat - start_lat)
        lng = start_lng + t * (end_lng - start_lng)
        points.append((lat, lng))
    return points


def fetch_route(
    start_lat: float,
    start_lng: float,
    end_lat: float,
    end_lng: float,
    scene_dir: Path,
    quality: str = "medium",
    radius: int = 50,
    fov: float = 80,
    pitch: float = 0,
    pitch_levels: list[float] | None = None,
    target_size: int = 720,
    num_points: int = 10,
    total_images: int = 100,
) -> Path:
    """
    Fetch street view images along a route (line from start to end).
    Full 360 views at each pano position for maximum overlap between adjacent points.
    """
    http = _http_client()
    session_token = _create_tiles_session(http)
    scene_dir.mkdir(parents=True, exist_ok=True)

    sample_points = _generate_route_points(start_lat, start_lng, end_lat, end_lng, num_points)
    route_bearing = _bearing_between(start_lat, start_lng, end_lat, end_lng)
    print(f"Route: {route_bearing:.1f} deg bearing, sampling {num_points} points...")

    # Find unique panos along the route (ordered)
    pano_list = []
    seen_panos = set()
    for i, (lat, lng) in enumerate(sample_points):
        try:
            meta = _get_pano_metadata(http, session_token, lat, lng, radius)
        except Exception:
            continue
        if "panoId" not in meta or meta.get("imageWidth", 0) < 10000:
            continue
        pid = meta["panoId"]
        if pid in seen_panos:
            continue
        seen_panos.add(pid)
        pano_list.append((pid, meta))
        print(f"  Point {i}: pano {pid} at ({meta.get('lat', lat):.6f}, {meta.get('lng', lng):.6f})")

    if not pano_list:
        raise RuntimeError("No street view panoramas found along this route")

    num_panos = len(pano_list)
    pitches = pitch_levels if pitch_levels else [pitch]
    num_pitches = len(pitches)
    views_per_pano = max(4, total_images // (num_panos * num_pitches))

    print(f"\n{num_panos} panos along route, {views_per_pano} headings x {num_pitches} pitches = {views_per_pano * num_pitches} views each")

    center_lat = (start_lat + end_lat) / 2
    center_lng = (start_lng + end_lng) / 2
    intrinsics = _compute_intrinsics(fov, target_size)
    all_poses = []
    all_sources = []
    img_idx = 0

    for pano_id, meta in pano_list:
        pano_lat = meta.get("lat", center_lat)
        pano_lng = meta.get("lng", center_lng)
        if pano_lat == 0 and pano_lng == 0:
            continue

        print(f"  Fetching pano {pano_id}...")
        pano_img = _stitch_panorama(http, session_token, pano_id, meta, quality)
        tx, ty = _latlng_to_meters(pano_lat, pano_lng, center_lat, center_lng)

        step = 360.0 / views_per_pano
        for p in pitches:
            for j in range(views_per_pano):
                heading = j * step
                view = _equirect_to_perspective(pano_img, heading, pitch_deg=p, fov_deg=fov, out_size=target_size)
                filename = f"{img_idx:03d}.jpg"
                view.save(scene_dir / filename, "JPEG", quality=95)

                pose = _compute_camera_pose(heading, p, tx, ty)
                all_poses.append(pose)
                all_sources.append({
                    "image": filename,
                    "pano_id": pano_id,
                    "heading": heading,
                    "pitch": p,
                })
                img_idx += 1

    camera_data = {
        "scene_center": {"lat": center_lat, "lng": center_lng},
        "route": {
            "start": {"lat": start_lat, "lng": start_lng},
            "end": {"lat": end_lat, "lng": end_lng},
            "bearing": route_bearing,
        },
        "num_images": img_idx,
        "num_panos": num_panos,
        "fov_deg": fov,
        "image_size": target_size,
        "intrinsics": intrinsics,
        "poses": all_poses,
        "sources": all_sources,
    }
    with open(scene_dir / "camera_meta.json", "w") as f:
        json.dump(camera_data, f, indent=2)

    print(f"\nDone! {img_idx} images from {num_panos} panos along route saved to {scene_dir}/")
    return scene_dir


def fetch_scene(
    center_lat: float,
    center_lng: float,
    scene_dir: Path,
    quality: str = "medium",
    radius: int = 30,
    fov: float = 80,
    pitch: float = 0,
    pitch_levels: list[float] | None = None,
    target_size: int = 720,
    grid_size: int = 0,
    grid_spacing: float = 30,
    total_images: int = 20,
) -> Path:
    """
    Fetch street view images for a location.
    Returns the scene_dir path with images + camera_meta.json.
    """
    http = _http_client()
    session_token = _create_tiles_session(http)
    scene_dir.mkdir(parents=True, exist_ok=True)

    if grid_size > 0:
        points = _generate_grid_points(center_lat, center_lng, grid_size, grid_spacing)
    else:
        points = [(center_lat, center_lng)]

    print(f"Probing {len(points)} points for street view panos...")
    pano_map = {}
    for lat, lng in points:
        try:
            meta = _get_pano_metadata(http, session_token, lat, lng, radius)
        except Exception:
            continue
        if "panoId" not in meta:
            continue
        pid = meta["panoId"]
        if meta.get("imageWidth", 0) < 10000:
            continue
        if pid not in pano_map:
            pano_map[pid] = meta
            print(f"  Found pano {pid} at ({meta.get('lat', lat):.6f}, {meta.get('lng', lng):.6f})")

    if not pano_map:
        raise RuntimeError("No street view panoramas found at this location")

    pitches = pitch_levels if pitch_levels else [pitch]
    num_pitches = len(pitches)
    num_panos = len(pano_map)
    views_per_pano = max(4, total_images // (num_panos * num_pitches))

    print(f"\n{num_panos} panos, {views_per_pano} views each, {num_pitches} pitch levels")

    intrinsics = _compute_intrinsics(fov, target_size)
    all_poses = []
    all_sources = []
    img_idx = 0

    for pano_id, meta in pano_map.items():
        pano_lat = meta.get("lat", center_lat)
        pano_lng = meta.get("lng", center_lng)
        if pano_lat == 0 and pano_lng == 0:
            continue

        print(f"  Fetching pano {pano_id}...")
        pano_img = _stitch_panorama(http, session_token, pano_id, meta, quality)
        tx, ty = _latlng_to_meters(pano_lat, pano_lng, center_lat, center_lng)

        step = 360.0 / views_per_pano
        for p in pitches:
            for j in range(views_per_pano):
                heading = j * step
                view = _equirect_to_perspective(pano_img, heading, pitch_deg=p, fov_deg=fov, out_size=target_size)
                filename = f"{img_idx:03d}.jpg"
                view.save(scene_dir / filename, "JPEG", quality=95)

                pose = _compute_camera_pose(heading, p, tx, ty)
                all_poses.append(pose)
                all_sources.append({
                    "image": filename,
                    "pano_id": pano_id,
                    "heading": heading,
                    "pitch": p,
                })
                img_idx += 1

    camera_data = {
        "scene_center": {"lat": center_lat, "lng": center_lng},
        "num_images": img_idx,
        "num_panos": num_panos,
        "fov_deg": fov,
        "image_size": target_size,
        "intrinsics": intrinsics,
        "poses": all_poses,
        "sources": all_sources,
    }
    with open(scene_dir / "camera_meta.json", "w") as f:
        json.dump(camera_data, f, indent=2)

    print(f"\nDone! {img_idx} images saved to {scene_dir}/")
    return scene_dir
