// Repite con web/bili/seguimiento.js los escenarios de paridad_seguimiento.py y compara cuadro a cuadro: mismos IDs, misma clase,
// misma confianza y la misma caja entera. Sale con código 1 si algo difiere.
// Uso: node scripts/movil/paridad_seguimiento.mjs seguimiento.json
import { readFileSync } from 'node:fs';

import { Seguidor, seguir } from '../../web/bili/seguimiento.js';

const { escenarios } = JSON.parse(readFileSync(process.argv[2], 'utf-8'));
let cuadros = 0, difs = 0, maxCaja = 0;
const ejemplos = [];
for (const e of escenarios) {
  const seg = new Seguidor();
  e.pasos.forEach((p, f) => {
    cuadros++;
    const dets = p.dets.map((d) => ({ ...d, label: d.cls }));
    const obtenido = seguir(seg, dets, e.ancho, e.alto).map((d) => ({ track_id: d.track_id, cls: d.label, conf: d.conf, bbox: d.bbox }));
    const crudas = seg.seguidas.filter((t) => t.activa).map((t) => t.xyxy);
    p.cajas.forEach((c, i) => { if (crudas[i]) c.forEach((v, k) => { maxCaja = Math.max(maxCaja, Math.abs(v - crudas[i][k])); }); });
    if (JSON.stringify(obtenido) !== JSON.stringify(p.esperado)) {
      difs++;
      if (ejemplos.length < 5) ejemplos.push({ origen: e.origen, cuadro: f + 1, python: p.esperado, js: obtenido });
    }
  });
}
for (const x of ejemplos) console.log(JSON.stringify(x));
console.log(`${escenarios.length} escenarios, ${cuadros} cuadros, diferencias ${difs}, máxima diferencia de caja sin redondear ${maxCaja.toExponential(2)} px`);
process.exit(difs ? 1 : 0);
