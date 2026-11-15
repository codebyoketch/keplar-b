"""Cairn Trail Mode API.

Serves the /api contract used by the React frontend (src/main.js, src/Map3DView.js).
All terrain and evidence is deterministic and synthetic; see planning.DATA_STATUS.
Run from the repository root:

    backend/.venv/bin/uvicorn app:app --app-dir backend --host 127.0.0.1 --port 8000
"""

import copy
import io
import json
import math
import os
import random
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles

import planning

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
PARAMS_FILE = Path(os.environ.get("CAIRN_PARAMS_FILE", DATA_DIR / "params.json"))
DIST_DIR = BASE_DIR.parent / "dist"

planning.PARAMS_PATH = PARAMS_FILE

app = FastAPI(title="Cairn Trail Mode API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Params
# ---------------------------------------------------------------------------

def load_params():
    if PARAMS_FILE.exists():
        try:
            data = json.loads(PARAMS_FILE.read_text())
            if isinstance(data, dict) and "reserve_minimums" in data:
                merged = planning.default_params()
                merged.update(data)
                return merged
        except (OSError, ValueError):
            pass
    return planning.default_params()


def save_params(params):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    PARAMS_FILE.write_text(json.dumps(params, indent=2))


# ---------------------------------------------------------------------------
# Basemap rendering (synthetic, offline-safe)
# ---------------------------------------------------------------------------

_BASEMAP_CACHE = {}
_BASEMAP_SIZE = 800
_BASEMAP_SAMPLES = 300


def _hash2(ix, iy, seed):
    value = math.sin(ix * 127.1 + iy * 311.7 + seed * 74.7) * 43758.5453
    return value - math.floor(value)


def _smoothstep(t):
    return t * t * (3 - 2 * t)


def _value_noise(x, y, seed):
    ix, iy = math.floor(x), math.floor(y)
    fx, fy = _smoothstep(x - ix), _smoothstep(y - iy)
    a = _hash2(ix, iy, seed)
    b = _hash2(ix + 1, iy, seed)
    c = _hash2(ix, iy + 1, seed)
    d = _hash2(ix + 1, iy + 1, seed)
    return (a + (b - a) * fx) + ((c + (d - c) * fx) - (a + (b - a) * fx)) * fy


def _fbm(u, v, seed=7):
    total, amplitude, scale = 0.0, 0.5, 3.0
    for octave in range(5):
        total += amplitude * _value_noise(u * scale, v * scale, seed + octave)
        scale *= 2.1
        amplitude *= 0.5
    return total / 0.97


def _craters(seed=11, count=14):
    rng = random.Random(seed)
    return [(rng.uniform(0.02, 0.98), rng.uniform(0.02, 0.98), rng.uniform(0.012, 0.06)) for _ in range(count)]

_PALETTES = {
    "thermal": [(32, 22, 40), (78, 40, 58), (140, 66, 58), (202, 108, 64), (247, 185, 106)],
    "mineralogy": [(24, 30, 34), (42, 62, 58), (74, 92, 78), (128, 120, 92), (196, 168, 120)],
    "gray": [(28, 28, 30), (64, 64, 66), (112, 112, 114), (168, 168, 170), (228, 228, 226)],
    "color": [(46, 26, 20), (96, 50, 34), (148, 82, 52), (196, 128, 82), (232, 178, 122)],
}


def _smooth_elevation(lon, lat):
    """Low-frequency relief only; keeps the basemap from showing DEM banding."""
    u = (lon - planning.AREA["lo0"]) / (planning.AREA["lo1"] - planning.AREA["lo0"])
    v = (lat - planning.AREA["la0"]) / (planning.AREA["la1"] - planning.AREA["la0"])
    return (
        900.0
        + 420.0 * math.sin(6.2 * u + 1.1) * math.cos(5.1 * v)
        + 240.0 * math.sin(11.0 * u - 3.0 * v)
        + 160.0 * math.cos(9.0 * v + 2.0 * u)
    )


def _palette_for(layer):
    label = (layer or "").lower()
    if "themis" in label or "thermal" in label:
        return _PALETTES["thermal"]
    if "crism" in label or "mineral" in label:
        return _PALETTES["mineralogy"]
    if "ctx" in label or "hirise" in label or "gray" in label:
        return _PALETTES["gray"]
    return _PALETTES["color"]


def _lerp_palette(palette, t):
    t = min(max(t, 0.0), 1.0) * (len(palette) - 1)
    index = min(int(t), len(palette) - 2)
    frac = t - index
    a, b = palette[index], palette[index + 1]
    return tuple(int(a[i] + (b[i] - a[i]) * frac) for i in range(3))


def render_basemap(box, layer):
    from PIL import Image

    key = (
        round(box["lo0"], 3), round(box["la0"], 3),
        round(box["lo1"], 3), round(box["la1"], 3), layer,
    )
    cached = _BASEMAP_CACHE.get(key)
    if cached is not None:
        return cached

    size = _BASEMAP_SAMPLES
    heights = []
    for y in range(size):
        lat = box["la1"] - (y / (size - 1)) * (box["la1"] - box["la0"])
        row = []
        for x in range(size):
            lon = box["lo0"] + (x / (size - 1)) * (box["lo1"] - box["lo0"])
            row.append(_smooth_elevation(lon, lat))
        heights.append(row)

    lo = min(min(row) for row in heights)
    hi = max(max(row) for row in heights)
    span = (hi - lo) or 1.0
    palette = _palette_for(layer)
    craters = _craters()

    # Build a fractal detail layer so the basemap reads as terrain rather than
    # analytic banding from the DEM function.
    detail = []
    for y in range(size):
        v = y / (size - 1)
        row = []
        for x in range(size):
            u = x / (size - 1)
            grain = _fbm(u, v)
            for cx, cy, radius in craters:
                dist = math.hypot(u - cx, v - cy) / radius
                if dist < 1.0:
                    grain += (0.55 if dist > 0.82 else -0.25) * (1.0 - dist)
            row.append(grain)
        detail.append(row)

    pixels = bytearray()
    for y in range(size):
        for x in range(size):
            height = heights[y][x]
            hx = heights[y][min(x + 1, size - 1)] - heights[y][max(x - 1, 0)]
            hy = heights[min(y + 1, size - 1)][x] - heights[max(y - 1, 0)][x]
            grain = detail[y][x]
            gx = detail[y][min(x + 1, size - 1)] - detail[y][max(x - 1, 0)]
            gy = detail[min(y + 1, size - 1)][x] - detail[max(y - 1, 0)][x]
            # Light from the north-west; mix broad relief with fractal texture.
            shade = max(-0.5, min(0.5, (hx * 0.35 - hy * 0.35) / span + gx * 4.0 - gy * 4.0))
            t = min(max((height - lo) / span * 0.45 + grain * 0.65 - 0.05, 0.0), 1.0)
            r, g, b = _lerp_palette(palette, t)
            factor = 1.0 + shade
            pixels.extend((
                max(0, min(255, int(r * factor))),
                max(0, min(255, int(g * factor))),
                max(0, min(255, int(b * factor))),
            ))

    image = Image.frombytes("RGB", (size, size), bytes(pixels))
    image = image.resize((_BASEMAP_SIZE, _BASEMAP_SIZE), Image.BICUBIC)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    payload = buffer.getvalue()
    _BASEMAP_CACHE[key] = payload
    return payload


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

@app.get("/api/status")
def status():
    return {"key": "custom" if os.environ.get("CAIRN_NASA_KEY") else "DEMO_KEY", "data_status": planning.DATA_STATUS}


@app.get("/api/layers")
def layers():
    names = [
        "Mars_Viking_MDIM21_ClrMosaic_global_925m",
        "Mars_CTX_Mosaic",
        "Mars_THEMIS_Day_IR",
    ]
    return {"layers": names, "auto": names[0]}


@app.get("/api/params")
def get_params():
    return load_params()


@app.put("/api/params")
def put_params(payload: dict):
    params = planning.default_params()
    for key, entry in payload.items():
        if isinstance(entry, dict) and "value" in entry:
            params[key] = {
                "value": entry["value"],
                "unit": entry.get("unit", ""),
                "label": entry.get("label", key),
            }
    if "reserve_minimums" in payload:
        entry = payload["reserve_minimums"]
        value = entry.get("value") if isinstance(entry, dict) else None
        if isinstance(value, dict):
            params["reserve_minimums"] = {
                "value": {
                    "oxygen": float(value.get("oxygen", 30)),
                    "power": float(value.get("power", 20)),
                },
                "unit": "%",
                "label": entry.get("label", "Return reserve minimums"),
            }
    save_params(params)
    return params


@app.get("/api/footprints")
def footprints(
    lo0: float = planning.AREA["lo0"],
    la0: float = planning.AREA["la0"],
    lo1: float = planning.AREA["lo1"],
    la1: float = planning.AREA["la1"],
):
    fps = []
    for product in planning.PRODUCTS:
        fps.append({
            "id": product["id"],
            "inst": product["inst"],
            "res": product["res"],
            "poly": product["poly"],
            "src": product["src"],
            "value_type": product["value_type"],
            "data_status": planning.DATA_STATUS,
        })
    return {"fps": fps, "live": False, "data_status": planning.DATA_STATUS}


@app.get("/api/dem")
def dem(
    lo0: float = planning.AREA["lo0"],
    la0: float = planning.AREA["la0"],
    lo1: float = planning.AREA["lo1"],
    la1: float = planning.AREA["la1"],
):
    if lo1 <= lo0 or la1 <= la0:
        raise HTTPException(status_code=400, detail="Invalid bounding box.")
    return planning.build_dem({"lo0": lo0, "la0": la0, "lo1": lo1, "la1": la1})


@app.post("/api/route")
def create_route(payload: dict):
    try:
        route = planning.plan_route(payload, load_params())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    response = {key: value for key, value in route.items() if key not in ("stress_results", "stress_flags", "waypoints", "created_seq")}
    response["segments"] = [
        {key: value for key, value in segment.items() if key not in ("highres_coverage_fraction", "needed")}
        for segment in route["segments"]
    ]
    return response


@app.get("/api/resources")
def resources(route_id: str = Query(...)):
    try:
        route = planning.get_route(route_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown route_id.")
    return planning.compute_resources(route, load_params())


@app.get("/api/mission")
def mission(route_id: str = Query(...)):
    try:
        route = planning.get_route(route_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown route_id.")
    result = planning.compute_mission(route, load_params())
    result.pop("resources", None)
    return result


def latest_route_with_segment(segment_id):
    candidates = [
        route for route in planning.ROUTES.values()
        if any(segment["id"] == segment_id for segment in route["segments"])
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda route: route.get("created_seq", 0))


@app.get("/api/segment/{segment_id}/dossier")
def dossier(segment_id: str, route_id: str | None = None):
    try:
        route = planning.get_route(route_id) if route_id else latest_route_with_segment(segment_id)
        if route is None:
            raise KeyError(segment_id)
        return planning.build_dossier(route, segment_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown route or segment.")


@app.post("/api/stress")
def stress(payload: dict):
    route_id = payload.get("route_id")
    segment_id = payload.get("segment_id")
    scenario = payload.get("scenario")
    if not segment_id:
        raise HTTPException(status_code=400, detail="segment_id is required.")
    try:
        route = planning.get_route(route_id) if route_id else latest_route_with_segment(segment_id)
        if route is None:
            raise KeyError(segment_id)
        result = planning.run_stress(route, segment_id, scenario, load_params())
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown route or segment.")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    mission_result = planning.compute_mission(route, load_params())
    mission_result.pop("resources", None)
    return {"result": result, "dossier": planning.build_dossier(route, segment_id), "mission": mission_result}


@app.get("/api/brief")
def brief(route_id: str = Query(...)):
    try:
        route = planning.get_route(route_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown route_id.")
    return planning.build_brief(route, load_params())


@app.get("/api/registry")
def registry(
    lo0: float = planning.AREA["lo0"],
    la0: float = planning.AREA["la0"],
    lo1: float = planning.AREA["lo1"],
    la1: float = planning.AREA["la1"],
):
    return planning.registry({"lo0": lo0, "la0": la0, "lo1": lo1, "la1": la1})


@app.get("/api/rover-photos")
def rover_photos(rover: str = "perseverance", sol: int = 1):
    return planning.rover_photos(rover, sol)


@app.get("/api/basemap")
def basemap(
    lo0: float = planning.AREA["lo0"],
    la0: float = planning.AREA["la0"],
    lo1: float = planning.AREA["lo1"],
    la1: float = planning.AREA["la1"],
    layer: str = "",
):
    if lo1 <= lo0 or la1 <= la0:
        raise HTTPException(status_code=400, detail="Invalid bounding box.")
    png = render_basemap({"lo0": lo0, "la0": la0, "lo1": lo1, "la1": la1}, layer)
    return Response(
        content=png,
        media_type="image/png",
        headers={
            "X-Layer": layer or "Cairn synthetic basemap",
            "Cache-Control": "public, max-age=3600",
        },
    )


if DIST_DIR.exists():
    app.mount("/", StaticFiles(directory=str(DIST_DIR), html=True), name="ui")
else:
    @app.get("/")
    def root():
        return {
            "service": "Cairn Trail Mode API",
            "note": "Run `npm run build` to serve the built frontend from this server, or `npm run dev` for Vite.",
            "data_status": planning.DATA_STATUS,
        }
