import React, { useEffect, useRef, useState } from 'react';
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { demToTerrainMesh } from './terrain.js';
import './map3d.css';

const h = React.createElement;
const DEFAULT_AREA = { lo0: 76.8, la0: 17.6, lo1: 78.4, la1: 19.2 };
const PRODUCT_COLORS = { CTX: '#f5a623', HiRISE: '#45c5ff', CRISM: '#c084fc', THEMIS: '#51d88a' };
const COLORS = { Supported: '#4bdd9a', Check: '#f4bd4f', Fragile: '#ff5e64' };

function encodeBox(box) {
  return new URLSearchParams({ lo0: box.lo0, la0: box.la0, lo1: box.lo1, la1: box.la1 }).toString();
}

function imageFromUrl(url) {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = reject;
    image.src = url;
  });
}

function slopeCanvas(dem) {
  const binary = atob(dem.z); const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
  const values = new DataView(bytes.buffer); const width = dem.w; const height = dem.h;
  const canvas = document.createElement('canvas'); canvas.width = width; canvas.height = height;
  const context = canvas.getContext('2d'); const image = context.createImageData(width, height);
  const stops = [[13, 99, 145], [17, 199, 157], [241, 188, 67], [245, 88, 49], [234, 39, 75]];
  const elev = (x, y) => values.getFloat32((y * width + x) * 4, true);
  for (let y = 0; y < height; y += 1) for (let x = 0; x < width; x += 1) {
    const dx = Math.max(1, (dem.b.lo1 - dem.b.lo0) / (width - 1) * 59150 * Math.cos(18 * Math.PI / 180));
    const dy = Math.max(1, (dem.b.la1 - dem.b.la0) / (height - 1) * 59150);
    const gx = (elev(Math.min(width - 1, x + 1), y) - elev(Math.max(0, x - 1), y)) / (2 * dx);
    const gy = (elev(x, Math.min(height - 1, y + 1)) - elev(x, Math.max(0, y - 1))) / (2 * dy);
    const degrees = Math.atan(Math.hypot(gx, gy)) * 180 / Math.PI;
    const scaled = Math.max(0, Math.min(1, degrees / 35)) * (stops.length - 1);
    const index = Math.min(stops.length - 2, Math.floor(scaled)); const t = scaled - index; const offset = (y * width + x) * 4;
    image.data[offset] = stops[index][0] * (1 - t) + stops[index + 1][0] * t;
    image.data[offset + 1] = stops[index][1] * (1 - t) + stops[index + 1][1] * t;
    image.data[offset + 2] = stops[index][2] * (1 - t) + stops[index + 1][2] * t;
    image.data[offset + 3] = 190;
  }
  context.putImageData(image, 0, 0);
  return canvas;
}

function hillshadeCanvas(dem) {
  const binary = atob(dem.z); const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
  const values = new DataView(bytes.buffer); const width = dem.w; const height = dem.h;
  const canvas = document.createElement('canvas'); canvas.width = width; canvas.height = height;
  const context = canvas.getContext('2d'); const image = context.createImageData(width, height);
  const dx = Math.max(1, (dem.b.lo1 - dem.b.lo0) * 59150 * Math.cos(((dem.b.la0 + dem.b.la1) / 2) * Math.PI / 180) / Math.max(width - 1, 1));
  const dy = Math.max(1, (dem.b.la1 - dem.b.la0) * 59150 / Math.max(height - 1, 1));
  const elev = (x, y) => values.getFloat32((y * width + x) * 4, true);
  const azimuth = 315 * Math.PI / 180; const altitude = 38 * Math.PI / 180;
  for (let y = 0; y < height; y += 1) for (let x = 0; x < width; x += 1) {
    const gx = (elev(Math.min(width - 1, x + 1), y) - elev(Math.max(0, x - 1), y)) / (2 * dx);
    const gy = (elev(x, Math.min(height - 1, y + 1)) - elev(x, Math.max(0, y - 1))) / (2 * dy);
    const nx = -gx; const ny = -gy; const nz = 1; const norm = Math.hypot(nx, ny, nz);
    const light = Math.max(0, (nx * Math.cos(altitude) * Math.sin(azimuth) + ny * Math.cos(altitude) * Math.cos(azimuth) + nz * Math.sin(altitude)) / norm);
    const offset = (y * width + x) * 4;
    const shade = Math.round(118 + light * 137);
    image.data[offset] = shade; image.data[offset + 1] = shade; image.data[offset + 2] = shade; image.data[offset + 3] = 255;
  }
  context.putImageData(image, 0, 0);
  return canvas;
}

function drawHatch(context, products, area) {
  const tile = document.createElement('canvas'); tile.width = tile.height = 12;
  const tileContext = tile.getContext('2d'); tileContext.strokeStyle = 'rgba(150,205,191,.65)'; tileContext.lineWidth = 1;
  tileContext.beginPath(); tileContext.moveTo(-2, 10); tileContext.lineTo(10, -2); tileContext.stroke();
  tileContext.beginPath(); tileContext.moveTo(2, 14); tileContext.lineTo(14, 2); tileContext.stroke();
  const pattern = context.createPattern(tile, 'repeat'); const width = context.canvas.width; const height = context.canvas.height;
  const covered = (lon, lat) => products.some((product) => {
    const polygon = product.poly || []; let inside = false;
    for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
      const [xi, yi] = polygon[i] || []; const [xj, yj] = polygon[j] || [];
      if ((yi > lat) !== (yj > lat) && lon < ((xj - xi) * (lat - yi)) / (yj - yi) + xi) inside = !inside;
    }
    return inside;
  });
  context.save(); context.globalAlpha = 0.48; context.fillStyle = pattern;
  const step = 5;
  for (let y = 0; y < height; y += step) for (let x = 0; x < width; x += step) {
    const lon = area.lo0 + x / width * (area.lo1 - area.lo0);
    const lat = area.la1 - y / height * (area.la1 - area.la0);
    if (!covered(lon, lat)) context.fillRect(x, y, step, step);
  }
  context.restore();
}

function disposeGroup(group) {
  group.traverse((item) => {
    item.geometry?.dispose();
    if (Array.isArray(item.material)) item.material.forEach((material) => { material.map?.dispose(); material.dispose(); });
    else if (item.material) { item.material.map?.dispose(); item.material.dispose(); }
  });
  while (group.children.length) group.remove(group.children[0]);
}

export default function Map3DView({ dem, area = DEFAULT_AREA, layers, products, route, waypoints, mission, sensor, mapLayer, showVerdictColors, onSegmentSelect, onUnavailable, verticalExaggeration, onExaggerationChange }) {
  const host = useRef(null); const rendererRef = useRef(null); const sceneRef = useRef(null);
  const cameraRef = useRef(null); const controlsRef = useRef(null); const contentRef = useRef(null);
  const demCacheRef = useRef(new Map()); const detailCacheRef = useRef(new Map());
  const requestedFactorRef = useRef(1); const extentRequestRef = useRef(0); const detailRequestRef = useRef(0); const detailKeyRef = useRef('');
  const [viewReady, setViewReady] = useState(false);
  const [viewDem, setViewDem] = useState(dem);
  const [detailDem, setDetailDem] = useState(null);
  const [extentMessage, setExtentMessage] = useState('');

  useEffect(() => {
    demCacheRef.current = new Map([['1', dem]]);
    requestedFactorRef.current = 1;
    extentRequestRef.current += 1;
    detailRequestRef.current += 1; detailKeyRef.current = '';
    setViewDem(dem);
    detailCacheRef.current.clear(); setDetailDem(null);
    setExtentMessage('');
  }, [dem]);

  useEffect(() => {
    let renderer; let controls; let observer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false, powerPreference: 'high-performance' });
      renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
      renderer.outputColorSpace = THREE.SRGBColorSpace;
      renderer.shadowMap.enabled = true;
      renderer.shadowMap.type = THREE.PCFSoftShadowMap;
      renderer.setClearColor('#091311', 1);
      host.current.appendChild(renderer.domElement);
      const scene = new THREE.Scene(); scene.background = new THREE.Color('#091311');
      const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 2000);
      camera.up.set(0, 0, 1);
      camera.position.set(0, -122, 100);
      const orbit = new OrbitControls(camera, renderer.domElement); controls = orbit;
      orbit.enableDamping = true; orbit.dampingFactor = 0.075; orbit.minDistance = 0.75; orbit.maxDistance = 1200;
      orbit.zoomSpeed = 1.15; orbit.target.set(0, 0, 0); orbit.update();
      scene.add(new THREE.HemisphereLight(0xd9fff1, 0x18221d, 2));
      const sun = new THREE.DirectionalLight(0xffffff, 2.6); sun.position.set(-45, -55, 85); sun.castShadow = true;
      sun.shadow.mapSize.set(1024, 1024); sun.shadow.camera.left = -120; sun.shadow.camera.right = 120;
      sun.shadow.camera.top = 120; sun.shadow.camera.bottom = -120; sun.shadow.bias = -0.0003; scene.add(sun);
      const content = new THREE.Group(); scene.add(content);
      rendererRef.current = renderer; sceneRef.current = scene; cameraRef.current = camera; controlsRef.current = orbit; contentRef.current = content;
      const resize = () => {
        if (!host.current) return;
        const width = host.current.clientWidth || 800; const height = host.current.clientHeight || 500;
        renderer.setSize(width, height, false); camera.aspect = width / height; camera.updateProjectionMatrix();
      };
      observer = new ResizeObserver(resize); observer.observe(host.current); resize();
      renderer.setAnimationLoop(() => { orbit.update(); renderer.render(scene, camera); });
      setViewReady(true);
    } catch (_error) {
      setViewReady(false); onUnavailable?.();
      return undefined;
    }
    return () => {
      observer?.disconnect(); renderer?.setAnimationLoop(null); controls?.dispose();
      if (contentRef.current) disposeGroup(contentRef.current);
      renderer?.dispose(); renderer?.domElement?.remove();
      rendererRef.current = null; sceneRef.current = null; cameraRef.current = null; controlsRef.current = null; contentRef.current = null;
    };
  }, []);

  useEffect(() => {
    const controls = controlsRef.current; const camera = cameraRef.current;
    if (!controls || !camera || !dem) return undefined;
    let timer;
    let active = true;
    const baseDistance = Math.max(32, (area.la1 - area.la0) * 59.15 * 1.66);
    const loadExtent = async (factor) => {
      const key = String(factor);
      if (demCacheRef.current.has(key)) {
        extentRequestRef.current += 1;
        setViewDem(demCacheRef.current.get(key)); setExtentMessage(factor > 1 ? `Showing ${factor}× surrounding terrain` : ''); return;
      }
      const halfLon = (area.lo1 - area.lo0) * factor / 2; const halfLat = (area.la1 - area.la0) * factor / 2;
      const centerLon = (area.lo0 + area.lo1) / 2; const centerLat = (area.la0 + area.la1) / 2;
      const bounds = { lo0: centerLon - halfLon, lo1: centerLon + halfLon, la0: centerLat - halfLat, la1: centerLat + halfLat };
      const requestId = ++extentRequestRef.current;
      setExtentMessage(`Loading ${factor}× surrounding terrain…`);
      try {
        const response = await fetch(`/api/dem?${encodeBox(bounds)}`);
        if (!response.ok) throw new Error('surrounding DEM unavailable');
        const nextDem = await response.json();
        if (!active || requestId !== extentRequestRef.current) return;
        demCacheRef.current.set(key, nextDem);
        setViewDem(nextDem); setExtentMessage(`Showing ${factor}× surrounding terrain`);
      } catch (_error) {
        if (active && requestId === extentRequestRef.current) setExtentMessage('Surrounding DEM unavailable; keeping the loaded terrain extent');
      }
    };
    let detailTimer;
    const requestHiRiseDetail = async (ratio) => {
      if (ratio > 0.45) { detailRequestRef.current += 1; detailKeyRef.current = ''; setDetailDem(null); return; }
      const factor = ratio < 0.015 ? 0.008 : ratio < 0.04 ? 0.02 : ratio < 0.12 ? 0.06 : 0.18;
      const currentMesh = demToTerrainMesh(viewDem, 1, 256); const bounds = currentMesh.bounds;
      const centerLon = bounds.lo0 + (controls.target.x / currentMesh.worldWidth + 0.5) * (bounds.lo1 - bounds.lo0);
      const latFraction = 0.5 - controls.target.y / currentMesh.worldHeight;
      const centerLat = bounds.la1 - latFraction * (bounds.la1 - bounds.la0);
      const latSpan = (area.la1 - area.la0) * factor; const lonSpan = (area.lo1 - area.lo0) * factor;
      const key = [factor, centerLon.toFixed(4), centerLat.toFixed(4)].join(':');
      if (key === detailKeyRef.current) return;
      detailKeyRef.current = key;
      if (detailCacheRef.current.has(key)) { setDetailDem(detailCacheRef.current.get(key)); setExtentMessage('HiRISE stereo detail loaded · 1 m source'); return; }
      const id = ++detailRequestRef.current;
      const queryBox = { lo0: centerLon - lonSpan / 2, lo1: centerLon + lonSpan / 2,
        la0: centerLat - latSpan / 2, la1: centerLat + latSpan / 2 };
      setExtentMessage('Loading local HiRISE stereo terrain…');
      try {
        const response = await fetch(`/api/dem/hirise?${encodeBox(queryBox)}`);
        if (!response.ok) throw new Error('no HiRISE DTM data at this view');
        const next = await response.json();
        if (!active || id !== detailRequestRef.current) return;
        detailCacheRef.current.set(key, next); setDetailDem(next);
        setExtentMessage('HiRISE stereo detail loaded · 1 m source');
      } catch (_error) {
        if (active && id === detailRequestRef.current) {
          setDetailDem(null);
          setExtentMessage('No HiRISE DTM coverage here; coarse MOLA remains visible');
        }
      }
    };
    const onControlsChange = () => {
      const distanceRatio = camera.position.distanceTo(controls.target) / baseDistance;
      const factor = distanceRatio >= 2.55 ? 4 : distanceRatio >= 1.35 ? 2 : 1;
      if (factor !== requestedFactorRef.current) {
        requestedFactorRef.current = factor;
        clearTimeout(timer);
        timer = setTimeout(() => loadExtent(factor), 420);
      }
      if (distanceRatio < 0.45) {
        clearTimeout(detailTimer);
        detailTimer = setTimeout(() => requestHiRiseDetail(distanceRatio), 550);
      } else if (distanceRatio >= 0.45 && detailDem) {
        clearTimeout(detailTimer); setDetailDem(null);
      }
    };
    controls.addEventListener('change', onControlsChange);
    return () => { active = false; clearTimeout(timer); clearTimeout(detailTimer); controls.removeEventListener('change', onControlsChange); };
  }, [area, dem, viewDem, detailDem]);

  useEffect(() => {
    const renderer = rendererRef.current; const scene = sceneRef.current; const previous = contentRef.current;
    if (!renderer || !scene || !previous || !viewDem?.z) return undefined;
    scene.remove(previous); disposeGroup(previous);
    const group = new THREE.Group(); scene.add(group); contentRef.current = group;
    let cancelled = false;
    const activeDem = viewDem;
    const meshData = demToTerrainMesh(activeDem, 1, 256);
    group.scale.z = verticalExaggeration;
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.BufferAttribute(meshData.positions, 3));
    const uv = new Float32Array(meshData.width * meshData.height * 2);
    for (let y = 0; y < meshData.height; y += 1) for (let x = 0; x < meshData.width; x += 1) {
      const i = y * meshData.width + x; uv[i * 2] = x / (meshData.width - 1); uv[i * 2 + 1] = 1 - y / (meshData.height - 1);
    }
    geometry.setAttribute('uv', new THREE.BufferAttribute(uv, 2)); geometry.setIndex(new THREE.BufferAttribute(meshData.indices, 1)); geometry.computeVertexNormals();
    const textureCanvas = document.createElement('canvas'); textureCanvas.width = 800; textureCanvas.height = 800;
    const context = textureCanvas.getContext('2d'); context.fillStyle = '#17221f'; context.fillRect(0, 0, 800, 800);
    const texture = new THREE.CanvasTexture(textureCanvas); texture.colorSpace = THREE.SRGBColorSpace; texture.anisotropy = renderer.capabilities.getMaxAnisotropy();
    const terrain = new THREE.Mesh(geometry, new THREE.MeshStandardMaterial({ map: texture, roughness: 1, metalness: 0, side: THREE.DoubleSide }));
    terrain.receiveShadow = true; terrain.castShadow = true;
    group.add(terrain);

    const b = meshData.bounds; const mean = meshData.meanElevation;
    const metersPerUnit = meshData.metersPerUnit || 1000;
    let hiResMeshData = null;
    if (detailDem?.z) {
      hiResMeshData = demToTerrainMesh(detailDem, 1, 256);
      const detailGeometry = new THREE.BufferGeometry();
      const positions = hiResMeshData.positions.slice();
      const detailMeanOffset = (hiResMeshData.meanElevation - mean) / 1000;
      for (let i = 2; i < positions.length; i += 3) positions[i] += detailMeanOffset;
      detailGeometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
      const detailUv = new Float32Array(hiResMeshData.width * hiResMeshData.height * 2);
      const db = hiResMeshData.bounds;
      for (let y = 0; y < hiResMeshData.height; y += 1) for (let x = 0; x < hiResMeshData.width; x += 1) {
        const i = y * hiResMeshData.width + x;
        const lon = db.lo0 + x / (hiResMeshData.width - 1) * (db.lo1 - db.lo0);
        const lat = db.la1 - y / (hiResMeshData.height - 1) * (db.la1 - db.la0);
        detailUv[i * 2] = (lon - b.lo0) / (b.lo1 - b.lo0);
        detailUv[i * 2 + 1] = (lat - b.la0) / (b.la1 - b.la0);
      }
      detailGeometry.setAttribute('uv', new THREE.BufferAttribute(detailUv, 2));
      detailGeometry.setIndex(new THREE.BufferAttribute(hiResMeshData.indices, 1)); detailGeometry.computeVertexNormals();
      const detailMesh = new THREE.Mesh(detailGeometry, new THREE.MeshStandardMaterial({ map: texture, roughness: 1, metalness: 0, side: THREE.DoubleSide, polygonOffset: true, polygonOffsetFactor: -1 }));
      const detailCenterLon = (db.lo0 + db.lo1) / 2; const detailCenterLat = (db.la0 + db.la1) / 2;
      detailMesh.position.x = ((detailCenterLon - b.lo0) / (b.lo1 - b.lo0) - 0.5) * meshData.worldWidth;
      const detailV = (b.la1 - detailCenterLat) / (b.la1 - b.la0);
      detailMesh.position.y = (0.5 - detailV) * meshData.worldHeight;
      detailMesh.receiveShadow = true; detailMesh.castShadow = true; detailMesh.renderOrder = 1;
      group.add(detailMesh);
    }
    const surfacePoint = (point, lift = 0.004) => {
      const [lon, lat] = point;
      const u = Math.max(0, Math.min(1, (lon - b.lo0) / (b.lo1 - b.lo0)));
      const v = Math.max(0, Math.min(1, (b.la1 - lat) / (b.la1 - b.la0)));
      let height = meshData.heights[Math.round(v * (meshData.height - 1)) * meshData.width + Math.round(u * (meshData.width - 1))];
      if (hiResMeshData) {
        const db = hiResMeshData.bounds;
        if (lon >= db.lo0 && lon <= db.lo1 && lat >= db.la0 && lat <= db.la1) {
          const du = (lon - db.lo0) / (db.lo1 - db.lo0); const dv = (db.la1 - lat) / (db.la1 - db.la0);
          const dx = Math.round(du * (hiResMeshData.width - 1)); const dy = Math.round(dv * (hiResMeshData.height - 1));
          height = hiResMeshData.heights[dy * hiResMeshData.width + dx];
        }
      }
      return new THREE.Vector3((u - 0.5) * meshData.worldWidth, (0.5 - v) * meshData.worldHeight,
        ((height - mean) / metersPerUnit) + lift);
    };

    const texturePromise = (async () => {
      if (layers.basemap) {
        try {
          const response = await fetch(`/api/basemap?${encodeBox(b)}&layer=${encodeURIComponent(mapLayer || '')}`);
          if (response.ok) { const bitmap = await createImageBitmap(await response.blob()); context.drawImage(bitmap, 0, 0, 800, 800); bitmap.close(); }
        } catch (_error) { /* retain the local terrain color when the WMS is unavailable */ }
        if (detailDem?.z) {
          try {
            const response = await fetch(`/api/dem/hirise/ortho?${encodeBox(b)}`);
            if (response.ok) {
              const ortho = await response.json(); const image = await imageFromUrl(ortho.image);
              const ob = ortho.b;
              const x = (ob.lo0 - b.lo0) / (b.lo1 - b.lo0) * 800;
              const y = (b.la1 - ob.la1) / (b.la1 - b.la0) * 800;
              const width = (ob.lo1 - ob.lo0) / (b.lo1 - b.lo0) * 800;
              const height = (ob.la1 - ob.la0) / (b.la1 - b.la0) * 800;
              context.drawImage(image, x, y, width, height);
            }
          } catch (_error) { /* WMS remains the texture if the local ortho cannot be decoded */ }
        }
      }
      if (cancelled) return;
      const hillshade = await imageFromUrl(hillshadeCanvas(dem).toDataURL('image/png'));
      if (!cancelled) { context.globalCompositeOperation = 'multiply'; context.globalAlpha = 0.58; context.drawImage(hillshade, 0, 0, 800, 800); context.globalCompositeOperation = 'source-over'; context.globalAlpha = 1; }
      if (cancelled) return;
      if (layers.slope) {
        const img = await imageFromUrl(slopeCanvas(activeDem).toDataURL('image/png'));
        if (!cancelled) { context.globalAlpha = 0.72; context.drawImage(img, 0, 0, 800, 800); context.globalAlpha = 1; }
      }
      if (cancelled) return;
      if (layers.footprints) {
        drawHatch(context, products || [], b);
        context.lineWidth = 2;
        (products || []).filter((product) => layers[product.inst]).forEach((product) => {
          const polygon = product.poly || []; if (polygon.length < 3) return;
          context.strokeStyle = PRODUCT_COLORS[product.inst] || '#a8c2bc';
          context.beginPath(); polygon.forEach(([lon, lat], index) => {
            const x = (lon - b.lo0) / (b.lo1 - b.lo0) * 800;
            const y = (b.la1 - lat) / (b.la1 - b.la0) * 800;
            if (index === 0) context.moveTo(x, y); else context.lineTo(x, y);
          }); context.closePath(); context.stroke();
        });
      }
      texture.needsUpdate = true;
    })();
    texturePromise.catch(() => {});

    const routeSegments = route?.segments || [];
    if (layers.route) routeSegments.forEach((segment, segmentIndex) => {
      const points = (segment.coordinates || []).map((point) => surfacePoint(point)); if (points.length < 2) return;
      const lineGeometry = new THREE.BufferGeometry().setFromPoints(points);
      const color = showVerdictColors ? (COLORS[segment.verdict] || '#64dfd1') : '#64dfd1';
      const line = new THREE.Line(lineGeometry, new THREE.LineBasicMaterial({ color, linewidth: 2 }));
      line.userData.segmentIndex = segmentIndex; group.add(line);
    });
    if (layers.alternate && route?.alternate?.coordinates?.length > 1) {
      const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints(route.alternate.coordinates.map((point) => surfacePoint(point, 0.01))),
        new THREE.LineDashedMaterial({ color: '#d5e1dc', dashSize: 2, gapSize: 1.2, linewidth: 1 }));
      line.computeLineDistances(); group.add(line);
    }
    if (layers.comms && waypoints?.length > 1) {
      const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints([surfacePoint(waypoints[0], 0.012), surfacePoint(waypoints.at(-1), 0.012)]),
        new THREE.LineDashedMaterial({ color: '#64dfd1', dashSize: 1, gapSize: 1 }));
      line.computeLineDistances(); group.add(line);
    }
    if (layers.stops) (waypoints || []).forEach((point, index) => {
      const marker = new THREE.Mesh(new THREE.SphereGeometry(0.07, 12, 8), new THREE.MeshStandardMaterial({ color: '#f0f8f4', emissive: '#367d6a', emissiveIntensity: 0.35 }));
      marker.position.copy(surfacePoint(point, 0.03)); marker.userData.segmentIndex = Math.min(index, Math.max(0, routeSegments.length - 1)); group.add(marker);
    });
    const turnSegment = routeSegments.find((segment) => segment.id === mission?.clock?.point);
    if (turnSegment?.coordinates?.length) {
      const marker = new THREE.Mesh(new THREE.OctahedronGeometry(0.11), new THREE.MeshStandardMaterial({ color: '#f4bd4f', emissive: '#7c5816', emissiveIntensity: 0.4 }));
      marker.position.copy(surfacePoint(turnSegment.coordinates.at(-1), 0.05));
      marker.userData.segmentIndex = routeSegments.indexOf(turnSegment); group.add(marker);
    }
    if (layers.radiation) {
      const flag = document.createElement('canvas'); flag.width = 512; flag.height = 42;
      const flagContext = flag.getContext('2d'); flagContext.fillStyle = 'rgba(50,22,13,.88)'; flagContext.fillRect(0, 0, 512, 42);
      flagContext.fillStyle = '#ffbd8e'; flagContext.font = 'bold 20px monospace'; flagContext.fillText('RADIATION CONTEXT · OTHER SITE · NO LOCAL GRID', 10, 28);
      const flagTexture = new THREE.CanvasTexture(flag); const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: flagTexture, transparent: true }));
      sprite.scale.set(64, 5.25, 1); sprite.position.set(0, 0, 8); group.add(sprite);
    }

    const raycaster = new THREE.Raycaster(); raycaster.params.Line.threshold = 1.2;
    const pointer = new THREE.Vector2();
    const handleClick = (event) => {
      const rect = renderer.domElement.getBoundingClientRect();
      pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
      pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
      raycaster.setFromCamera(pointer, cameraRef.current);
      const hit = raycaster.intersectObjects(group.children, true).find((item) => Number.isInteger(item.object.userData.segmentIndex));
      if (hit) onSegmentSelect?.(hit.object.userData.segmentIndex);
    };
    renderer.domElement.addEventListener('click', handleClick);

    return () => {
      cancelled = true; renderer.domElement.removeEventListener('click', handleClick);
      texturePromise.catch(() => {}); scene.remove(group); disposeGroup(group);
    };
  }, [viewDem, detailDem, area, layers, products, route, waypoints, mission, mapLayer, showVerdictColors, onSegmentSelect]);

  useEffect(() => { if (contentRef.current) contentRef.current.scale.z = verticalExaggeration; }, [verticalExaggeration]);

  const resetView = () => {
    if (!cameraRef.current || !controlsRef.current) return;
    cameraRef.current.position.set(0, -122, 100); cameraRef.current.up.set(0, 0, 1);
    controlsRef.current.target.set(0, 0, 0); controlsRef.current.update();
  };
  const topDown = () => {
    if (!cameraRef.current || !controlsRef.current) return;
    cameraRef.current.position.set(0, 0, 150); cameraRef.current.up.set(0, 1, 0);
    controlsRef.current.target.set(0, 0, 0); controlsRef.current.update();
  };
  return h('div', { className: `map3d-view sensor-${sensor}` },
    h('div', { className: 'map3d-canvas', ref: host, role: 'application', 'aria-label': 'Interactive three-dimensional Mars terrain' }),
    h('div', { className: 'map3d-controls' },
      h('button', { onClick: resetView, disabled: !viewReady }, 'Reset view'), h('button', { onClick: topDown, disabled: !viewReady }, 'Top-down'),
      h('label', null, 'Vertical exaggeration ', h('strong', null, `${verticalExaggeration.toFixed(1)}×`),
        h('input', { type: 'range', min: 1, max: 12, step: 0.5, value: verticalExaggeration, onChange: (event) => onExaggerationChange(Number(event.target.value)) }))),
    extentMessage && h('div', { className: 'map3d-extent-status', role: 'status' }, extentMessage),
    h('div', { className: 'map3d-label' }, '3D is a visual aid: MOLA elevation is coarse (~463 m/px), smoothing steep local slopes. Not used in the audit. Zoom out to load a wider terrain extent; relief shading is derived from the loaded DEM.'));
}
