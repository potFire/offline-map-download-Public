#!/usr/bin/env python3
"""Download a small, authorized XYZ tile set directly into tiles/<dataset>/<z>/<y>/<x>.<ext>.

Requires only the Python standard library. Never run against a map source unless
its license permits the requested offline storage and redistribution.
"""
import argparse
import concurrent.futures
import json
import math
import os
import pathlib
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

MERCATOR_LIMIT = 85.05112878
NASA_TEMPLATE = (
    "https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/"
    "BlueMarble_NextGeneration/default/GoogleMapsCompatible_Level8/"
    "{z}/{y}/{x}.jpeg"
)
NASA_ATTRIBUTION = (
    "Imagery provided by services from NASA's Global Imagery Browse Services (GIBS), "
    "part of NASA's Earth Science Data and Information System (ESDIS)."
)


def tile_xy(longitude, latitude, zoom):
    n = 1 << zoom
    latitude = max(-MERCATOR_LIMIT, min(MERCATOR_LIMIT, latitude))
    lat_radians = math.radians(latitude)
    x = math.floor((longitude + 180.0) / 360.0 * n)
    y = math.floor(
        (1.0 - math.asinh(math.tan(lat_radians)) / math.pi) / 2.0 * n
    )
    return max(0, min(n - 1, x)), max(0, min(n - 1, y))


def has_expected_signature(data, extension):
    if extension in ("jpg", "jpeg"):
        return data.startswith(b"\xff\xd8\xff")
    if extension == "png":
        return data.startswith(b"\x89PNG\r\n\x1a\n")
    if extension == "webp":
        return data.startswith(b"RIFF") and data[8:12] == b"WEBP"
    return False


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bbox", default="113.93,22.58,114.25,22.77",
                        help="minLongitude,minLatitude,maxLongitude,maxLatitude")
    parser.add_argument("--min-zoom", type=int, default=6)
    parser.add_argument("--max-zoom", type=int, default=8)
    parser.add_argument("--dataset", default="nasa-blue-marble")
    parser.add_argument("--tile-url", default=NASA_TEMPLATE,
                        help="Authorized HTTPS XYZ URL with {z}, {y}, {x}")
    parser.add_argument("--extension", choices=("jpeg", "jpg", "png", "webp"),
                        default="jpeg")
    parser.add_argument("--max-tiles", type=int, default=200)
    return parser.parse_args()


def validate(args):
    try:
        bbox = tuple(float(v.strip()) for v in args.bbox.split(","))
    except ValueError as exc:
        raise ValueError("bbox must be 4 comma-separated numbers") from exc
    if len(bbox) != 4 or not all(math.isfinite(v) for v in bbox):
        raise ValueError("bbox must contain 4 finite numbers")
    w, s, e, n = bbox
    if not (-180 <= w < e <= 180 and -MERCATOR_LIMIT <= s < n <= MERCATOR_LIMIT):
        raise ValueError("Invalid bounds, or bounds cross the date line")
    if not 0 <= args.min_zoom <= args.max_zoom <= 20:
        raise ValueError("Zoom levels must satisfy 0 <= min <= max <= 20")
    if args.tile_url == NASA_TEMPLATE and args.max_zoom > 8:
        raise ValueError("NASA Blue Marble tile matrix supports zoom levels 0-8")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,48}", args.dataset):
        raise ValueError("dataset must be a safe lowercase slug")
    parsed = urllib.parse.urlsplit(args.tile_url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("Use an HTTPS tile endpoint")
    if not all("{" + key + "}" in args.tile_url for key in ("x", "y", "z")):
        raise ValueError("tile URL requires {z}, {y}, and {x} placeholders")
    if not 1 <= args.max_tiles <= 500:
        raise ValueError("max-tiles must be between 1 and 500")
    return bbox


def compute_tiles(bbox, min_zoom, max_zoom, max_tiles):
    w, s, e, n = bbox
    tiles = []
    for z in range(min_zoom, max_zoom + 1):
        x0, y0 = tile_xy(w, n, z)  # north-west
        x1, y1 = tile_xy(e, s, z)  # south-east
        count = (x1 - x0 + 1) * (y1 - y0 + 1)
        if len(tiles) + count > max_tiles:
            raise ValueError(
                f"Selected extent requires more than {max_tiles} tiles. "
                "Use smaller bounds/zoom ranges, or raise the cap carefully."
            )
        tiles.extend((z, x, y) for x in range(x0, x1 + 1)
                     for y in range(y0, y1 + 1))
    return tiles


def fetch_one(task):
    z, x, y, url_template, extension, output_dir = task
    target = output_dir / str(z) / str(y) / f"{x}.{extension}"
    if target.is_file() and has_expected_signature(target.read_bytes()[:16], extension):
        return "cached", str(target)
    url = url_template.format(x=x, y=y, z=z)
    last_error = None
    for attempt in range(3):
        try:
            request = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "offline-map-download-Public/1.0 (authorized XYZ tile export)",
                    "Accept": "image/jpeg,image/png,image/webp",
                },
            )
            with urllib.request.urlopen(request, timeout=25) as response:
                if response.status != 200:
                    raise ValueError(f"HTTP {response.status}")
                data = response.read(5_000_001)
            if len(data) > 5_000_000 or not has_expected_signature(data, extension):
                raise ValueError("unexpected image type or tile too large")
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_suffix(target.suffix + ".part")
            tmp.write_bytes(data)
            os.replace(tmp, target)
            return "downloaded", str(target)
        except (OSError, ValueError, urllib.error.URLError) as exc:
            last_error = exc
            if attempt < 2:
                time.sleep((attempt + 1) * 1.5)
    raise RuntimeError(f"Tile z={z},x={x},y={y} failed: {last_error}")


def main():
    args = parse_args()
    bbox = validate(args)
    tiles = compute_tiles(bbox, args.min_zoom, args.max_zoom, args.max_tiles)
    output_dir = pathlib.Path("tiles") / args.dataset
    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"Dataset={args.dataset}; zoom={args.min_zoom}-{args.max_zoom}; "
          f"tile-count={len(tiles)}; bbox={bbox}", flush=True)
    tasks = [(z, x, y, args.tile_url, args.extension, output_dir) for z, x, y in tiles]
    downloaded, cached = 0, 0
    errors = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(fetch_one, task) for task in tasks]
        for future in concurrent.futures.as_completed(futures):
            try:
                status, filename = future.result()
                downloaded += status == "downloaded"
                cached += status == "cached"
                print(f"{status}: {filename}", flush=True)
            except Exception as exc:
                errors.append(str(exc))
                print(f"ERROR: {exc}", file=sys.stderr, flush=True)
    if errors:
        raise RuntimeError(f"{len(errors)} tiles failed; no manifest written")

    is_nasa = args.tile_url == NASA_TEMPLATE
    metadata = {
        "dataset": args.dataset,
        "source": "NASA GIBS Blue Marble (August 2004)" if is_nasa
                  else "Custom source (redistribution authorization required)",
        "attribution": NASA_ATTRIBUTION if is_nasa
                       else "Follow the authorized provider's attribution requirements.",
        "bounds_lonlat": bbox,
        "min_zoom": args.min_zoom,
        "max_zoom": args.max_zoom,
        "tile_format": args.extension,
        "tile_count": len(tiles),
        "coordinate_system": "EPSG:3857",
        "tile_scheme": "XYZ z/y/x",
    }
    (output_dir / "source.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"SUCCESS: {downloaded} newly downloaded; {cached} already present. "
          f"Saved under {output_dir}/", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"FAILED: {error}", file=sys.stderr)
        sys.exit(1)
