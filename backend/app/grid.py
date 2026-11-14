"""Convert the cached/live MOLA response into a bounded routing grid."""
from __future__ import annotations
import array
import base64
import math
import sys
from dataclasses import dataclass

KM_PER_DEGREE = 59.15


@dataclass
class MarsGrid:
    width: int
    height: int
    elevations_m: list[float]
    slopes_deg: list[float]
    bounds: dict[str, float]
    resolution_m: float
    elevation_type: str = "measured"
    slope_type: str = "derived"

    def index(self, x: int, y: int) -> int:
        return y * self.width + x

    def coordinate(self, x: int, y: int) -> tuple[float, float]:
        lon = self.bounds["lo0"] + x / max(self.width - 1, 1) * (self.bounds["lo1"] - self.bounds["lo0"])
        lat = self.bounds["la1"] - y / max(self.height - 1, 1) * (self.bounds["la1"] - self.bounds["la0"])
        return lon, lat

    def cell(self, lon: float, lat: float) -> tuple[int, int]:
        b = self.bounds
        if not (b["lo0"] <= lon <= b["lo1"] and b["la0"] <= lat <= b["la1"]):
            raise ValueError("Waypoint lies outside the DEM bounds")
        x = round((lon - b["lo0"]) / (b["lo1"] - b["lo0"]) * (self.width - 1))
        y = round((b["la1"] - lat) / (b["la1"] - b["la0"]) * (self.height - 1))
        return int(x), int(y)


def _decode_elevations(payload: dict) -> tuple[list[float], int, int]:
    width, height = int(payload["w"]), int(payload["h"])
    raw = base64.b64decode(payload["z"], validate=True)
    values = array.array("f")
    values.frombytes(raw)
    if sys.byteorder == "big":
        values.byteswap()
    if len(values) != width * height:
        raise ValueError("DEM dimensions do not match its elevation data")
    return [float(value) for value in values], width, height


def _downsample(values: list[float], width: int, height: int, limit: int = 220):
    if max(width, height) <= limit:
        return values, width, height
    out_width = min(limit, width)
    out_height = min(limit, height)
    sampled = []
    for y in range(out_height):
        sy = round(y * (height - 1) / max(out_height - 1, 1))
        for x in range(out_width):
            sx = round(x * (width - 1) / max(out_width - 1, 1))
            sampled.append(values[sy * width + sx])
    return sampled, out_width, out_height


def _slope_grid(values: list[float], width: int, height: int, bounds: dict[str, float]) -> list[float]:
    dlon = (bounds["lo1"] - bounds["lo0"]) / max(width - 1, 1)
    dlat = (bounds["la1"] - bounds["la0"]) / max(height - 1, 1)
    slopes = [0.0] * (width * height)
    for y in range(height):
        for x in range(width):
            left, right = max(0, x - 1), min(width - 1, x + 1)
            top, bottom = max(0, y - 1), min(height - 1, y + 1)
            lon, lat = bounds["lo0"] + x * dlon, bounds["la1"] - y * dlat
            dx = max((right - left) * dlon * KM_PER_DEGREE * 1000 * math.cos(math.radians(lat)), 1e-8)
            dy = max((bottom - top) * dlat * KM_PER_DEGREE * 1000, 1e-8)
            dzdx = (values[y * width + right] - values[y * width + left]) / dx
            dzdy = (values[bottom * width + x] - values[top * width + x]) / dy
            slopes[y * width + x] = math.degrees(math.atan(math.hypot(dzdx, dzdy)))
    return slopes


def from_dem(payload: dict) -> MarsGrid:
    """Decode and downsample the prototype DEM payload, deriving cell slopes."""
    bounds = {key: float(payload["b"][key]) for key in ("lo0", "la0", "lo1", "la1")}
    if bounds["lo0"] >= bounds["lo1"] or bounds["la0"] >= bounds["la1"]:
        raise ValueError("DEM bounds must have positive width and height")
    values, source_width, source_height = _decode_elevations(payload)
    values, width, height = _downsample(values, source_width, source_height)
    # The returned resolution reflects the grid after bounded downsampling.
    resolution=max(float(payload["res"])*source_width/max(width,1),
                   float(payload["res"])*source_height/max(height,1))
    return MarsGrid(width, height, values, _slope_grid(values, width, height, bounds), bounds,
                    resolution, str(payload.get("value_type", "measured")), "derived")


def from_elevations(values, width: int, height: int, bounds: dict[str, float], resolution_m: float = 463) -> MarsGrid:
    """Build a grid from an in-memory fixture (also useful to downstream callers)."""
    if len(values) != width * height:
        raise ValueError("Elevation count does not match grid dimensions")
    copied = [float(v) for v in values]
    return MarsGrid(width, height, copied, _slope_grid(copied, width, height, bounds),
                    dict(bounds), float(resolution_m))
