import React, { lazy, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import './styles.css';

const h = React.createElement;
const Map3DView = lazy(() => import('./Map3DView.js'));
const SITE_AREAS = {
  jezero: { label: 'Jezero Crater', lo0: 76.8, la0: 17.6, lo1: 78.4, la1: 19.2 },
  gale: { label: 'Gale Crater', lo0: 137.0, la0: -6.2, lo1: 138.6, la1: -4.6 },
};
const AREA = SITE_AREAS.jezero;
const MAP_SIZE = 800;
const PRODUCT_COLORS = { CTX: '#f5a623', HiRISE: '#45c5ff', CRISM: '#c084fc', THEMIS: '#51d88a' };
const VERDICT_COLORS = { Supported: '#4bdd9a', Check: '#f4bd4f', Fragile: '#ff5e64' };
const DEFAULT_LAYERS = {
  basemap: true, slope: false, footprints: true, CTX: true, HiRISE: true,
  CRISM: true, THEMIS: true, radiation: false, route: true, alternate: true,
  stops: true, comms: false,
};
const CLAIMS = [
  { value: 'terrain', label: 'Terrain / bedrock' },
  { value: 'current', label: 'Current surface conditions' },
  { value: 'thermal', label: 'Thermal context' },
];
const QUICK_BASEMAPS = [
  ['', 'Automatic'],
  ['MDIM21', 'Global imagery · MDIM21'],
  ['MDIM21_color', 'Color imagery · MDIM21'],
  ['THEMIS', 'THEMIS daytime'],
  ['THEMIS_controlled', 'THEMIS controlled'],
  ['THEMIS_night', 'THEMIS infrared night'],
  ['MOLA_color', 'COLOR RELIEF · MOLA elevation'],
  ['MOLA_bw', 'Grayscale elevation · MOLA'],
  ['MOLA_THEMIS_blend', 'Color terrain blend · MOLA + THEMIS'],
  ['HRSC_MOLA_Blend_Hillshade', 'HRSC + MOLA shaded relief'],
];

function api(path, options = {}) {
  return fetch(path, { headers: { 'Content-Type': 'application/json' }, ...options }).then(async (response) => {
    const body = response.headers.get('content-type')?.includes('application/json') ? await response.json() : await response.text();
    if (!response.ok) throw new Error(typeof body === 'string' ? body : body.detail || body.error || `HTTP ${response.status}`);
    return body;
  });
}

function boxQuery(box) {
  return new URLSearchParams({ lo0: box.lo0, la0: box.la0, lo1: box.lo1, la1: box.la1 }).toString();
}

function geoToMap([lon, lat], area = AREA) {
  const x = (lon - area.lo0) / (area.lo1 - area.lo0) * MAP_SIZE;
  const y = (lat - area.la0) / (area.la1 - area.la0) * MAP_SIZE;
  return [y, x];
}

function mapToGeo({ lat, lng }, area = AREA) {
  return [area.lo0 + lng / MAP_SIZE * (area.lo1 - area.lo0), area.la0 + lat / MAP_SIZE * (area.la1 - area.la0)];
}

function insidePolygon(point, polygon = []) {
  let hit = false;
  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
    const [xi, yi] = polygon[i] || [];
    const [xj, yj] = polygon[j] || [];
    if ((yi > point[1]) !== (yj > point[1]) && point[0] < ((xj - xi) * (point[1] - yi)) / (yj - yi) + xi) hit = !hit;
  }
  return hit;
}

function polygonProductsAt(point, products) {
  return products.filter((product) => insidePolygon(point, product.poly || []));
}

function segmentSummary(segment) {
  if (!segment) return '';
  const coordinates = segment.coordinates || [];
  const from = coordinates[0]; const to = coordinates.at(-1);
  const endpoint = (point) => point ? `lat ${point[1].toFixed(3)}°, lon ${point[0].toFixed(3)}°` : 'unknown location';
  const distance = Number(segment.distance_km); const slope = Number(segment.max_slope_deg);
  return `${segment.verdict || 'Unassessed'}: travel ${Number.isFinite(distance) ? distance.toFixed(2) : '—'} km from ${endpoint(from)} to ${endpoint(to)}${Number.isFinite(slope) ? `; steepest mapped slope ${slope.toFixed(1)}°` : ''}.`;
}

function claimVerdict(route) {
  const verdicts = (route?.segments || []).map((segment) => segment.verdict);
  return verdicts.includes('Fragile') ? 'Fragile' : verdicts.includes('Check') ? 'Check' : verdicts.length ? 'Supported' : '—';
}

function makeHatchImage(products, area = AREA) {
  const size = 180;
  const canvas = document.createElement('canvas');
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext('2d');
  const tile = document.createElement('canvas');
  tile.width = tile.height = 10;
  const tileCtx = tile.getContext('2d');
  tileCtx.strokeStyle = 'rgba(136, 195, 182, .47)';
  tileCtx.lineWidth = 1;
  tileCtx.beginPath(); tileCtx.moveTo(-2, 8); tileCtx.lineTo(8, -2); tileCtx.stroke();
  tileCtx.beginPath(); tileCtx.moveTo(2, 12); tileCtx.lineTo(12, 2); tileCtx.stroke();
  const pattern = ctx.createPattern(tile, 'repeat');
  for (let y = 0; y < size; y += 2) {
    for (let x = 0; x < size; x += 2) {
      const lon = area.lo0 + (x / size) * (area.lo1 - area.lo0);
      const lat = area.la0 + ((size - y) / size) * (area.la1 - area.la0);
      if (!products.some((product) => insidePolygon([lon, lat], product.poly || []))) {
        ctx.fillStyle = 'rgba(4, 15, 15, .76)';
        ctx.fillRect(x, y, 2, 2);
        ctx.fillStyle = pattern;
        ctx.fillRect(x, y, 2, 2);
      }
    }
  }
  return canvas.toDataURL('image/png');
}

function slopeImage(dem) {
  if (!dem?.z || !dem.w || !dem.h) return null;
  const binary = atob(dem.z);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
  const values = new DataView(bytes.buffer);
  const w = dem.w; const ht = dem.h; const b = dem.b;
  const canvas = document.createElement('canvas');
  canvas.width = w; canvas.height = ht;
  const ctx = canvas.getContext('2d');
  const image = ctx.createImageData(w, ht);
  const metersPerLonDeg = 59150;
  const metersPerLatDeg = 59150;
  const dlon = (b.lo1 - b.lo0) / Math.max(w - 1, 1);
  const dlat = (b.la1 - b.la0) / Math.max(ht - 1, 1);
  const elev = (x, y) => values.getFloat32((y * w + x) * 4, true);
  for (let y = 0; y < ht; y += 1) {
    for (let x = 0; x < w; x += 1) {
      const lx = Math.max(0, x - 1); const rx = Math.min(w - 1, x + 1);
      const ty = Math.max(0, y - 1); const by = Math.min(ht - 1, y + 1);
      const lat = b.la1 - (y / Math.max(ht - 1, 1)) * (b.la1 - b.la0);
      const dx = Math.max((rx - lx) * dlon * metersPerLonDeg * Math.cos(lat * Math.PI / 180), 1e-6);
      const dy = Math.max((by - ty) * dlat * metersPerLatDeg, 1e-6);
      const gx = (elev(rx, y) - elev(lx, y)) / dx;
      const gy = (elev(x, by) - elev(x, ty)) / dy;
      const deg = Math.atan(Math.hypot(gx, gy)) * 180 / Math.PI;
      const t = Math.max(0, Math.min(1, deg / 35));
      const stops = [[13, 99, 145], [17, 199, 157], [241, 188, 67], [245, 88, 49], [234, 39, 75]];
      const scaled = t * (stops.length - 1); const index = Math.min(stops.length - 2, Math.floor(scaled));
      const mix = scaled - index; const offset = (y * w + x) * 4;
      image.data[offset] = stops[index][0] * (1 - mix) + stops[index + 1][0] * mix;
      image.data[offset + 1] = stops[index][1] * (1 - mix) + stops[index + 1][1] * mix;
      image.data[offset + 2] = stops[index][2] * (1 - mix) + stops[index + 1][2] * mix;
      image.data[offset + 3] = 184;
    }
  }
  ctx.putImageData(image, 0, 0);
  return canvas.toDataURL('image/png');
}

function MapView(props) {
  const host = useRef(null);
  const mapRef = useRef(null);
  const overlayRef = useRef(null);
  const baseRef = useRef(null);
  const baseUrlRef = useRef(null);
  const propsRef = useRef(props);
  propsRef.current = props;

  useEffect(() => {
    const map = L.map(host.current, {
      crs: L.CRS.Simple, minZoom: -1.5, maxZoom: 3, zoomControl: false,
      attributionControl: false, zoomSnap: 0.25, wheelPxPerZoomLevel: 120,
    });
    mapRef.current = map;
    overlayRef.current = L.layerGroup().addTo(map);
    map.fitBounds([[0, 0], [MAP_SIZE, MAP_SIZE]], { animate: false });
    map.on('click', (event) => {
      const current = propsRef.current;
      if (!current.drawing) return;
      const point = mapToGeo(event.latlng, propsRef.current.area);
      current.onWaypointsChange((old) => [...old, point]);
      current.onRouteInvalidated();
    });
    map.on('mousemove', (event) => {
      const point = mapToGeo(event.latlng, propsRef.current.area);
      const products = polygonProductsAt(point, propsRef.current.products);
      propsRef.current.onCursor({ point, products });
    });
    map.on('mouseout', () => propsRef.current.onCursor(null));
    const resize = new ResizeObserver(() => map.invalidateSize());
    resize.observe(host.current);
    props.toolsRef.current.fit = () => map.fitBounds([[0, 0], [MAP_SIZE, MAP_SIZE]], { padding: [24, 24] });
    props.toolsRef.current.zoomIn = () => map.zoomIn();
    props.toolsRef.current.zoomOut = () => map.zoomOut();
    return () => {
      resize.disconnect();
      map.remove();
      mapRef.current = null;
      if (baseUrlRef.current) URL.revokeObjectURL(baseUrlRef.current);
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (map) map.fitBounds([[0, 0], [MAP_SIZE, MAP_SIZE]], { animate: false });
  }, [props.area]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return undefined;
    let active = true;
    let timer = null;
    let controller = null;
    if (!props.layers.basemap) {
      if (baseRef.current) { map.removeLayer(baseRef.current); baseRef.current = null; }
      if (baseUrlRef.current) { URL.revokeObjectURL(baseUrlRef.current); baseUrlRef.current = null; }
      return undefined;
    }
    const loadVisibleArea = () => {
      controller?.abort();
      controller = new AbortController();
      const bounds = map.getBounds();
      const southwest = mapToGeo(bounds.getSouthWest(), props.area);
      const northeast = mapToGeo(bounds.getNorthEast(), props.area);
      const visibleBox = { lo0: southwest[0], la0: southwest[1], lo1: northeast[0], la1: northeast[1] };
      const query = `${boxQuery(visibleBox)}&layer=${encodeURIComponent(props.mapLayer || '')}`;
      fetch(`/api/basemap?${query}`, { signal: controller.signal }).then(async (response) => {
        if (!response.ok) throw new Error('USGS imagery is unavailable for this area');
        const blob = await response.blob();
        if (!active) return;
        const url = URL.createObjectURL(blob);
        if (baseRef.current) map.removeLayer(baseRef.current);
        if (baseUrlRef.current) URL.revokeObjectURL(baseUrlRef.current);
        baseUrlRef.current = url;
        baseRef.current = L.imageOverlay(url, bounds, { opacity: 0.94, interactive: false }).addTo(map);
        propsRef.current.onMapStatus(`${response.headers.get('X-Layer') || 'USGS WMS'} · visible area`);
      }).catch((error) => {
        if (active && error.name !== 'AbortError') propsRef.current.onMapStatus(error.message);
      });
    };
    const scheduleLoad = () => {
      clearTimeout(timer);
      timer = setTimeout(loadVisibleArea, 240);
    };
    map.on('moveend zoomend', scheduleLoad);
    scheduleLoad();
    return () => {
      active = false;
      clearTimeout(timer);
      controller?.abort();
      map.off('moveend zoomend', scheduleLoad);
    };
  }, [props.layers.basemap, props.mapLayer, props.area]);

  useEffect(() => {
    const map = mapRef.current; const group = overlayRef.current;
    if (!map || !group) return;
    group.clearLayers();
    const active = props.layers;
    const products = props.products;
    if (active.slope && props.dem) {
      const image = slopeImage(props.dem);
      if (image) L.imageOverlay(image, [[0, 0], [MAP_SIZE, MAP_SIZE]], { opacity: 0.65, interactive: false }).addTo(group);
    }
    if (active.footprints) {
      const coverage = makeHatchImage(products, props.area);
      L.imageOverlay(coverage, [[0, 0], [MAP_SIZE, MAP_SIZE]], { opacity: 0.68, interactive: false }).addTo(group);
      products.filter((product) => active[product.inst]).forEach((product) => {
        const latlngs = (product.poly || []).map(([lon, lat]) => geoToMap([lon, lat], props.area));
        if (latlngs.length < 3) return;
        const color = PRODUCT_COLORS[product.inst] || '#a8c2bc';
        L.polygon(latlngs, { color, weight: 1.7, opacity: 0.95, fillColor: color, fillOpacity: 0.08, dashArray: product.src === 'ILLUSTRATIVE' ? '5 5' : null }).addTo(group);
      });
    }
    if (active.route && props.route?.segments?.length) {
      props.route.segments.forEach((segment) => {
        const color = props.showVerdictColors ? (VERDICT_COLORS[segment.verdict] || '#55e0c0') : '#64dfd1';
        const points = (segment.coordinates || []).map((point) => geoToMap(point, props.area));
        if (points.length > 1) L.polyline(points, { color, weight: 4.4, opacity: 0.96, lineCap: 'round' })
          .on('click', () => props.onSegmentSelect?.(props.route.segments.indexOf(segment))).addTo(group);
      });
    } else if (active.route && props.waypoints.length > 1) {
      L.polyline(props.waypoints.map((point) => geoToMap(point, props.area)), { color: '#60d9c1', weight: 3, dashArray: '7 6' }).addTo(group);
    }
    if (active.alternate && props.route?.alternate?.coordinates?.length) {
      L.polyline(props.route.alternate.coordinates.map((point) => geoToMap(point, props.area)), { color: '#b6c3c2', weight: 2.6, dashArray: '7 8', opacity: 0.85 }).addTo(group);
    }
    if (active.stops && props.waypoints.length) {
      props.waypoints.forEach((point, index) => {
        const icon = L.divIcon({ className: 'mars-pin-wrap', html: `<span class="mars-pin">${index === props.waypoints.length - 1 ? 'T' : index + 1}</span>`, iconSize: [26, 26], iconAnchor: [13, 13] });
        L.marker(geoToMap(point, props.area), { icon, keyboard: false }).on('click', () => props.onSegmentSelect?.(Math.min(index, (props.route?.segments?.length || 1) - 1))).addTo(group);
      });
    }
    if (active.comms && props.waypoints.length > 1) {
      L.polyline([geoToMap(props.waypoints[0], props.area), geoToMap(props.waypoints[props.waypoints.length - 1], props.area)],
        { color: '#64dfff', weight: 1.6, dashArray: '2 7', opacity: 0.9 }).addTo(group);
    }
  }, [props.layers, props.products, props.dem, props.route, props.waypoints, props.showVerdictColors, props.area]);

  return h('div', { className: `map-shell sensor-${props.sensor} ${props.scanning ? 'scan-active' : ''}` },
    h('div', { ref: host, className: 'leaflet-map', role: 'application', 'aria-label': 'Mars planning map. Click to add waypoints.' }),
    h('button', { className: 'map-recenter-button', onClick: () => props.toolsRef.current.fit?.(), title: 'Return to the original Jezero map extent' }, 'Recenter'),
    h('div', { className: 'map-reticle', 'aria-hidden': true }, h('i'), h('b'), h('span')),
    h('div', { className: 'corner corner-tl' }), h('div', { className: 'corner corner-tr' }),
    h('div', { className: 'corner corner-bl' }), h('div', { className: 'corner corner-br' }),
    props.layers.radiation && h('div', { className: 'map-context-flag' }, 'RADIATION CONTEXT · OTHER SITE · NO LOCAL GRID'),
    props.layers.slope && h('div', { className: 'slope-legend' }, h('span', null, 'SLOPE · DERIVED'),
      h('i', null), h('small', null, '0°'), h('small', null, '35°+')),
    h('div', { className: 'map-scale-tag' }, `L.CRS.SIMPLE  /  ${MAP_SIZE} × ${MAP_SIZE} px`));
}

function LayerSwitch({ label, checked, onChange, note, disabled = false }) {
  return h('label', { className: `layer-switch ${disabled ? 'is-disabled' : ''}` },
    h('input', { type: 'checkbox', checked, disabled, onChange: (event) => onChange(event.target.checked) }),
    h('span', { className: 'switch-track' }),
    h('span', { className: 'layer-switch-copy' }, h('b', null, label), note && h('small', null, note)));
}

function AssumptionsDrawer({ params, onParamsChange, onSave, saving, canEdit }) {
  const entries = Object.entries(params || {});
  const scalar = entries.filter(([, entry]) => !entry?.value || typeof entry.value !== 'object');
  const reserve = params?.reserve_minimums?.value || { oxygen: 30, power: 20 };
  return h('section', { className: 'assumption-fields' },
      h('p', { className: 'assumption-warning' }, 'Crew-set values · unvalidated assumptions'),
      scalar.map(([key, entry]) => h('label', { className: 'assumption-field', key },
        h('span', null, h('b', null, key.replaceAll('_', ' ')), h('small', null, `${entry.unit} · ${entry.label}`)),
        h('input', { type: 'number', min: 0, step: 'any', value: entry.value, disabled: !canEdit, onChange: (event) => onParamsChange(key, Number(event.target.value)) }))),
      h('div', { className: 'reserve-fields' }, h('span', null, h('b', null, 'reserve minimums'), h('small', null, '% · unvalidated assumption')),
        ['oxygen', 'power'].map((key) => h('label', { key }, key, h('input', { type: 'number', min: 0, step: 1, value: reserve[key], disabled: !canEdit, onChange: (event) => onParamsChange('reserve_minimums', { ...reserve, [key]: Number(event.target.value) }) })))),
      !canEdit && h('small', { className: 'read-only-note' }, 'Assumptions are read-only on this public demo.'),
      h('button', { className: 'action-button action-button-full', onClick: onSave, disabled: saving || !canEdit }, saving ? 'SAVING…' : canEdit ? 'Save assumptions' : 'Read-only deployment'));
}

function ProductDossier({ dossier, segment, stressBusy, onStress, onClose }) {
  const checks = dossier?.checks || segment?.checks || {};
  const products = dossier?.products || [];
  const flags = dossier?.flags || segment?.flags || [];
  if (!segment) return null;
  const verdict = dossier?.verdict || segment.verdict || 'Check';
  const topFlags = flags.slice(0, 3);
  return h('aside', { className: 'dossier-panel side-panel', 'aria-label': 'Segment dossier' },
    h('div', { className: 'side-panel-head' }, h('div', null, h('span', { className: 'eyebrow' }, 'SEGMENT DOSSIER'),
      h('h2', null, `${segment.id} · ${Number(segment.distance_km).toFixed(2)} km`)),
      h('button', { className: 'icon-button', onClick: onClose, 'aria-label': 'Close dossier' }, '×')),
    h('div', { className: `dossier-verdict verdict-${verdict.toLowerCase()}` }, `${verdict} · ${flags.length} flag${flags.length === 1 ? '' : 's'}`),
    topFlags.length ? topFlags.map((flag, index) => h('div', { className: `flag-row flag-${flag.severity || 'warn'}`, key: `${flag.code}-${index}` },
      h('b', null, flag.code), h('span', null, flag.reason))) : h('p', { className: 'dossier-clear' }, 'No flags on this segment.'),
    h('div', { className: 'needed-line' }, h('b', null, 'NEEDED /'), ' ', dossier?.needed || 'No additional observation identified.'),
    h('div', { className: 'stress-actions' },
      h('button', { className: 'action-button', disabled: stressBusy, onClick: () => onStress('unseen_obstacle') }, stressBusy ? 'RUNNING…' : 'RUN STRESS TEST'),
      h('button', { className: 'quiet-button', disabled: stressBusy, onClick: () => onStress('slope_error') }, 'SLOPE ERROR')),
    (dossier?.stress_tests || []).map((result, index) => h('div', { className: 'stress-result', key: `stress-${index}` },
      h('b', null, result.scenario.replaceAll('_', ' ').toUpperCase()), h('span', null, result.reason))),
    h('details', { className: 'dossier-details' }, h('summary', null, 'Show all flags and sources'),
      flags.slice(3).map((flag, index) => h('div', { className: `flag-row flag-${flag.severity || 'warn'}`, key: `${flag.code}-all-${index}` }, h('b', null, flag.code), h('span', null, flag.reason))),
      h('h3', null, `Checks / ${Object.keys(checks).length}`),
      Object.entries(checks).map(([name, check]) => h('p', { key: name }, `${name}: ${check.status} · ${check.reason}`)),
      h('h3', null, `Sources / ${products.length}`),
      products.map((product) => h('p', { key: product.id }, `${product.id} · ${product.inst} · ${product.res} m/px · ${product.value_type || 'unknown'}`))));
}

function MissionStrips({ route, resources, selectedSegment, onSelectSegment }) {
  const segments = route?.segments || [];
  if (!segments.length) return h('div', { className: 'strips-empty' }, 'SEGMENT EVIDENCE / RESOURCE PROJECTIONS APPEAR HERE AFTER ROUTE PLANNING');
  const resourceSegments = resources?.segments || [];
  return h('div', { className: 'strip-board' },
    h('div', { className: 'strip-row evidence-strip' }, h('div', { className: 'strip-label' }, 'EVIDENCE / VALUE TYPE'),
      h('div', { className: 'strip-columns', style: { gridTemplateColumns: `repeat(${segments.length}, minmax(130px, 1fr))` } }, segments.map((segment, index) => h('button', {
        className: `strip-cell ${selectedSegment === index ? 'strip-selected' : ''}`, key: segment.id, onClick: () => onSelectSegment(index),
        style: { '--segment-color': VERDICT_COLORS[segment.verdict] || '#789' },
      }, h('span', null, segment.id), h('b', null, segment.verdict), h('small', null, `${segment.checks?.coverage?.status || 'unknown'} coverage · ${segment.checks?.scale?.value_type || 'unknown'}`))))),
    h('div', { className: 'strip-row resource-strip' }, h('div', { className: 'strip-label' }, 'RESOURCE / DERIVED RANGE'),
      h('div', { className: 'strip-columns', style: { gridTemplateColumns: `repeat(${segments.length}, minmax(130px, 1fr))` } }, segments.map((segment, index) => {
        const estimate = resourceSegments[index];
        return h('div', { className: 'resource-cell', key: segment.id }, h('b', null, segment.id),
          h('span', null, `O₂ ${estimate?.oxygen_used_pct?.best ?? '—'}–${estimate?.oxygen_used_pct?.worst ?? '—'}%`),
          h('span', null, `PWR ${estimate?.power_used_pct?.best ?? '—'}–${estimate?.power_used_pct?.worst ?? '—'}%`),
          h('small', null, `time ${estimate?.time_minutes?.best ?? '—'}–${estimate?.time_minutes?.worst ?? '—'} min`));
      }))));
}

function visorDirection(segment, dossier) {
  if (!segment) return 'No route is loaded. Return to Planner, draw the route, and calculate the mission before receiving voice directions.';
  const warnings = [];
  if ((dossier?.highres_coverage_fraction ?? 0) < 1) warnings.push('no close-up imagery, boulders not visible. Proceed slowly.');
  if (dossier?.checks?.age?.status === 'fail') warnings.push('orbital observations cannot establish current local conditions.');
  if (dossier?.checks?.type?.status !== 'pass') warnings.push('some evidence is assumed or uncertain.');
  const path = segment.coordinates || [];
  const origin = path[0]; const destination = path[path.length - 1];
  const coords = origin && destination
    ? `From ${origin[1].toFixed(3)} north, ${origin[0].toFixed(3)} east to ${destination[1].toFixed(3)} north, ${destination[0].toFixed(3)} east.`
    : 'Follow the planned route to the next waypoint.';
  const warning = warnings.length ? ` Trust warning: ${warnings.join(' ')}` : ` Evidence status: ${dossier?.verdict || segment.verdict}.`;
  return `Next stretch, ${segment.id}. ${coords} Distance ${Number(segment.distance_km).toFixed(2)} kilometers, derived from the DEM. Maximum slope ${segment.max_slope_deg} degrees, DEM-derived.${warning}`;
}

function VisorPage({ route, segmentIndex, setSegmentIndex, dossier, onSpeak, voiceAvailable, onPlanner }) {
  const segment = route?.segments?.[segmentIndex];
  const direction = visorDirection(segment, dossier);
  return h('main', { className: 'visor-screen' },
    h('div', { className: 'visor-topline' }, h('span', null, 'CAIRN / FIELD VISOR'), h('span', null, route ? `${segmentIndex + 1} / ${route.segments.length} · ${route.target?.name || 'TARGET'}` : 'NO ROUTE LOADED'),
      h('button', { onClick: onPlanner }, '← PLANNER')),
    h('div', { className: 'visor-copy' },
      h('span', { className: 'eyebrow' }, 'VOICE ROUTE GUIDANCE · PLANNING-TIME ONLY'),
      h('div', { className: 'visor-segment' }, segment?.id || 'STANDBY'),
      h('p', { className: 'visor-direction', 'aria-live': 'polite' }, direction),
      h('div', { className: 'visor-fallback' }, h('b', null, voiceAvailable ? 'TEXT BACKUP READY' : 'VOICE UNAVAILABLE · TEXT DIRECTIONS SHOWN'),
        h('span', null, direction)),
      h('div', { className: 'visor-controls' },
        h('button', { onClick: () => setSegmentIndex((index) => Math.max(0, index - 1)), disabled: segmentIndex <= 0 }, '← PREVIOUS'),
        h('button', { className: 'action-button visor-speak', onClick: onSpeak, disabled: !voiceAvailable || !segment }, voiceAvailable ? '▶ SPEAK DIRECTIONS' : 'SPEECH NOT AVAILABLE'),
        h('button', { onClick: () => setSegmentIndex((index) => Math.min((route?.segments?.length || 1) - 1, index + 1)), disabled: !route || segmentIndex >= route.segments.length - 1 }, 'NEXT →')),
      h('small', { className: 'visor-advisory' }, 'Advisory only · no live telemetry · follow crew procedures')),
    h('div', { className: 'visor-reticle', 'aria-hidden': true }, h('i'), h('b'), h('span')));
}

function BriefPage({ data, error, loading, onPrint, onPlanner }) {
  if (loading) return h('main', { className: 'brief-shell' }, h('div', { className: 'brief-tools' }, h('button', { onClick: onPlanner }, '← PLANNER')),
    h('article', { className: 'brief-paper' }, h('p', null, 'LOADING ROUTE BRIEF…')));
  if (!data) return h('main', { className: 'brief-shell' }, h('div', { className: 'brief-tools' }, h('button', { onClick: onPlanner }, '← PLANNER')),
    h('article', { className: 'brief-paper brief-empty' }, h('span', { className: 'eyebrow' }, 'MISSION BRIEF'), h('h1', null, 'No route brief yet'),
      h('p', null, error || 'Plan a route first. The brief is generated from the selected route and its current stress tests.'),
      h('button', { className: 'action-button', onClick: onPlanner }, 'OPEN PLANNER')));
  const stressResults = data.stress_test_results || [];
  return h('main', { className: 'brief-shell' },
    h('div', { className: 'brief-tools' }, h('span', null, 'PRINT-READY · SINGLE MISSION PAGE'),
      h('div', null, h('button', { onClick: onPlanner }, '← PLANNER'), h('button', { className: 'action-button', onClick: onPrint }, 'PRINT / SAVE PDF'))),
    h('article', { className: 'brief-paper' },
      h('header', { className: 'brief-header' }, h('div', null, h('span', null, 'CAIRN / TRAIL MODE'), h('h1', null, 'MISSION EVIDENCE BRIEF'),
        h('p', null, `${data.target?.name || 'Crew selected target'} · ${data.target?.claim || 'terrain'} claim · planning-time projection`)),
        h('div', { className: `brief-verdict verdict-${(data.mission_verdict || '').toLowerCase().replaceAll(' ', '-')}` }, data.mission_verdict)),
      h('div', { className: 'brief-clock-row' },
        h('div', null, h('span', null, 'TURN-BACK POINT · DERIVED'), h('b', null, data.turn_back_clock?.point || '—')),
        h('div', null, h('span', null, 'OUTBOUND ELAPSED · DERIVED'), h('b', null, `${data.turn_back_clock?.elapsed_outbound_minutes ?? '—'} min`)),
        h('div', null, h('span', null, 'RETURN TIME · DERIVED'), h('b', null, `${data.turn_back_clock?.return_time_minutes ?? '—'} min`))),
      h('section', { className: 'brief-section' }, h('h2', null, 'RESOURCE MARGINS · WORST CASE'),
        h('div', { className: 'brief-margin-grid' },
          ['oxygen_pct', 'power_pct', 'daylight_minutes'].map((key) => h('div', { key }, h('span', null, key.replaceAll('_', ' ').toUpperCase()),
            h('b', null, `${data.resource_margins?.[key] ?? '—'}${key === 'daylight_minutes' ? ' min' : '%'}`), h('small', null, 'derived'))))),
      h('section', { className: 'brief-section' }, h('h2', null, 'WELL SUPPORTED SEGMENTS'),
        data.well_supported?.length ? data.well_supported.map((item) => h('div', { className: 'brief-supported-row', key: item.id },
          h('b', null, item.id), h('span', null, 'Supported'), h('small', null, 'coverage and scale checks passed · evidence types shown in planner')))
          : h('p', { className: 'brief-muted' }, 'No segment meets the Supported criteria in the current plan.')),
      h('section', { className: 'brief-section' }, h('h2', null, 'CAVEATS / FLAGS'),
        data.caveats?.length ? data.caveats.map((item) => h('div', { className: 'brief-caveat', key: item.segment_id }, h('b', null, item.segment_id),
          h('ul', null, item.flags.map((flag, index) => h('li', { key: `${flag.code}-${index}` }, h('strong', null, `${flag.code} · ${flag.severity}`), ` — ${flag.reason}`)))))
          : h('p', { className: 'brief-muted' }, 'No evidence flags were recorded.')),
      h('section', { className: 'brief-section' }, h('h2', null, 'STRESS TEST'),
        stressResults.length ? stressResults.map((result, index) => h('div', { className: 'brief-stress', key: `${result.scenario}-${index}` },
          h('b', null, result.scenario.replaceAll('_', ' ').toUpperCase()), h('span', null, result.reason),
          result.extra_distance_km != null && h('small', null, `Distance change ${result.extra_distance_km} km · derived`)))
          : h('p', { className: 'brief-muted' }, 'No stress test has been run for this route.')),
      h('section', { className: 'brief-next-observation' }, h('span', null, 'SINGLE NEXT OBSERVATION TO REDUCE RISK'), h('p', null, data.next_observation)),
      h('section', { className: 'brief-sources' }, h('h2', null, `SOURCES · ${data.data_status === 'PLACEHOLDER DATA' ? 'PLACEHOLDER DATA' : 'PDS / USGS'}`),
        (data.sources || []).slice(0, 12).map((source, index) => h('span', { key: `${source.id}-${index}` }, `${source.id} · ${source.inst} · ${source.res ?? 'unknown'} m/px · ${source.src}`)),
        h('small', null, 'Orbital products describe their acquisition footprint; rover context images are not exact-location evidence.')),
      h('footer', { className: 'brief-footer' }, 'Advisory only · not flight certified · no live telemetry · assumptions remain unvalidated')));
}

function MainApp() {
  const [site, setSite] = useState('jezero');
  const area = SITE_AREAS[site] || SITE_AREAS.jezero;
  const [status, setStatus] = useState(null);
  const [mapLayers, setMapLayers] = useState({ layers: [], auto: '' });
  const [mapLayer, setMapLayer] = useState('');
  const [products, setProducts] = useState([]);
  const [footprintsLive, setFootprintsLive] = useState(null);
  const [dem, setDem] = useState(null);
  const [params, setParams] = useState({});
  const [route, setRoute] = useState(null);
  const [claimRuns, setClaimRuns] = useState(null);
  const [resources, setResources] = useState(null);
  const [mission, setMission] = useState(null);
  const [dossier, setDossier] = useState(null);
  const [waypoints, setWaypoints] = useState([]);
  const [selectedSegment, setSelectedSegment] = useState(0);
  const [targetName, setTargetName] = useState('Jezero field target');
  const [claim, setClaim] = useState('terrain');
  const [stopCount, setStopCount] = useState(1);
  const [layers, setLayers] = useState(DEFAULT_LAYERS);
  const [sensor, setSensor] = useState('plain');
  const [drawing, setDrawing] = useState(true);
  const [cursor, setCursor] = useState(null);
  const [mapStatus, setMapStatus] = useState('CONNECTING TO LOCAL DATA GATEWAY');
  const [photo, setPhoto] = useState(null);
  const [busy, setBusy] = useState(false);
  const [stressBusy, setStressBusy] = useState(false);
  const [savingParams, setSavingParams] = useState(false);
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  const [activeView, setActiveView] = useState(() => window.location.hash.slice(1) || 'planner');
  const [briefData, setBriefData] = useState(null);
  const [briefError, setBriefError] = useState('');
  const [briefLoading, setBriefLoading] = useState(false);
  const [visorIndex, setVisorIndex] = useState(0);
  const [visorDossier, setVisorDossier] = useState(null);
  const [voiceAvailable, setVoiceAvailable] = useState(false);
  const [openPanels, setOpenPanels] = useState([]);
  const [showVerdictColors, setShowVerdictColors] = useState(true);
  const [cleanMode, setCleanMode] = useState(false);
  const [demoStep, setDemoStep] = useState(0);
  const [registryRows, setRegistryRows] = useState(null);
  const [toolMessage, setToolMessage] = useState('');
  const [mapMode, setMapMode] = useState('2d');
  const [verticalExaggeration, setVerticalExaggeration] = useState(6);
  const [webglAvailable, setWebglAvailable] = useState(null);
  const [map3dMessage, setMap3dMessage] = useState('');
  const toolsRef = useRef({});

  const hasPanel = (name) => openPanels.includes(name);
  const openPanel = (name) => setOpenPanels((old) => {
    const base = window.innerWidth < 780 && ['tools', 'dossier'].includes(name)
      ? old.filter((item) => item !== 'tools' && item !== 'dossier') : old;
    return [...base.filter((item) => item !== name), name].slice(-2);
  });
  const closePanel = (name) => setOpenPanels((old) => old.filter((item) => item !== name));

  useEffect(() => {
    const onKeyDown = (event) => {
      if (event.key === 'Escape') setOpenPanels((old) => old.filter((name) => name !== 'tools' && name !== 'dossier'));
      if (event.key.toLowerCase() === 't' && !['INPUT', 'SELECT', 'TEXTAREA'].includes(event.target?.tagName)) {
        setOpenPanels((old) => old.includes('tools') ? old.filter((name) => name !== 'tools') : [...old.filter((name) => name !== 'tools'), 'tools'].slice(-2));
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, []);

  useEffect(() => {
    let available = false;
    try {
      const canvas = document.createElement('canvas');
      available = Boolean(canvas.getContext('webgl2') || canvas.getContext('webgl'));
      const lose = canvas.getContext('webgl2')?.getExtension('WEBGL_lose_context') || canvas.getContext('webgl')?.getExtension('WEBGL_lose_context');
      lose?.loseContext();
    } catch { available = false; }
    setWebglAvailable(available);
    if (!available) setMap3dMessage('3D unavailable: WebGL is not supported here. Staying in 2D.');
  }, []);

  useEffect(() => {
    const syncHash = () => {
      const requested = window.location.hash.slice(1);
      if (['planner', 'visor', 'brief'].includes(requested)) setActiveView(requested);
      else { window.location.hash = '#planner'; setActiveView('planner'); }
    };
    window.addEventListener('hashchange', syncHash);
    syncHash();
    return () => window.removeEventListener('hashchange', syncHash);
  }, []);

  useEffect(() => {
    const supported = typeof window !== 'undefined' && 'speechSynthesis' in window && 'SpeechSynthesisUtterance' in window;
    setVoiceAvailable(supported);
    return () => { if ('speechSynthesis' in window) window.speechSynthesis.cancel(); };
  }, []);

  useEffect(() => {
    if (!window.location.hash) window.location.hash = '#planner';
    let active = true;
    Promise.allSettled([
      api('/api/status'), api('/api/layers'), api('/api/params'),
    ]).then((results) => {
      if (!active) return;
      const [stat, layerResult, paramResult] = results;
      if (stat.status === 'fulfilled') setStatus(stat.value);
      if (layerResult.status === 'fulfilled') setMapLayers(layerResult.value);
      if (paramResult.status === 'fulfilled') setParams(paramResult.value);
      const failed = results.filter((result) => result.status === 'rejected');
      if (failed.length) setNotice(`${failed.length} source request(s) unavailable; cached or placeholder status is shown per layer.`);
      setMapStatus(layerResult.status === 'fulfilled' ? 'USGS IMAGE OVERLAY · LOCAL MAP COORDINATES' : 'LOCAL API NOT REACHABLE');
    });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    let active = true;
    setProducts([]); setFootprintsLive(null); setDem(null);
    setMap3dMessage('');
    setMapStatus(`LOADING ${area.label.toUpperCase()} MAP DATA`);
    Promise.allSettled([
      api(`/api/footprints?site=${site}&${boxQuery(area)}`),
      api(`/api/dem?site=${site}&${boxQuery(area)}`),
    ]).then(([footprintResult, demResult]) => {
      if (!active) return;
      if (footprintResult.status === 'fulfilled') {
        setProducts(footprintResult.value.fps || []);
        setFootprintsLive(footprintResult.value.live);
      } else setToolMessage(`${area.label} footprints unavailable: ${footprintResult.reason?.message || 'source error'}`);
      if (demResult.status === 'fulfilled') setDem(demResult.value);
      else setMap3dMessage(`${area.label} DEM unavailable: ${demResult.reason?.message || 'source error'}`);
      setMapStatus(`${area.label.toUpperCase()} · ${footprintResult.status === 'fulfilled' ? 'FOOTPRINT DATA LOADED' : 'FOOTPRINTS UNAVAILABLE'}`);
    });
    return () => { active = false; };
  }, [site, area]);

  const selected = route?.segments?.[selectedSegment] || null;

  const refreshMission = useCallback(async (routeId) => {
    if (!routeId) return;
    const [resourceData, missionData] = await Promise.all([
      api(`/api/resources?route_id=${routeId}`), api(`/api/mission?route_id=${routeId}`),
    ]);
    setResources(resourceData);
    setMission(missionData);
    return { resources: resourceData, mission: missionData };
  }, []);

  const invalidateRoute = useCallback(() => {
    setRoute(null); setClaimRuns(null); setResources(null); setMission(null); setDossier(null); setPhoto(null);
    closePanel('dossier');
    setError('');
  }, []);

  const selectSegment = useCallback(async (index) => {
    setSelectedSegment(index);
    const segment = route?.segments?.[index];
    if (!segment) return;
    openPanel('dossier');
    try { setDossier(await api(`/api/segment/${segment.id}/dossier`)); }
    catch (requestError) { setError(requestError.message); }
  }, [route]);

  useEffect(() => {
    const segment = route?.segments?.[visorIndex];
    if (!segment || activeView !== 'visor') { setVisorDossier(null); return; }
    let active = true;
    api(`/api/segment/${segment.id}/dossier`).then((result) => { if (active) setVisorDossier(result); }).catch(() => { if (active) setVisorDossier(null); });
    return () => { active = false; };
  }, [activeView, route, visorIndex]);

  useEffect(() => {
    if (activeView !== 'brief') return;
    if (!route?.route_id) { setBriefData(null); setBriefError(''); return; }
    let active = true;
    setBriefLoading(true); setBriefError('');
    api(`/api/brief?route_id=${route.route_id}`).then((result) => { if (active) setBriefData(result); })
      .catch((requestError) => { if (active) { setBriefError(requestError.message); setBriefData(null); } })
      .finally(() => { if (active) setBriefLoading(false); });
    return () => { active = false; };
  }, [activeView, route]);

  const calculateRoute = async () => {
    if (waypoints.length < 2) { setError('Add at least two waypoints on the map.'); return; }
    setBusy(true); setError(''); setNotice('');
    try {
      const routeResults = await Promise.all(CLAIMS.map(async (item) => {
        const target = { name: targetName || 'Crew selected target', claim: item.value, coordinates: waypoints[waypoints.length - 1] };
        const result = await api('/api/route', { method: 'POST', body: JSON.stringify({ target, waypoints, stop_count: Number(stopCount) }) });
        return [item.value, result];
      }));
      const routes = Object.fromEntries(routeResults);
      const routeExtras = await Promise.all(CLAIMS.map(async (item) => {
        const result = routes[item.value];
        const [routeResources, routeMission] = await Promise.all([
          api(`/api/resources?route_id=${result.route_id}`), api(`/api/mission?route_id=${result.route_id}`),
        ]);
        return [item.value, { resources: routeResources, mission: routeMission }];
      }));
      const extras = Object.fromEntries(routeExtras);
      const runs = { routes, extras };
      setClaimRuns(runs);
      setRoute(routes[claim]); setResources(extras[claim].resources); setMission(extras[claim].mission);
      setSelectedSegment(0); setDossier(null); setPhoto(null);
      setNotice('Route calculated for Terrain, Current conditions, and Thermal claims. Select a claim to inspect its audit.');
      if (layers.stops) api('/api/rover-photos?rover=perseverance&sol=1').then((photoResult) => setPhoto(photoResult[0] || null)).catch(() => setPhoto(null));
    } catch (requestError) { setError(requestError.message); }
    finally { setBusy(false); }
  };

  const changeClaim = (value) => {
    if (value === claim) return;
    setClaim(value);
    const nextRoute = claimRuns?.routes?.[value];
    if (nextRoute) {
      setRoute(nextRoute); setResources(claimRuns.extras[value].resources); setMission(claimRuns.extras[value].mission);
      setDossier(null);
      const nextSegment = nextRoute.segments?.[selectedSegment];
      if (nextSegment && hasPanel('dossier')) api(`/api/segment/${nextSegment.id}/dossier`).then(setDossier).catch(() => setDossier(null));
      setNotice(`Showing the ${CLAIMS.find((item) => item.value === value)?.label || value} audit. All three claim audits were calculated together.`);
    }
  };

  const changeSite = (value) => {
    if (value === site || !SITE_AREAS[value]) return;
    setSite(value);
    setTargetName(`${SITE_AREAS[value].label} field target`);
    setWaypoints([]);
    setMapMode('2d');
    setMap3dMessage('');
    invalidateRoute();
    setNotice(`Switched to ${SITE_AREAS[value].label}. Draw a new route for this location.`);
  };

  const runStress = async (scenario, segmentIndex = selectedSegment) => {
    const stressSegment = route?.segments?.[segmentIndex];
    if (!stressSegment) { setError('Create a route in Tools before running a stress test.'); return; }
    setSelectedSegment(segmentIndex);
    setStressBusy(true); setError(''); setNotice('');
    try {
      await api('/api/stress', { method: 'POST', body: JSON.stringify({ segment_id: stressSegment.id, scenario }) });
      const latestDossier = await api(`/api/segment/${stressSegment.id}/dossier`);
      setDossier(latestDossier);
      const updateRoute = (old) => old ? ({ ...old, segments: old.segments.map((segment) => segment.id === stressSegment.id ? { ...segment, verdict: latestDossier.verdict, flags: latestDossier.flags } : segment) }) : old;
      setRoute(updateRoute);
      setClaimRuns((old) => old ? ({ ...old,
        routes: { ...old.routes, [claim]: updateRoute(old.routes[claim]) },
      }) : old);
      const updatedExtras = await refreshMission(route.route_id);
      setClaimRuns((old) => old ? ({ ...old, extras: { ...old.extras, [claim]: updatedExtras } }) : old);
    } catch (requestError) { setError(requestError.message); }
    finally { setStressBusy(false); }
  };

  const changeParam = (key, value) => setParams((old) => ({ ...old, [key]: { ...old[key], value } }));
  const saveParams = async () => {
    setSavingParams(true); setError('');
    try { setParams(await api('/api/params', { method: 'PUT', body: JSON.stringify(params) })); setNotice('Crew assumptions saved to the local API.'); }
    catch (requestError) { setError(requestError.message); }
    finally { setSavingParams(false); }
  };

  const speakVisor = () => {
    if (!voiceAvailable || !route?.segments?.[visorIndex]) return;
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(visorDirection(route.segments[visorIndex], visorDossier));
    utterance.rate = 0.9;
    utterance.pitch = 0.88;
    const voice = window.speechSynthesis.getVoices().find((candidate) => /en/i.test(candidate.lang));
    if (voice) utterance.voice = voice;
    window.speechSynthesis.speak(utterance);
  };

  const navigate = (view) => { window.location.hash = `#${view}`; };

  const activeCursorProducts = cursor?.products || [];
  const placeholder = footprintsLive === false || route?.data_status === 'PLACEHOLDER DATA';
  const hasDem = Boolean(dem?.z && dem?.w && dem?.h);
  const verdict = mission?.verdict || 'AWAITING ROUTE';
  const clock = mission?.clock;
  const safetyMargins = mission?.safety_margins || {};
  const hardLimits = mission?.hard_limits || {};
  const hardStopReasons = [
    hardLimits.reserve_breached && (safetyMargins.oxygen_pct < 0 || safetyMargins.power_pct < 0
      ? `Return reserve breached${safetyMargins.oxygen_pct < 0 ? ' · oxygen' : ''}${safetyMargins.power_pct < 0 ? ' · power' : ''}.`
      : 'Return reserve breached.'),
    hardLimits.obstacle_route_unavailable && 'Stress test found no route around the unseen obstacle.',
    hardLimits.slope_limit_exceeded && 'Coarse terrain slope plus the configured error margin exceeds the slope limit.',
  ].filter(Boolean);
  const statusBadge = status?.key === 'DEMO_KEY' ? 'DEMO_KEY · RATE LIMITED' : status?.key === 'custom' ? 'NASA KEY ACTIVE · SERVER ONLY' : 'KEY STATUS UNKNOWN';

  const setLayer = (key, value) => setLayers((old) => ({ ...old, [key]: value }));
  const weakestSegmentIndex = route?.segments?.findIndex((segment) => segment.verdict === 'Fragile') >= 0
    ? route.segments.findIndex((segment) => segment.verdict === 'Fragile')
    : route?.segments?.findIndex((segment) => segment.verdict === 'Check') >= 0
      ? route.segments.findIndex((segment) => segment.verdict === 'Check') : 0;
  const saveProject = () => {
    localStorage.setItem('cairn-project', JSON.stringify({ site, waypoints, targetName, claim, stopCount, layers }));
    setToolMessage('Project inputs saved in this browser.');
  };
  const loadProject = () => {
    try {
      const saved = JSON.parse(localStorage.getItem('cairn-project') || 'null');
      if (!saved) { setToolMessage('No saved project in this browser yet.'); return; }
      if (SITE_AREAS[saved.site]) setSite(saved.site);
      setWaypoints(saved.waypoints || []); setTargetName(saved.targetName || 'Jezero field target');
      setClaim(saved.claim || 'terrain'); setStopCount(saved.stopCount || 1); setLayers({ ...DEFAULT_LAYERS, ...saved.layers });
      invalidateRoute(); setToolMessage('Project inputs loaded. Recalculate the route to refresh its audit.');
    } catch { setToolMessage('Saved project could not be read.'); }
  };
  const loadRegistry = async () => {
    try { setRegistryRows(await api(`/api/registry?site=${site}&${boxQuery(area)}`)); }
    catch (requestError) { setToolMessage(`Registry unavailable: ${requestError.message}`); }
  };
  const loadNasaImages = async () => {
    try { const images = await api('/api/rover-photos?rover=perseverance&sol=1'); setPhoto(images[0] || null); setToolMessage(images.length ? 'NASA rover context image loaded.' : 'No context image returned.'); }
    catch (requestError) { setToolMessage(`NASA image lookup unavailable: ${requestError.message}`); }
  };
  const demoSteps = [
    'Pick a target in Tools.', 'Draw the route by clicking the map, then calculate it in Tools.',
    'Turn on Data footprints in the layer bar.', 'Open a weak segment from the evidence strip or map.',
    'Run the stress test.', 'Read the updated verdict and limits.', 'Open Visor mode.', 'Open the Brief.',
  ];
  const layerChip = (key, label) => h('button', { className: `layer-chip ${layers[key] ? 'chip-on' : ''}`, 'aria-pressed': layers[key], onClick: () => setLayer(key, !layers[key]), key }, label);
  const advLayer = (key, label, note = '') => h(LayerSwitch, { key, label, note, checked: layers[key], onChange: (value) => setLayer(key, value) });
  const toolsPanel = hasPanel('tools') && h('aside', { className: `tools-panel side-panel ${hasPanel('dossier') ? 'tools-shift' : ''}`, 'aria-label': 'Tools' },
    h('div', { className: 'side-panel-head' }, h('div', null, h('span', { className: 'eyebrow' }, 'TOOLS'), h('h2', null, 'Mission setup and advanced controls')),
      h('button', { className: 'icon-button', onClick: () => closePanel('tools'), 'aria-label': 'Close tools' }, '×')),
    h('section', { className: 'tools-section' }, h('h3', null, 'Target and route'),
      h('label', { className: 'tool-field' }, 'Landing region', h('select', { className: 'text-input', value: site, onChange: (event) => changeSite(event.target.value) },
        Object.entries(SITE_AREAS).map(([key, location]) => h('option', { key, value: key }, location.label)))),
      h('label', { className: 'tool-field' }, 'Science target', h('input', { className: 'text-input', value: targetName, onChange: (event) => setTargetName(event.target.value) })),
      h('div', { className: 'claim-results', role: 'group', 'aria-label': 'Evidence claim results' },
        h('h4', null, 'Evidence claims · one calculation'),
        h('p', null, claimRuns ? 'All three audits are ready. Choose one to inspect its route.' : 'Calculate once to audit Terrain, Current conditions, and Thermal together.'),
        CLAIMS.map((item) => h('button', { key: item.value, className: `claim-result ${claim === item.value ? 'claim-result-selected' : ''}`,
          'aria-pressed': claim === item.value, disabled: !claimRuns, onClick: () => changeClaim(item.value) },
        h('span', null, item.label), h('b', null, claimVerdict(claimRuns?.routes?.[item.value])),
        h('small', null, claimRuns ? `${claimRuns.routes[item.value].segments.length} route segments · click to inspect` : 'Calculated with the route')))),
      h('label', { className: 'tool-field' }, 'Planned stops', h('input', { className: 'text-input', type: 'number', min: 1, value: stopCount, onChange: (event) => setStopCount(Math.max(1, Number(event.target.value) || 1)) })),
      h('div', { className: 'tool-actions' }, h('button', { onClick: () => setDrawing((value) => !value) }, drawing ? 'Pause drawing' : 'Draw route'),
        h('button', { onClick: () => setWaypoints((old) => { invalidateRoute(); return old.slice(0, -1); }) }, 'Undo waypoint'),
        h('button', { onClick: () => { setWaypoints([]); invalidateRoute(); } }, 'Clear route'),
        h('button', { onClick: () => toolsRef.current.fit?.() }, 'Fit map'),
        h('button', { onClick: () => toolsRef.current.zoomIn?.() }, 'Zoom in'), h('button', { onClick: () => toolsRef.current.zoomOut?.() }, 'Zoom out')),
      h('div', { className: 'tool-route-calculate' },
        h('span', null, waypoints.length >= 2 ? `${waypoints.length} waypoints · ${area.label}` : 'Place at least two map points to calculate route distance and audit.'),
        h('button', { className: 'action-button', onClick: calculateRoute, disabled: busy || waypoints.length < 2 }, busy ? 'Calculating route and 3 claims…' : 'Calculate route + all 3 claims'))),
    h('section', { className: 'tools-section' }, h('h3', null, 'Assumptions'),
      h(AssumptionsDrawer, { params, onParamsChange: changeParam, onSave: saveParams, saving: savingParams, canEdit: Boolean(status?.param_updates_enabled) })),
    h('section', { className: 'tools-section' }, h('h3', null, 'Advanced map layers'),
      advLayer('alternate', 'Alternate route'), advLayer('comms', 'Comms line-of-sight', 'Geometric only'),
      advLayer('radiation', 'Radiation context', 'Other site'),
      ['CTX', 'HiRISE', 'CRISM', 'THEMIS'].map((name) => advLayer(name, `${name} footprint`, `${products.filter((item) => item.inst === name).length} products`)),
      h('label', { className: 'tool-field' }, 'WMS basemap style', h('select', { className: 'text-input', value: mapLayer, onChange: (event) => setMapLayer(event.target.value) },
        h('option', { value: '' }, `Auto · ${mapLayers.auto || 'local cache'}`), (mapLayers.layers || []).map((name) => h('option', { key: name, value: name }, name)))),
      h('div', { className: 'sensor-mode tools-sensors' }, [['plain', 'Plain'], ['night', 'Night vision'], ['thermal', 'Thermal']].map(([value, label]) => h('button', { key: value, className: sensor === value ? 'sensor-selected' : '', onClick: () => setSensor(value) }, label))),
      h('p', null, `Slope display: ${dem?.layer || 'DEM'}${dem?.res ? ` · ${dem.res} m/px` : ''}`)),
    h('section', { className: 'tools-section' }, h('h3', null, 'Registry, gaps and context'),
      h('div', { className: 'tool-actions' }, h('button', { onClick: loadRegistry }, 'Load registry'), h('button', { onClick: loadNasaImages }, 'NASA rover image search')),
      h('p', null, `NASA API key status: ${statusBadge}`),
      registryRows && h('p', null, `Registry: ${registryRows.length} records${registryRows.some((row) => row.is_placeholder) ? ' · includes placeholder records' : ''}`),
      h('p', null, `Gaps list: ${dossier?.needed || 'Select a segment to see its next useful observation.'}`),
      h('p', null, 'MEDA context is not available in this build.'),
      photo && h('div', { className: 'tool-photo' }, h('img', { src: photo.img_src, alt: 'NASA rover context image' }), h('span', null, `${photo.title || photo.camera || 'Rover image'} · context image, not this exact location`))),
    h('section', { className: 'tools-section' }, h('h3', null, 'Project and validation'),
      h('div', { className: 'tool-actions' }, h('button', { onClick: saveProject }, 'Save project'), h('button', { onClick: loadProject }, 'Load project')),
      h('p', null, 'Project inputs are saved in this browser; loaded routes must be recalculated.'),
      h('p', null, 'Validation tests: run pytest backend/tests from the repository root.'), toolMessage && h('p', { role: 'status' }, toolMessage)));

  const showTools = () => hasPanel('tools') ? closePanel('tools') : openPanel('tools');
  const runMainStress = () => route?.segments?.length ? runStress('unseen_obstacle', weakestSegmentIndex) : setError('Create a route in Tools before running a stress test.');

  return h('div', { className: `app-frame ${cleanMode ? 'clean-mode' : ''}` },
    h('header', { className: 'topbar' },
      h('div', { className: 'brand-lockup' }, h('div', { className: 'brand-mark' }, 'C'), h('div', null, h('b', null, 'CAIRN'), h('span', null, 'TRAIL MODE'))),
      h('nav', { className: 'main-nav', 'aria-label': 'Main navigation' },
        [['planner', 'Plan'], ['visor', 'Field visor'], ['brief', 'Mission brief']].map(([view, label]) => h('a', {
          key: view, href: `#${view}`, className: activeView === view ? 'nav-current' : undefined,
          'aria-current': activeView === view ? 'page' : undefined,
        }, label))),
      h('div', { className: 'header-actions' },
        activeView === 'planner' && h('button', { onClick: showTools, 'aria-expanded': hasPanel('tools') }, 'Tools'),
        activeView === 'planner' && h('button', { onClick: () => hasPanel('demo') ? closePanel('demo') : openPanel('demo'), 'aria-expanded': hasPanel('demo') }, 'Guide'),
        h('button', { onClick: () => setCleanMode((value) => !value), 'aria-pressed': cleanMode }, cleanMode ? 'Effects off' : 'Clean')),
      h('div', { className: 'top-status' }, h('span', { className: `status-led ${status?.key ? 'led-ready' : ''}` }), placeholder && h('b', { className: 'placeholder-badge' }, 'PLACEHOLDER DATA'))),
    activeView === 'planner' && h('main', { className: 'planner-page' },
      h('section', { className: `mission-banner mission-${verdict.toLowerCase().replaceAll(' ', '-')}` },
        h('div', { className: 'mission-verdict-block' }, h('span', { className: 'eyebrow' }, 'MISSION VERDICT / ADVISORY ONLY'), h('strong', null, verdict),
          h('small', null, mission?.directive ? mission.directive.toUpperCase() : 'PLANNING-TIME · NO LIVE TELEMETRY')),
        h('div', { className: 'mission-clock' }, h('span', { className: 'eyebrow' }, 'TURN-BACK CLOCK'), h('b', null, clock?.point || '—'),
          h('small', null, clock ? `${clock.elapsed_outbound_minutes} min outbound · ${clock.return_time_minutes} min return` : 'Draw a route in Tools')),
        h('div', { className: 'mission-margin' }, h('span', { className: 'eyebrow' }, 'WORST-CASE MARGIN'),
          h('b', null, mission?.safety_margins ? `O₂ ${mission.safety_margins.oxygen_pct}%  /  PWR ${mission.safety_margins.power_pct}%` : 'O₂ —  /  PWR —'),
          h('small', null, mission?.safety_margins ? `DAYLIGHT ${mission.safety_margins.daylight_minutes} min` : 'reserve intact required'))),
      verdict === 'NO-GO' && h('div', { className: 'hard-stop-banner', role: 'alert' }, h('b', null, 'HARD STOP /'),
        h('span', null, hardStopReasons.length ? hardStopReasons.join(' ') : (mission?.directive || 'Return to shelter.')),
        h('small', null, 'Route colours show evidence checks, not resource or stress limits.')),
      mission?.fixes?.length > 0 && h('div', { className: 'fix-banner' }, mission.fixes.map((fix, index) => h('span', { key: index }, fix.action))),
      error && h('div', { className: 'error-line' }, error), notice && h('div', { className: 'notice-line' }, notice),
      hasPanel('demo') && h('section', { className: 'demo-guide' }, h('b', null, `DEMO · ${demoStep + 1} / ${demoSteps.length}`),
        h('span', null, demoSteps[demoStep]), h('button', { onClick: () => setDemoStep((step) => (step + 1) % demoSteps.length) }, demoStep === demoSteps.length - 1 ? 'Restart' : 'Next step'),
        h('button', { onClick: () => closePanel('demo'), 'aria-label': 'Close demo guide' }, '×')),
      !route && h('section', { className: 'route-guide panel', 'aria-labelledby': 'route-guide-title' },
        h('div', { className: 'route-guide-copy' }, h('span', { className: 'eyebrow' }, 'GET STARTED'), h('h1', { id: 'route-guide-title' }, 'Plan a route'),
          h('p', null, 'Choose a target, place waypoints on the map, then calculate the route and evidence checks.')),
        h('ol', { className: 'route-guide-steps' },
          h('li', null, h('b', null, '1'), h('span', null, 'Choose a region and target in Tools')),
          h('li', null, h('b', null, '2'), h('span', null, 'Click the map to place at least two points')),
          h('li', null, h('b', null, '3'), h('span', null, 'Calculate the route in Tools'))),
        h('button', { className: 'action-button', onClick: () => openPanel('tools') }, 'Open Tools')),
      route && h('div', { className: 'primary-actions' },
        h('button', { className: 'action-button', onClick: runMainStress, disabled: stressBusy }, stressBusy ? 'Running stress test…' : 'Run stress test')),
      h('div', { className: 'map-section' },
        h('div', { className: 'map-mode-row' },
          h('div', { className: 'map-mode-toggle', role: 'group', 'aria-label': 'Map dimension' },
            h('button', { 'aria-pressed': mapMode === '2d', onClick: () => setMapMode('2d') }, '2D'),
            h('button', { 'aria-pressed': mapMode === '3d', disabled: !hasDem || webglAvailable !== true,
              title: !hasDem ? '3D requires the DEM for this area.' : webglAvailable === false ? 'WebGL is unavailable; use 2D.' : 'Open the 3D terrain view',
              onClick: () => { setMap3dMessage(''); setMapMode('3d'); } }, '3D')),
          map3dMessage && h('span', { className: 'map-mode-message', role: 'status' }, map3dMessage),
          !hasDem && h('span', { className: 'map-mode-message', title: '3D requires the DEM for this area.' }, '3D disabled · DEM not loaded')),
        h('div', { className: 'map-stage sensor-' + sensor }, mapMode === '3d'
          ? h(React.Suspense, { fallback: h('div', { className: 'map3d-loading' }, 'Loading local 3D terrain…') },
            h(Map3DView, { dem, area, layers, products, route, waypoints, mission, sensor, mapLayer, showVerdictColors, onSegmentSelect: selectSegment,
              verticalExaggeration, onExaggerationChange: setVerticalExaggeration,
              onUnavailable: () => { setWebglAvailable(false); setMapMode('2d'); setMap3dMessage('3D unavailable: WebGL could not start. Staying in 2D.'); } }))
          : h(MapView, { area, layers, products, dem, route, waypoints, drawing, sensor, mapLayer, toolsRef,
            showVerdictColors, onSegmentSelect: selectSegment, scanning: busy || stressBusy,
            onWaypointsChange: setWaypoints, onRouteInvalidated: invalidateRoute, onCursor: setCursor, onMapStatus: setMapStatus })),
        h('div', { className: 'compact-layer-bar', 'aria-label': 'Map layers' },
          h('label', { className: 'basemap-picker' }, h('span', null, 'Map style'),
            h('select', { value: mapLayer, onChange: (event) => { setMapLayer(event.target.value); setSensor('plain'); }, 'aria-label': 'Basemap style' },
              QUICK_BASEMAPS.filter(([value]) => !value || (mapLayers.layers || []).includes(value)).map(([value, label]) => h('option', { key: value || 'auto', value }, value ? label : `Automatic · ${mapLayers.auto || 'loading'}`)))),
          layerChip('basemap', 'Basemap'), layerChip('slope', 'Slope'), layerChip('footprints', 'Data footprints'),
          layerChip('route', 'Route'), h('button', { className: `layer-chip ${showVerdictColors ? 'chip-on' : ''}`, 'aria-pressed': showVerdictColors, onClick: () => setShowVerdictColors((value) => !value) }, 'Verdict colours'), layerChip('stops', 'Stops')),
        h('div', { className: 'map-readout' }, h('span', null, mapStatus),
          h('span', null, cursor ? `lat ${cursor.point[1].toFixed(4)}°  lon ${cursor.point[0].toFixed(4)}°` : 'Move cursor for coordinates'),
          h('span', null, cursor ? activeCursorProducts.length ? activeCursorProducts.map((item) => item.id).join(' · ') : 'No product footprint' : 'Product coverage')),
      h('section', { className: 'strip-section panel' }, h('div', { className: 'strip-section-head' }, h('b', null, 'EVIDENCE + RESOURCE STRIPS'),
        h('span', null, route ? `${route.segments.length} segments · select a weak segment` : 'Create a route in Tools to begin')),
        selected && h('p', { className: 'route-human-summary', 'aria-live': 'polite' }, segmentSummary(selected)),
        h(MissionStrips, { route, resources, selectedSegment: hasPanel('dossier') ? selectedSegment : -1, onSelectSegment: selectSegment })))),
    activeView === 'visor' && h(VisorPage, { route, segmentIndex: visorIndex, setSegmentIndex: setVisorIndex,
      dossier: visorDossier, onSpeak: speakVisor, voiceAvailable, onPlanner: () => navigate('planner') }),
    activeView === 'brief' && h(BriefPage, { data: briefData, error: briefError, loading: briefLoading,
      onPrint: () => window.print(), onPlanner: () => navigate('planner') }),
    activeView === 'planner' && toolsPanel,
    activeView === 'planner' && hasPanel('dossier') && h(ProductDossier, { dossier, segment: selected, stressBusy, onStress: runStress, onClose: () => closePanel('dossier') }));
}

createRoot(document.getElementById('root')).render(h(MainApp));
