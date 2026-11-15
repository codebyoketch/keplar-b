# Deployment preparation

Cairn is a public, no-login demo. Keep the frontend and API on the same origin so Vite's local proxy is not part of the production setup.

## Build and run

Install the Python dependencies and build the frontend, then run the FastAPI application as the single web service:

```sh
pip install -r requirements.txt
cd frontend && npm ci && npm run build
cd ..
uvicorn backend.app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
```

Set `PORT` to the port supplied by the hosting platform. The API serves `frontend/dist` when that directory exists. Run one Uvicorn worker and one app instance for this demo: route and stress-test results are kept in process memory. Multiple workers or instances can lose those results between requests.

## Railway

The repository's `railpack.json` configures a single Railway service. It installs Python 3.12 and Node 22, builds the frontend, starts Uvicorn on Railway's `$PORT`, and keeps shared assumption updates disabled. Connect the `deployment-prep` branch, leave the service root directory at the repository root, and generate a public domain. Keep the service to one replica.

`NASA_API_KEY` is not required for the map, DEM, route planner, or basic demo. Add a personal key only as a Railway service variable if NASA APOD or rover-photo requests are needed. Railway trial accounts with restricted network access may need GitHub verification before the service can reach upstream NASA/USGS sources.

## Environment

- Keep `CAIRN_ENABLE_PARAM_UPDATES=false` for the public demo. This is the default. It makes the assumptions read-only and prevents visitors from overwriting the shared `data/params.json`. Set it to `true` only for a trusted deployment where shared edits are intended.
- `NASA_API_KEY` is optional. If used, set it in the hosting platform's server-side secret settings. Do not place it in frontend code or commit it. The key is only needed for NASA APOD and rover-photo requests; the map and DEM sources do not use it.
- Use the platform's HTTPS endpoint.

## Request limits

The API applies per-client, in-process limits to basemap, DEM, imagery, route, and stress-test endpoints. These limits are a basic safeguard for a small single-instance demo. Configure matching or stricter rate limits at the hosting edge as well, especially if the platform runs multiple instances.

The app identifies clients using the ASGI connection address. If the platform puts a reverse proxy in front of Uvicorn, configure Uvicorn to trust forwarded client addresses only from the platform's documented proxy addresses. Do not trust arbitrary `X-Forwarded-For` values from public clients.

The planner is an advisory demo. Keep its source and placeholder-data labels visible in the submitted build.
