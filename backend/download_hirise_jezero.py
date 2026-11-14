"""Download the public Jezero HiRISE stereo DTM into the ignored local cache.

The file is about 700 MB. Downloads use HTTP byte ranges and resume safely.
"""
from __future__ import annotations

import os
import re
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

DTM_URL = (
    "https://hirise.lpl.arizona.edu/PDS/DTM/ESP/ORB_023500_023599/"
    "ESP_023524_1985_ESP_023379_1985/"
    "DTEEC_023524_1985_023379_1985_U01.IMG"
)
LABEL_URL = (
    "https://hirise.lpl.arizona.edu/PDS/DTM/ESP/ORB_023500_023599/"
    "ESP_023524_1985_ESP_023379_1985/ESP_023524_1985_RED_C_01_ORTHO.LBL"
)
CHUNK = 8 * 1024 * 1024
ASSET_DIR = Path(__file__).resolve().parent / "cache" / "hirise_jezero"
DTM_PATH = ASSET_DIR / "DTEEC_023524_1985_023379_1985_U01.IMG"
LABEL_PATH = ASSET_DIR / "ESP_023524_1985_RED_C_01_ORTHO.LBL"
ORTHO_URL = (
    "https://hirise.lpl.arizona.edu/PDS/DTM/ESP/ORB_023500_023599/"
    "ESP_023524_1985_ESP_023379_1985/ESP_023524_1985_RED_C_01_ORTHO.JP2"
)
ORTHO_PATH = ASSET_DIR / "ESP_023524_1985_RED_C_01_ORTHO.JP2"


def fetch_range(url: str, size: int, start: int, end: int, fd: int) -> int:
    expected = end - start + 1
    written = 0
    while written < expected:
        request = urllib.request.Request(url, headers={
            "Range": f"bytes={start + written}-{end}",
            "User-Agent": "Cairn-Trail-Mode/1.0 (public HiRISE DTM cache)",
        })
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                if response.status != 206:
                    raise RuntimeError(f"HiRISE server did not honor byte ranges (HTTP {response.status})")
                range_header = response.headers.get("Content-Range", "")
                match = re.match(r"bytes (\d+)-(\d+)/(\d+)", range_header)
                if not match or int(match.group(1)) != start + written or int(match.group(3)) != size:
                    raise RuntimeError("HiRISE returned an unexpected byte range")
                while written < expected:
                    data = response.read(min(1024 * 1024, expected - written))
                    if not data: break
                    os.pwrite(fd, data, start + written)
                    written += len(data)
        except Exception:
            if written >= expected: break
            time.sleep(min(8, 1 + written // (1024 * 1024)))
    return written


def download_asset(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(urllib.request.Request(url, method="HEAD"), timeout=30) as response:
        size = int(response.headers.get("Content-Length", 0))
    if size <= 0: raise RuntimeError(f"Could not read product length: {dest.name}")
    if dest.is_file() and dest.stat().st_size == size:
        print(f"Already downloaded: {dest.name}", flush=True); return
    part = dest.with_suffix(dest.suffix + ".part")
    markers = dest.parent / (dest.name + ".chunks")
    markers.mkdir(exist_ok=True)
    fd = os.open(part, os.O_CREAT | os.O_RDWR, 0o644)
    try:
        os.ftruncate(fd, size)
        ranges = [(start, min(start + CHUNK - 1, size - 1)) for start in range(0, size, CHUNK)]
        done = {int(path.stem) for path in markers.glob("*.done") if path.stem.isdigit()}
        total = sum(end - start + 1 for index, (start, end) in enumerate(ranges) if index in done)
        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = {pool.submit(fetch_range, url, size, start, end, fd): index for index, (start, end) in enumerate(ranges) if index not in done}
            for future in as_completed(futures):
                index = futures[future]
                total += future.result()
                (markers / f"{index}.done").touch()
                print(f"{dest.name}: {total / size:.0%} ({total:,} / {size:,} bytes)", flush=True)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(part, dest)
    for marker in markers.glob("*.done"): marker.unlink()
    markers.rmdir()
    print(f"HiRISE product ready: {dest}", flush=True)


def main() -> None:
    download_asset(DTM_URL, DTM_PATH)
    download_asset(LABEL_URL, LABEL_PATH)
    download_asset(ORTHO_URL, ORTHO_PATH)


if __name__ == "__main__":
    main()
