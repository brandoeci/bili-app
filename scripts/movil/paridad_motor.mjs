// Repite con web/bili/ los escenarios que generó paridad_motor.py y compara cuadro por cuadro. Sale con 0 solo si todo coincide.
// Uso: node scripts/movil/paridad_motor.mjs motor.json
import { readFileSync } from 'node:fs';

import { Alertas } from '../../web/bili/alertas.js';
import { Fusion } from '../../web/bili/fusion.js';

const datos = JSON.parse(readFileSync(process.argv[2], 'utf8'));
const CAMPOS = ['track_id', 'direction', 'distance_m', 'approach_speed_mps', 'ttc_s', 'priority', 'zone', 'conducta'];
let cuadros = 0, dets = 0, alertas = 0, fallos = 0;
const muestra = [];
datos.escenarios.forEach((pasos, e) => {
  const fusion = new Fusion({ focal: datos.focal });
  const al = new Alertas(datos.alertas);
  for (const p of pasos) {
    cuadros++;
    const fus = fusion.actualizar(p.crudas, datos.alto, datos.ancho, p.t);
    const avisos = al.evaluar(fus, p.t);
    fus.forEach((d, i) => {
      dets++;
      for (const c of CAMPOS) {
        if (d[c] !== p.fusion[i][c]) { fallos++; if (muestra.length < 8) muestra.push(`esc ${e} t=${p.t} det ${i} ${c}: py=${p.fusion[i][c]} js=${d[c]}`); }
      }
    });
    alertas += p.alertas.length;
    const a = avisos.map((x) => `${x.priority}|${x.track_id}|${x.text}`).join(' // ');
    const b = p.alertas.map((x) => `${x.priority}|${x.track_id}|${x.text}`).join(' // ');
    if (a !== b) { fallos++; if (muestra.length < 8) muestra.push(`esc ${e} t=${p.t} alertas:\n   py: ${b}\n   js: ${a}`); }
  }
});
muestra.forEach((m) => console.log('DIFERENCIA', m));
console.log(`escenarios ${datos.escenarios.length} | cuadros ${cuadros} | detecciones ${dets} | alertas ${alertas} | diferencias ${fallos}`);
process.exit(fallos ? 1 : 0);
