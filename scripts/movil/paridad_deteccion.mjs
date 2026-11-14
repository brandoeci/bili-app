// Compara web/bili/deteccion.js con Ultralytics sobre las salidas crudas que deja paridad_deteccion.py.
// Uso: node scripts/movil/paridad_deteccion.mjs CARPETA
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { decodificar } from '../../web/bili/deteccion.js';

const dir = process.argv[2];
const meta = JSON.parse(readFileSync(join(dir, 'casos.json'), 'utf8'));
const claseConf = Object.fromEntries(Object.entries(meta.claseConf).map(([k, v]) => [Number(k), v]));

const iou = (a, b) => {
  const iw = Math.min(a[2], b[2]) - Math.max(a[0], b[0]), ih = Math.min(a[3], b[3]) - Math.max(a[1], b[1]);
  if (iw <= 0 || ih <= 0) return 0;
  const i = iw * ih;
  return i / ((a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - i);
};

let ref = 0, js = 0, iguales = 0, maxDifConf = 0, peorIou = 1, cuadrosDistintos = 0;
for (const c of meta.casos) {
  const buf = readFileSync(join(dir, c.crudo));
  const datos = new Float32Array(buf.buffer, buf.byteOffset, buf.byteLength / 4);
  const nuestras = decodificar(datos, meta.nClases, { conf: meta.conf, iou: meta.iou, claseConf, alto: meta.entrada[0], ancho: meta.entrada[1] });
  ref += c.referencia.length; js += nuestras.length;
  const usadas = new Set();
  let aciertos = 0;
  for (const r of c.referencia) {
    let mejor = -1, mejorIou = 0;
    nuestras.forEach((n, j) => {
      if (usadas.has(j) || n.clase !== r.clase) return;
      const v = iou(r.caja, [n.x1, n.y1, n.x2, n.y2]);
      if (v > mejorIou) { mejorIou = v; mejor = j; }
    });
    if (mejor >= 0 && mejorIou >= 0.99) {
      usadas.add(mejor); aciertos++;
      maxDifConf = Math.max(maxDifConf, Math.abs(nuestras[mejor].conf - r.conf));
      peorIou = Math.min(peorIou, mejorIou);
    }
  }
  iguales += aciertos;
  if (aciertos !== c.referencia.length || nuestras.length !== c.referencia.length) {
    cuadrosDistintos++;
    console.log(`DISTINTO ${c.cuadro}: referencia ${c.referencia.length}, js ${nuestras.length}, iguales ${aciertos}`);
  }
}
console.log(`cuadros ${meta.casos.length} | detecciones referencia ${ref} | js ${js} | iguales (misma clase, IoU>=0,99) ${iguales}`);
console.log(`peor IoU entre iguales ${peorIou.toFixed(4)} | máxima diferencia de confianza ${maxDifConf.toExponential(2)} | cuadros con diferencias ${cuadrosDistintos}`);
process.exit(cuadrosDistintos === 0 && ref === js ? 0 : 1);
