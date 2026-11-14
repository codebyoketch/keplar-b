# Cairn: Trail Mode

Cairn is an advisory Marswalk planner for a small Jezero Crater area. It audits orbital evidence along a crew-drawn route, stress-tests segments, projects resources and shows a turn-back clock. It is a hackathon planning aid, not flight-certified software; resource values are editable, unvalidated assumptions.

## First-time setup

Use Python 3.11+ and npm. Install the Python packages from `requirements.txt`, then create the offline demo cache and the locally bundled frontend:

```sh
python -m pip install -r requirements.txt
cp .env.example .env
python backend/prep_cache.py
cd frontend && npm install && npm run build && cd ..
```

Set `NASA_API_KEY` in `.env` to a NASA key. If omitted, Cairn uses `DEMO_KEY` with its rate limit. The key is read only by the backend and sent only to NASA APIs.

## Run

```sh
python backend/run.py
```

Open <http://127.0.0.1:8000>. The local Python server serves the production files from `frontend/dist`; it requires the one-time frontend build above. To develop the UI with Vite, run `npm run dev` in `frontend` while the backend is running. The Vite development server proxies API calls to port 8000.

The demo cache makes the selected Jezero area available without a live source connection after a successful prep run. Unavailable live and cached data is labeled as placeholder data in the app.

## Planner controls

The planner opens with the verdict and turn-back clock, map, six layer toggles, evidence/resource strips, and the Run stress test, Visor mode, and Brief buttons. Target selection, waypoint editing, assumptions, individual instrument layers, sensor modes, registry and gaps/context tools, rover image lookup, project save/load, and the pytest command are in the closed-by-default **Tools** drawer (`T` also toggles it). After two map waypoints are placed, **Calculate mission route** appears directly below the map. Click a segment or stop to open its right-side dossier; only its first three flags appear until **Show all flags and sources** is expanded. **Demo** opens one guided step at a time. Press `Esc` to close Tools and the dossier; **Clean** removes the remaining map-console effects.

MEDA context is not connected in this build; Tools labels that gap. NASA rover context images are explicitly labeled as not being from the exact route location.

The map also offers a local **2D / 3D** switch when a DEM is loaded and WebGL is available. The 3D terrain uses the DEM elevation payload, caps the mesh at 256 × 256 vertices, and shares the layer toggles, routes and stop selection with 2D. Its label explains that coarse MOLA terrain is a visual aid and is not used in the audit. Use `npm run test:terrain` in `frontend` to check the DEM-to-mesh conversion.
