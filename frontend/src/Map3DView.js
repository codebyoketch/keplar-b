import React, { useEffect, useRef, useState } from 'react';
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { demToTerrainMesh } from './terrain.js';
import './map3d.css';

const h = React.createElement;
const AREA = { lo0: 76.8, la0: 17.6, lo1: 78.4, la1: 19.2 };
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

function drawHatch(context, products) {
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
    const lon = AREA.lo0 + x / width * (AREA.lo1 - AREA.lo0);
    const lat = AREA.la1 - y / height * (AREA.la1 - AREA.la0);
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

export default function Map3DView({ dem, layers, products, route, waypoints, mission, sensor, mapLayer, showVerdictColors, onSegmentSelect, onUnavailable, verticalExaggeration, onExaggerationChange }) {
  const host = useRef(null); const rendererRef = useRef(null); const sceneRef = useRef(null);
  const cameraRef = useRef(null); const controlsRef = useRef(null); const contentRef = useRef(null);
  const [viewReady, setViewReady] = useState(false);

  useEffect(() => {
    let renderer; let controls; let observer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false, powerPreference: 'high-performance' });
      renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
      renderer.outputColorSpace = THREE.SRGBColorSpace;
      renderer.setClearColor('#091311', 1);
      host.current.appendChild(renderer.domElement);
      const scene = new THREE.Scene(); scene.background = new THREE.Color('#091311');
      const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 2000);
      camera.up.set(0, 0, 1);
      camera.position.set(0, -122, 100);
      const orbit = new OrbitControls(camera, renderer.domElement); controls = orbit;
      orbit.enableDamping = true; orbit.dampingFactor = 0.075; orbit.target.set(0, 0, 0); orbit.update();
      scene.add(new THREE.HemisphereLight(0xd9fff1, 0x18221d, 2));
      const sun = new THREE.DirectionalLight(0xffffff, 2.1); sun.position.set(-35, -45, 90); scene.add(sun);
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
    const renderer = rendererRef.current; const scene = sceneRef.current; const previous = contentRef.current;
    if (!renderer || !scene || !previous || !dem?.z) return undefined;
    scene.remove(previous); disposeGroup(previous);
    const group = new THREE.Group(); scene.add(group); contentRef.current = group;
    let cancelled = false;
    const meshData = demToTerrainMesh(dem, 1, 256);
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
    const terrain = new THREE.Mesh(geometry, new THREE.MeshStandardMaterial({ map: texture, roughness: 0.95, metalness: 0.02, side: THREE.DoubleSide }));
    group.add(terrain);

    const b = meshData.bounds; const mean = meshData.meanElevation;
    const metersPerUnit = meshData.metersPerUnit || ((b.la1 - b.la0) * 59150 / 100);
    const surfacePoint = (point, lift = 0.35) => {
      const [lon, lat] = point;
      const u = Math.max(0, Math.min(1, (lon - b.lo0) / (b.lo1 - b.lo0)));
      const v = Math.max(0, Math.min(1, (b.la1 - lat) / (b.la1 - b.la0)));
      const x = Math.round(u * (meshData.width - 1)); const y = Math.round(v * (meshData.height - 1));
      const height = meshData.heights[y * meshData.width + x];
      return new THREE.Vector3((u - 0.5) * meshData.worldWidth, (0.5 - v) * 100,
        ((height - mean) / metersPerUnit) + lift);
    };

    const texturePromise = (async () => {
      if (layers.basemap) {
        try {
          const response = await fetch(`/api/basemap?${encodeBox(AREA)}&layer=${encodeURIComponent(mapLayer || '')}`);
          if (response.ok) { const bitmap = await createImageBitmap(await response.blob()); context.drawImage(bitmap, 0, 0, 800, 800); bitmap.close(); }
        } catch (_error) { /* retain the local terrain color when the WMS is unavailable */ }
      }
      if (cancelled) return;
      if (layers.slope) {
        const img = await imageFromUrl(slopeCanvas(dem).toDataURL('image/png'));
        if (!cancelled) { context.globalAlpha = 0.72; context.drawImage(img, 0, 0, 800, 800); context.globalAlpha = 1; }
      }
      if (cancelled) return;
      if (layers.footprints) {
        drawHatch(context, products || []);
        context.lineWidth = 2; context.strokeStyle = '#64dfd1';
        (products || []).filter((product) => layers[product.inst]).forEach((product) => {
          const polygon = product.poly || []; if (polygon.length < 3) return;
          context.beginPath(); polygon.forEach(([lon, lat], index) => {
            const x = (lon - AREA.lo0) / (AREA.lo1 - AREA.lo0) * 800;
            const y = (AREA.la1 - lat) / (AREA.la1 - AREA.la0) * 800;
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
      const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints(route.alternate.coordinates.map((point) => surfacePoint(point, 0.2))),
        new THREE.LineDashedMaterial({ color: '#d5e1dc', dashSize: 2, gapSize: 1.2, linewidth: 1 }));
      line.computeLineDistances(); group.add(line);
    }
    if (layers.comms && waypoints?.length > 1) {
      const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints([surfacePoint(waypoints[0], 0.55), surfacePoint(waypoints.at(-1), 0.55)]),
        new THREE.LineDashedMaterial({ color: '#64dfd1', dashSize: 1, gapSize: 1 }));
      line.computeLineDistances(); group.add(line);
    }
    if (layers.stops) (waypoints || []).forEach((point, index) => {
      const marker = new THREE.Mesh(new THREE.SphereGeometry(0.9, 12, 8), new THREE.MeshStandardMaterial({ color: '#f0f8f4', emissive: '#367d6a', emissiveIntensity: 0.35 }));
      marker.position.copy(surfacePoint(point, 1)); marker.userData.segmentIndex = Math.min(index, Math.max(0, routeSegments.length - 1)); group.add(marker);
    });
    const turnSegment = routeSegments.find((segment) => segment.id === mission?.clock?.point);
    if (turnSegment?.coordinates?.length) {
      const marker = new THREE.Mesh(new THREE.OctahedronGeometry(1.4), new THREE.MeshStandardMaterial({ color: '#f4bd4f', emissive: '#7c5816', emissiveIntensity: 0.4 }));
      marker.position.copy(surfacePoint(turnSegment.coordinates.at(-1), 1.8));
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
  }, [dem, layers, products, route, waypoints, mission, mapLayer, showVerdictColors, onSegmentSelect]);

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
    h('div', { className: 'map3d-label' }, '3D is a visual aid: MOLA elevation is coarse (~463 m/px), smoothing steep local slopes. Not used in the audit.'));
}
