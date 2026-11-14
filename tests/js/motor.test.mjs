// Casos puntuales del motor del celular. La equivalencia completa con Python la cubre scripts/movil/paridad_motor.*.
import assert from 'node:assert/strict';
import { test } from 'node:test';

import { Alertas, distanciaHablada } from '../../web/bili/alertas.js';
import { conducta } from '../../web/bili/decision.js';
import { redondear } from '../../web/bili/etiquetas.js';
import { Fusion } from '../../web/bili/fusion.js';

test('redondeo como Python: al par en los empates exactos', () => {
  assert.equal(redondear(2.5), 2);
  assert.equal(redondear(3.5), 4);
  assert.equal(redondear(0.125, 2), 0.12);
  assert.equal(redondear(1.236, 2), 1.24);
});

test('1,25 m se dice "a un metro" (en Python round(2.5) = 2)', () => {
  assert.equal(distanciaHablada(1.25), 'a un metro');
  assert.equal(distanciaHablada(0.5), 'a menos de un metro');
});

test('conductas', () => {
  assert.equal(conducta('stairs', 0.3, 'P0'), 'incertidumbre');
  assert.equal(conducta('stairs', 0.3, 'P2'), 'callar');
  assert.equal(conducta('person', 0.3, 'P0'), 'callar');
});

test('QA-3: algo dudoso y cerca al frente -> "Deténgase", sin nombrar la clase, con prioridad máxima de voz', () => {
  const [d] = new Fusion().actualizar([{ track_id: 1, label: 'pothole', conf: 0.3, bbox: [200, 400, 280, 630] }], 640, 480, 0);
  assert.equal(d.conducta, 'incertidumbre');
  const [a] = new Alertas().evaluar([d], 0);
  assert.equal(a.priority, 'P0');
  assert.match(a.text, /^Deténgase/);
  assert.doesNotMatch(a.text, /hueco/);
});
