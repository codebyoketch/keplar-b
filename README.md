# Cairn: Trail Mode

Cairn is an advisory Marswalk planner for a small Jezero Crater area. It audits orbital evidence along a crew-drawn route, stress-tests segments, projects resources and shows a turn-back clock. It is a hackathon planning aid, not flight-certified software; resource values are editable, unvalidated assumptions.

For an end-to-end product explanation and a timed tutorial-video walkthrough, see [Cairn project walkthrough and video guide](DEMO_SCRIPT.md).

For a short project presentation, see the [seven-slide deck](presentation/Cairn_Project_Introduction.pptx) and its [speaker notes](presentation/SPEAKER_NOTES.md).

## First-time setup

Use Python 3.11+, [uv](https://docs.astral.sh/uv/) and [pnpm](https://pnpm.io/). Install the backend dependencies and build the frontend:

```sh
uv sync --group dev
cp .env.example .env
uv run python backend/prep_cache.py
cd frontend && pnpm install && pnpm build && cd ..
```

`NASA_API_KEY` is optional. If omitted, Cairn uses NASA's `DEMO_KEY`, which has a lower request limit. A personal key only enables NASA APOD and rover-photo requests; the map, DEM, and route workflow do not need it. The key is read only by the backend and sent only to NASA APIs.

## Run

```sh
uv run uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000>. The local Python server serves the production files from `frontend/dist`; it requires the one-time frontend build above. To develop the UI with Vite, run `pnpm dev` in `frontend` while the backend is running. The Vite development server proxies API calls to port 8000.

The demo cache makes the selected Jezero area available without a live source connection after a successful prep run. Unavailable live and cached data is labeled as placeholder data in the app.

## Planner controls

The top navigation stays available across **Plan**, **Field visor**, and **Mission brief**. On Plan, the start guide explains the route workflow; **Tools** contains landing region and target selection, claim results, planned stops, assumptions, advanced layers, sensor modes, registry/context tools, rover-image lookup, and project save/load. Click at least two points on the map, then choose **Calculate route + all 3 claims** in Tools. Cairn calculates Terrain, Current conditions, and Thermal together; select a claim card to inspect its result. Click a segment or stop to open its dossier. **Guide** opens the built-in walkthrough, and **Clean** hides map-console effects. The **Run stress test** button appears once a route exists.

The 2D basemap reloads for the visible map extent after panning or zooming, allowing exploration beyond the original Jezero square where the selected WMS layer has coverage. **Recenter** returns to the original Jezero extent. Route, footprint, and DEM overlays remain tied to their loaded data extent.

Choose **Jezero Crater** or **Gale Crater** under Tools → Target and route. Switching sites clears the previous route and waypoints, recenters the map, and requests that site's footprints and DEM. DEM availability depends on the live USGS service; 3D remains disabled until a DEM loads.

Footprints use separate colors for CTX (orange), HiRISE (blue), CRISM (purple), and THEMIS (green), in both map views. Selecting a claim card switches to that claim's already-calculated route and verdict. The selected segment has a plain-language summary with its verdict, distance, endpoints, and steepest mapped slope.

MEDA context is not connected in this build; Tools labels that gap. NASA rover context images are explicitly labeled as not being from the exact route location.

The map also offers a local **2D / 3D** switch when a DEM is loaded and WebGL is available. The 3D terrain uses kilometer-scale geometry, shaded relief derived from DEM elevations, directional lighting and shadows, and caps each terrain mesh at 256 × 256 vertices. Zooming out loads up to four times the selected region as surrounding terrain where the DEM source responds. Zooming into the Jezero stereo footprint requests the local [HiRISE DTM and matching orthoimage](https://hirise.lpl.arizona.edu/dtm/ESP_023524_1985) for a detailed terrain patch and texture; elsewhere the view falls back to MOLA and USGS imagery. Download the public DTM, matching orthoimage, and its map label to the Git-ignored local cache with `uv run python backend/download_hirise_jezero.py` (about 760 MB total). Pillow with JPEG 2000 support is required to decode the orthoimage. The view shares layer toggles, routes and stop selection with 2D. Its label explains that coarse MOLA terrain is a visual aid and is not used in the audit. Fine terrain appears only where the stereo product has coverage. Use `pnpm test:terrain` in `frontend` to check the DEM-to-mesh conversion.


## Integration branch: live-first API

This branch uses `backend.app.main:app` as the **single authoritative API**. The Vite development proxy forwards `/api` requests to `http://127.0.0.1:8000`. Run `uv run uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000` at the repository root and `pnpm dev` inside `frontend/` in a second terminal. The Python API serves the built `frontend/dist` when available.

Live NASA/USGS and PDS/ODE data are preferred. Existing backend cache handling may serve previously fetched data during upstream outages. Footprint records with `src: ILLUSTRATIVE` and responses with `live: false` are **synthetic fallback data**, not observations; never present them as verified measurements. If an uncached DEM or basemap cannot be retrieved, the API may return HTTP 502 instead of manufacturing terrain data. HiRISE high-resolution data requires a separately downloaded local dataset.

Run backend tests with `uv run pytest backend/tests -q` and frontend terrain tests with `cd frontend && pnpm test:terrain`. Both require execution in a checkout; this branch's GitHub-side edits alone do not prove the integration passes.
