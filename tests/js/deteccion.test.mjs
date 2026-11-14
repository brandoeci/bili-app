// node --test tests/js
import assert from 'node:assert/strict';
import { test } from 'node:test';

import { aCuadro, decodificar, letterbox } from '../../web/bili/deteccion.js';

/** Arma una salida cruda [1, 4 + nc, N] a partir de cajas {cx, cy, w, h, puntajes: [...]} */
function salida(cajas, nc) {
  const N = cajas.length;
  const d = new Float32Array((4 + nc) * N);
  cajas.forEach((c, i) => {
    d[i] = c.cx; d[N + i] = c.cy; d[2 * N + i] = c.w; d[3 * N + i] = c.h;
    c.puntajes.forEach((p, k) => { d[(4 + k) * N + i] = p; });
  });
  return d;
}

test('letterbox de la cámara vertical 720x1280 a 480x640: bandas a los lados', () => {
  const lb = letterbox(720, 1280, 640, 480);
  assert.equal(lb.escala, 0.5);
  assert.deepEqual([lb.w, lb.h, lb.padX, lb.padY], [360, 640, 60, 0]);
});

test('letterbox con sobrante impar: la banda de arriba es la menor (como Ultralytics)', () => {
  const lb = letterbox(480, 635, 640, 480);
  assert.deepEqual([lb.padY, 640 - lb.h - lb.padY], [2, 3]);
});

test('sin bandas cuando el cuadro ya tiene la forma de la entrada', () => {
  const lb = letterbox(480, 640, 640, 480);
  assert.deepEqual([lb.escala, lb.padX, lb.padY], [1, 0, 0]);
});

test('filtra por confianza y se queda con la mejor clase de cada caja', () => {
  const d = salida([
    { cx: 100, cy: 100, w: 20, h: 40, puntajes: [0.1, 0.8, 0.2] },
    { cx: 300, cy: 300, w: 20, h: 40, puntajes: [0.3, 0.1, 0.2] },
  ], 3);
  const r = decodificar(d, 3, { conf: 0.35 });
  assert.equal(r.length, 1);
  assert.equal(r[0].clase, 1);
  assert.ok(Math.abs(r[0].conf - 0.8) < 1e-6);
  assert.deepEqual([r[0].x1, r[0].y1, r[0].x2, r[0].y2], [90, 80, 110, 120]);
});

test('NMS por clase: quita la repetida de la misma clase, conserva la de otra clase encima', () => {
  const d = salida([
    { cx: 100, cy: 100, w: 40, h: 40, puntajes: [0.9, 0] },
    { cx: 102, cy: 101, w: 40, h: 40, puntajes: [0.7, 0] },   // misma clase, casi igual: fuera
    { cx: 101, cy: 100, w: 40, h: 40, puntajes: [0, 0.6] },   // otra clase en el mismo sitio: se queda
  ], 2);
  const r = decodificar(d, 2, { conf: 0.35, iou: 0.5 });
  assert.deepEqual(r.map((x) => x.clase), [0, 1]);
});

test('umbral más alto por clase (escaleras a 0,50)', () => {
  const d = salida([
    { cx: 100, cy: 100, w: 40, h: 40, puntajes: [0, 0, 0, 0.45] },
    { cx: 300, cy: 300, w: 40, h: 40, puntajes: [0, 0, 0, 0.55] },
  ], 4);
  const r = decodificar(d, 4, { conf: 0.35, claseConf: { 3: 0.5 } });
  assert.equal(r.length, 1);
  assert.ok(r[0].conf > 0.5);
});

test('con el tamaño de la entrada, una caja que se sale queda recortada (después del NMS)', () => {
  const d = salida([{ cx: 270, cy: 84, w: 10, h: 188, puntajes: [0.46] }], 1);   // y1 = -10, como un poste alto
  const r = decodificar(d, 1, { conf: 0.35, ancho: 480, alto: 640 });
  assert.equal(r[0].y1, 0);
  assert.equal(decodificar(d, 1, { conf: 0.35 })[0].y1, -10);   // sin tamaño, no se toca
});

test('una salida que no cuadra con el número de clases es un error, no una lista vacía', () => {
  assert.throws(() => decodificar(new Float32Array(11), 6));
});

test('vuelta al cuadro original: quita la banda y deshace la escala, recortando al borde', () => {
  const lb = letterbox(720, 1280, 640, 480);
  const c = aCuadro({ clase: 0, conf: 1, x1: 50, y1: 10, x2: 160, y2: 650 }, lb, 720, 1280);
  assert.deepEqual([c.x1, c.y1, c.x2, c.y2], [0, 20, 200, 1280]);
});
