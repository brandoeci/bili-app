// Casos puntuales del seguimiento del celular. La equivalencia con Ultralytics la cubre scripts/movil/paridad_seguimiento.*.
import assert from 'node:assert/strict';
import { test } from 'node:test';

import { Seguidor, asignar, seguir } from '../../web/bili/seguimiento.js';

const poste = (dx = 0, conf = 0.6) => ({ label: 'pole', conf, bbox: [200 + dx, 100, 240 + dx, 500] });

test('asignación: empareja lo barato y deja sin pareja lo que cuesta más que el umbral', () => {
  const r = asignar([[0.1, 0.9], [0.95, 0.85]], 0.8, 2);
  assert.deepEqual(r.pares, [[0, 0]]);
  assert.deepEqual(r.sinA, [1]);
  assert.deepEqual(r.sinB, [1]);
  assert.deepEqual(asignar([], 0.8, 3).sinB, [0, 1, 2]);
});

test('un poste quieto conserva su ID cuadro a cuadro', () => {
  const s = new Seguidor();
  const ids = [0, 1, 2, 3, 4, 5].map((i) => seguir(s, [poste(i % 2)], 480, 640)[0].track_id);
  assert.deepEqual(new Set(ids), new Set([1]));
});

test('un objeto nuevo (después del primer cuadro) se anuncia desde su segundo cuadro', () => {
  const s = new Seguidor();
  seguir(s, [poste()], 480, 640);
  const otro = { label: 'curb', conf: 0.7, bbox: [10, 560, 300, 620] };
  assert.equal(seguir(s, [poste(), otro], 480, 640).length, 1);   // pendiente de confirmar
  assert.deepEqual(seguir(s, [poste(), otro], 480, 640).map((d) => d.track_id).sort(), [1, 2]);
});

test('tras taparse unos cuadros, vuelve con el mismo ID', () => {
  const s = new Seguidor();
  for (let i = 0; i < 5; i++) seguir(s, [poste()], 480, 640);
  for (let i = 0; i < 10; i++) seguir(s, [], 480, 640);
  assert.equal(seguir(s, [poste()], 480, 640)[0].track_id, 1);
});

test('dos detectores no comparten números de ID', () => {
  const s = new Seguidor();
  assert.equal(seguir(s, [poste()], 480, 640, 100000)[0].track_id, 100001);
});
