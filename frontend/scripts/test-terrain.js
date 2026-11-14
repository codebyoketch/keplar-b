import assert from 'node:assert/strict';
import { demToTerrainMesh } from '../src/terrain.js';

function payload(width, height, values) {
  const bytes = new Uint8Array(values.length * 4);
  const view = new DataView(bytes.buffer);
  values.forEach((value, index) => view.setFloat32(index * 4, value, true));
  let binary = '';
  bytes.forEach((byte) => { binary += String.fromCharCode(byte); });
  return { w: width, h: height, z: btoa(binary), b: { lo0: 76, la0: 17, lo1: 78, la1: 19 } };
}

const tiny = demToTerrainMesh(payload(3, 2, [1, 2, 3, 4, Number.NaN, 6]));
assert.equal(tiny.width, 3);
assert.equal(tiny.height, 2);
assert.equal(tiny.positions.length, 3 * 2 * 3);
assert.equal(tiny.indices.length, (3 - 1) * (2 - 1) * 6);
assert.ok([...tiny.heights].every(Number.isFinite), 'all mesh elevations must be finite');
assert.ok([...tiny.positions].every(Number.isFinite), 'all mesh positions must be finite');

const values = Array.from({ length: 300 * 280 }, (_, index) => index % 173);
const capped = demToTerrainMesh(payload(300, 280, values));
assert.equal(capped.width, 256);
assert.equal(capped.height, 256);
assert.ok(capped.width * capped.height <= 256 * 256, 'mesh must stay within the vertex budget');
assert.ok([...capped.heights].every(Number.isFinite));
console.log('DEM-to-mesh checks passed (finite heights, correct dimensions, 256 × 256 cap).');
