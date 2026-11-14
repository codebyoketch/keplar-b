export function demToTerrainMesh(dem, verticalExaggeration = 3, maxDimension = 256) {
  if (!dem?.z || !dem?.w || !dem?.h || !dem?.b) throw new Error('A decoded DEM is required for 3D terrain.');
  const sourceWidth = Number(dem.w);
  const sourceHeight = Number(dem.h);
  if (!Number.isInteger(sourceWidth) || !Number.isInteger(sourceHeight) || sourceWidth < 2 || sourceHeight < 2) {
    throw new Error('DEM dimensions must be integers of at least 2 × 2.');
  }
  const binary = atob(dem.z);
  if (binary.length !== sourceWidth * sourceHeight * 4) throw new Error('DEM dimensions do not match its elevation payload.');
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
  const view = new DataView(bytes.buffer);
  const source = new Float32Array(sourceWidth * sourceHeight);
  let sum = 0; let count = 0;
  for (let i = 0; i < source.length; i += 1) {
    const value = view.getFloat32(i * 4, true);
    source[i] = value;
    if (Number.isFinite(value)) { sum += value; count += 1; }
  }
  if (!count) throw new Error('DEM contains no finite elevations.');
  const mean = sum / count;
  const width = Math.min(sourceWidth, maxDimension);
  const height = Math.min(sourceHeight, maxDimension);
  const bounds = dem.b;
  const midLat = (Number(bounds.la0) + Number(bounds.la1)) / 2;
  // Keep a stable world scale (1 Three.js unit = 1 km) so zooming and
  // wider DEM extents show the correct change in apparent feature size.
  const metersPerUnit = 1000;
  const worldHeight = (Number(bounds.la1) - Number(bounds.la0)) * 59.15;
  const worldWidth = (Number(bounds.lo1) - Number(bounds.lo0)) * 59.15 * Math.cos(midLat * Math.PI / 180);
  const positions = new Float32Array(width * height * 3);
  const heights = new Float32Array(width * height);
  let minHeight = Infinity; let maxHeight = -Infinity;
  for (let y = 0; y < height; y += 1) {
    const sy = Math.round(y * (sourceHeight - 1) / Math.max(height - 1, 1));
    for (let x = 0; x < width; x += 1) {
      const sx = Math.round(x * (sourceWidth - 1) / Math.max(width - 1, 1));
      const raw = source[sy * sourceWidth + sx];
      const elevation = Number.isFinite(raw) ? raw : mean;
      const i = y * width + x;
      heights[i] = elevation;
      minHeight = Math.min(minHeight, elevation); maxHeight = Math.max(maxHeight, elevation);
      positions[i * 3] = (x / (width - 1) - 0.5) * worldWidth;
      positions[i * 3 + 1] = (0.5 - y / (height - 1)) * worldHeight;
      positions[i * 3 + 2] = ((elevation - mean) / metersPerUnit) * Number(verticalExaggeration);
    }
  }
  const indices = new Uint32Array((width - 1) * (height - 1) * 6);
  let index = 0;
  for (let y = 0; y < height - 1; y += 1) {
    for (let x = 0; x < width - 1; x += 1) {
      const a = y * width + x; const b = a + 1; const c = a + width; const d = c + 1;
      indices[index++] = a; indices[index++] = c; indices[index++] = b;
      indices[index++] = b; indices[index++] = c; indices[index++] = d;
    }
  }
  return { width, height, positions, heights, indices, bounds, meanElevation: mean, minHeight, maxHeight, worldWidth, worldHeight, metersPerUnit };
}
