"""
Street View Data Fetcher
Inspired by https://github.com/stiles/streetview-dl

Downloads full 360° equirectangular panoramas and directional crops
for a given lat/lng coordinate using Google's Map Tiles API.

Usage:
    python fetch_streetview.py --lat 37.4219999 --lng -122.0840575
    python fetch_streetview.py --lat 37.4219999 --lng -122.0840575 --quality high --directions
    python fetch_streetview.py --lat 37.4219999 --lng -122.0840575 --radius 100 --grid 5

Requires:
    - GOOGLE_MAPS_API_KEY environment variable
    - pip install requests Pillow
"""

import os
import sys
import math
import argparse
import requests
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from PIL import Image
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter


API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY", "")
TILES_BASE = "https://tile.googleapis.com"

ZOOM_LEVELS = {"low": 3, "medium": 4, "high": 5}

DIRECTIONS = {
    "north":     0,
    "northeast": 45,
    "east":      90,
    "southeast": 135,
    "south":     180,
    "southwest": 225,
    "west":      270,
    "northwest": 315,
}


def create_http_client():
    session = requests.Session()
    retries = Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
    session.mount("https://", HTTPAdapter(max_retries=retries))
    return session


def create_tiles_session(http: requests.Session):
    """Create a Map Tiles API session for streetview tiles."""
    resp = http.post(
        f"{TILES_BASE}/v1/createSession",
        params={"key": API_KEY},
        json={"mapType": "streetview", "language": "en-US", "region": "US"},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["session"]


def get_pano_metadata(http: requests.Session, session_token: str, lat: float, lng: float, radius: int = 50):
    """Look up a Street View panorama by coordinates."""
    resp = http.get(
        f"{TILES_BASE}/v1/streetview/metadata",
        params={
            "key": API_KEY,
            "session": session_token,
            "lat": lat,
            "lng": lng,
            "radius": radius,
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def get_pano_metadata_by_id(http: requests.Session, session_token: str, pano_id: str):
    """Look up panorama metadata by pano ID."""
    resp = http.get(
        f"{TILES_BASE}/v1/streetview/metadata",
        params={
            "key": API_KEY,
            "session": session_token,
            "panoId": pano_id,
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def fetch_tile(http: requests.Session, session_token: str, pano_id: str, zoom: int, x: int, y: int):
    """Download a single tile."""
    url = f"{TILES_BASE}/v1/streetview/tiles/{zoom}/{x}/{y}"
    resp = http.get(
        url,
        params={
            "key": API_KEY,
            "session": session_token,
            "panoId": pano_id,
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.content


def stitch_panorama(http: requests.Session, session_token: str, pano_id: str, metadata: dict, quality: str = "medium"):
    """Download all tiles and stitch into a full equirectangular panorama."""
    zoom = ZOOM_LEVELS.get(quality, 4)

    pano_width = metadata["imageWidth"]
    pano_height = metadata["imageHeight"]
    tile_width = metadata["tileWidth"]
    tile_height = metadata["tileHeight"]

    scale = 2 ** (5 - zoom)
    scaled_width = math.ceil(pano_width / scale)
    scaled_height = math.ceil(pano_height / scale)

    cols = math.ceil(scaled_width / tile_width)
    rows = math.ceil(scaled_height / tile_height)

    canvas = Image.new("RGB", (cols * tile_width, rows * tile_height))

    print(f"  Downloading {cols * rows} tiles at zoom {zoom} ({cols}x{rows} grid)...")

    tiles = {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {}
        for y in range(rows):
            for x in range(cols):
                f = pool.submit(fetch_tile, http, session_token, pano_id, zoom, x, y)
                futures[f] = (x, y)

        for f in as_completed(futures):
            x, y = futures[f]
            tiles[(x, y)] = f.result()

    for (x, y), data in tiles.items():
        from io import BytesIO
        tile_img = Image.open(BytesIO(data))
        canvas.paste(tile_img, (x * tile_width, y * tile_height))

    canvas = canvas.crop((0, 0, scaled_width, scaled_height))
    return canvas


def crop_direction(pano: Image.Image, heading_deg: float, fov_deg: float = 90):
    """
    Crop a directional view from an equirectangular panorama.

    heading_deg: compass heading (0=north, 90=east, etc.)
    fov_deg: horizontal field of view for the crop
    """
    w, h = pano.size

    center_x = (heading_deg / 360.0) * w
    crop_width = (fov_deg / 360.0) * w
    crop_height = h // 2  # crop the middle 50% vertically (horizon band)

    left = int(center_x - crop_width / 2)
    right = int(center_x + crop_width / 2)
    top = int(h * 0.25)
    bottom = int(h * 0.75)

    if left < 0:
        # wraps around the panorama
        part_right = pano.crop((w + left, top, w, bottom))
        part_left = pano.crop((0, top, right, bottom))
        result = Image.new("RGB", (int(crop_width), bottom - top))
        result.paste(part_right, (0, 0))
        result.paste(part_left, (part_right.width, 0))
        return result
    elif right > w:
        part_left = pano.crop((left, top, w, bottom))
        part_right = pano.crop((0, top, right - w, bottom))
        result = Image.new("RGB", (int(crop_width), bottom - top))
        result.paste(part_left, (0, 0))
        result.paste(part_right, (part_left.width, 0))
        return result
    else:
        return pano.crop((left, top, right, bottom))


def fetch_for_location(lat: float, lng: float, output_dir: Path, quality: str = "medium",
                       crop_directions: bool = True, radius: int = 50, fov: float = 90):
    """Fetch the full panorama and directional crops for a single location."""
    http = create_http_client()

    print(f"\nFetching Street View for ({lat}, {lng})...")

    session_token = create_tiles_session(http)
    print("  Session created.")

    metadata = get_pano_metadata(http, session_token, lat, lng, radius)

    if "panoId" not in metadata:
        print(f"  No Street View imagery found at ({lat}, {lng}) within {radius}m radius.")
        return None

    pano_id = metadata["panoId"]
    pano_lat = metadata.get("lat", lat)
    pano_lng = metadata.get("lng", lng)
    date = metadata.get("date", "unknown")
    copyright_info = metadata.get("copyright", "")

    print(f"  Pano ID: {pano_id}")
    print(f"  Location: ({pano_lat}, {pano_lng})")
    print(f"  Date: {date}")
    print(f"  Size: {metadata.get('imageWidth', '?')}x{metadata.get('imageHeight', '?')}")

    loc_dir = output_dir / f"{lat}_{lng}"
    loc_dir.mkdir(parents=True, exist_ok=True)

    # Download and stitch the full panorama
    pano_img = stitch_panorama(http, session_token, pano_id, metadata, quality)

    pano_path = loc_dir / "panorama_full.jpg"
    pano_img.save(pano_path, "JPEG", quality=95)
    print(f"  Saved full panorama: {pano_path}")

    # Crop directional views
    if crop_directions:
        directions_dir = loc_dir / "directions"
        directions_dir.mkdir(exist_ok=True)

        for name, heading in DIRECTIONS.items():
            crop = crop_direction(pano_img, heading, fov)
            crop_path = directions_dir / f"{name}_{heading}deg.jpg"
            crop.save(crop_path, "JPEG", quality=90)
            print(f"  Saved {name} ({heading}°): {crop_path}")

    # Write metadata
    meta_path = loc_dir / "metadata.txt"
    with open(meta_path, "w") as f:
        f.write(f"pano_id: {pano_id}\n")
        f.write(f"lat: {pano_lat}\n")
        f.write(f"lng: {pano_lng}\n")
        f.write(f"date: {date}\n")
        f.write(f"copyright: {copyright_info}\n")
        f.write(f"image_width: {metadata.get('imageWidth', '')}\n")
        f.write(f"image_height: {metadata.get('imageHeight', '')}\n")
        f.write(f"quality: {quality}\n")

    print(f"  Metadata saved: {meta_path}")
    return pano_id


def generate_grid_points(center_lat: float, center_lng: float, grid_size: int, spacing_meters: float = 50):
    """
    Generate a grid of lat/lng points around a center coordinate.
    Useful for bulk-downloading street view data for an area.
    """
    points = []
    # approximate degrees per meter
    lat_per_meter = 1 / 111320.0
    lng_per_meter = 1 / (111320.0 * math.cos(math.radians(center_lat)))

    half = grid_size // 2
    for dy in range(-half, half + 1):
        for dx in range(-half, half + 1):
            lat = center_lat + dy * spacing_meters * lat_per_meter
            lng = center_lng + dx * spacing_meters * lng_per_meter
            points.append((lat, lng))
    return points


def main():
    parser = argparse.ArgumentParser(description="Download Street View panoramas and directional data")
    parser.add_argument("--lat", type=float, required=True, help="Latitude")
    parser.add_argument("--lng", type=float, required=True, help="Longitude")
    parser.add_argument("--quality", choices=["low", "medium", "high"], default="medium",
                        help="Image quality/resolution (default: medium)")
    parser.add_argument("--radius", type=int, default=50,
                        help="Search radius in meters for finding panoramas (default: 50)")
    parser.add_argument("--directions", action="store_true", default=True,
                        help="Crop directional views (N/NE/E/SE/S/SW/W/NW)")
    parser.add_argument("--no-directions", action="store_false", dest="directions",
                        help="Skip directional crops, only save full panorama")
    parser.add_argument("--fov", type=float, default=90,
                        help="Field of view for directional crops in degrees (default: 90)")
    parser.add_argument("--output", type=str, default="./output",
                        help="Output directory (default: ./output)")
    parser.add_argument("--grid", type=int, default=0,
                        help="Generate an NxN grid of points around the pin (e.g., --grid 5 for 5x5)")
    parser.add_argument("--grid-spacing", type=float, default=50,
                        help="Spacing between grid points in meters (default: 50)")

    args = parser.parse_args()

    if not API_KEY:
        print("Error: Set the GOOGLE_MAPS_API_KEY environment variable.")
        print("  export GOOGLE_MAPS_API_KEY='your-api-key'")
        sys.exit(1)

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.grid > 0:
        points = generate_grid_points(args.lat, args.lng, args.grid, args.grid_spacing)
        print(f"Generated {len(points)} grid points ({args.grid}x{args.grid}, {args.grid_spacing}m spacing)")
    else:
        points = [(args.lat, args.lng)]

    seen_panos = set()
    success_count = 0

    for i, (lat, lng) in enumerate(points):
        print(f"\n--- Point {i+1}/{len(points)} ---")
        pano_id = fetch_for_location(
            lat, lng, output_dir,
            quality=args.quality,
            crop_directions=args.directions,
            radius=args.radius,
            fov=args.fov,
        )
        if pano_id:
            if pano_id in seen_panos:
                print(f"  (Duplicate pano, already downloaded)")
            else:
                seen_panos.add(pano_id)
                success_count += 1

    print(f"\nDone! Downloaded {success_count} unique panoramas to {output_dir}/")


if __name__ == "__main__":
    main()
