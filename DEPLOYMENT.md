# Deployment preparation

Cairn is a public, no-login demo. Keep the frontend and API on the same origin so Vite's local proxy is not part of the production setup.

## Build and run

Build the frontend, then run the FastAPI application as the single web service:

```sh
cd frontend && npm ci && npm run build
cd ..
uv run uvicorn backend.app.main:app --host 0.0.0.0 --port "$PORT"
```

Set `PORT` to the port supplied by the hosting platform. The API serves `frontend/dist` when that directory exists. Run one Uvicorn worker and one app instance for this demo: route and stress-test results are kept in process memory. Multiple workers or instances can lose those results between requests.

## Environment

- Keep `CAIRN_ENABLE_PARAM_UPDATES=false` for the public demo. This is the default. It makes the assumptions read-only and prevents visitors from overwriting the shared `data/params.json`. Set it to `true` only for a trusted deployment where shared edits are intended.
- `NASA_API_KEY` is optional. If used, set it in the hosting platform's server-side secret settings. Do not place it in frontend code or commit it. The key is only needed for NASA APOD and rover-photo requests; the map and DEM sources do not use it.
- Use the platform's HTTPS endpoint.

## Request limits

The API applies per-client, in-process limits to basemap, DEM, imagery, route, and stress-test endpoints. These limits are a basic safeguard for a small single-instance demo. Configure matching or stricter rate limits at the hosting edge as well, especially if the platform runs multiple instances.

The app identifies clients using the ASGI connection address. If the platform puts a reverse proxy in front of Uvicorn, configure Uvicorn to trust forwarded client addresses only from the platform's documented proxy addresses. Do not trust arbitrary `X-Forwarded-For` values from public clients.

The planner is an advisory demo. Keep its source and placeholder-data labels visible in the submitted build.
