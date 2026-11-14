// Copia de app/core/alerts.py: decide CUÁNDO hablar y QUÉ decir. Un objeto se anuncia una vez y solo se repite si aporta algo nuevo.
import { fraseDeZona, INDICE_ZONA } from './cercania.js';
import { capitalizar, labelEs, redondear } from './etiquetas.js';

const RANGO = { P0: 0, P1: 1, P2: 2, P3: 3 };
const BANDAS = [1.2, 2.5, 4.5];
const NUMEROS = { 1: 'un', 2: 'dos', 3: 'tres', 4: 'cuatro', 5: 'cinco', 6: 'seis', 7: 'siete', 8: 'ocho', 9: 'nueve', 10: 'diez' };
const OLVIDAR_S = 3.0;

const banda = (d) => { const i = BANDAS.findIndex((b) => d < b); return i < 0 ? BANDAS.length : i; };
const bandaDe = (det) => (det.zone != null ? INDICE_ZONA[det.zone] : banda(det.distance_m ?? 99));

export function distanciaHablada(d) {
  if (d < 0.8) return 'a menos de un metro';
  const medios = redondear(d * 2) / 2;
  const entero = Math.trunc(medios);
  if (medios > 10) return 'a más de diez metros';
  if (medios === 1) return 'a un metro';
  if (medios === 1.5) return 'a metro y medio';
  if (medios === entero) return `a ${NUMEROS[entero]} metros`;
  return `a ${NUMEROS[entero]} metros y medio`;
}

export function frase(det, razon = 'new') {
  const lado = { left: 'a su izquierda', right: 'a su derecha' }[det.direction] ?? 'al frente';
  if (det.conducta === 'incertidumbre') return `Deténgase: hay algo ${lado} y no estoy seguro de qué es`;
  const nombre = labelEs(det.label);
  const dist = fraseDeZona(det.zone) ?? (det.distance_m != null ? distanciaHablada(det.distance_m) : '');
  const acerca = (det.ttc_s != null && det.ttc_s < 4.0) || (det.approach_speed_mps || 0) > 0.6;
  const cola = acerca ? ', se acerca' : '';
  const nota = det.note && razon !== 'reminder' ? `. ${det.note}` : '';
  if (razon === 'reminder') return `Sigue ${nombre} ${lado}, ${dist}`.trim();
  if (razon === 'closer') return `${capitalizar(nombre)} ${lado}, ahora ${dist}${cola}${nota}`;
  if (det.priority === 'P0') return `Cuidado: ${nombre} ${lado}, ${dist}${cola}${nota}`;
  return `${capitalizar(nombre)} ${lado}, ${dist}${cola}${nota}`;
}

export class Alertas {
  constructor({ cooldown = 4.0, minFrames = 1, maxHabla = 1.5, recordatorio = 12.0 } = {}) {
    this.cooldown = cooldown;
    this.minFrames = Math.max(1, minFrames);
    this.maxHabla = maxHabla;
    this.recordatorio = recordatorio;
    this.memoria = new Map();
    this.ultimaVez = -1e9;
  }

  /** @returns {{priority, text, track_id, conducta, label, conf, razon}[]} */
  evaluar(detecciones, ahora) {
    for (const [k, m] of this.memoria) if (ahora - m.ultimaVista >= OLVIDAR_S) this.memoria.delete(k);
    const cand = [];
    for (const det of detecciones) {
      if (det.distance_m == null || det.priority === 'P3' || det.conducta === 'callar') continue;
      const clave = det.track_id != null ? `t${det.track_id}` : `${det.label}|${det.direction}`;
      let m = this.memoria.get(clave);
      if (!m) { m = { primera: ahora, ultimaVista: ahora, frames: 1, avisadoEn: null, banda: 99, direccion: '', prioridad: 'P3', conducta: null }; this.memoria.set(clave, m); }
      else { m.frames += 1; m.ultimaVista = ahora; }
      const razon = this.debeAvisar(det, m, ahora);
      if (razon) cand.push({ rango: RANGO[det.priority], dist: det.distance_m, det, razon, m });
    }
    cand.sort((a, b) => a.rango - b.rango || a.dist - b.dist);   // estable, como sorted() de Python
    const out = [];
    for (const { rango, det, razon, m } of cand.slice(0, 2)) {
      if (rango > 0 && ahora - this.ultimaVez < this.maxHabla) continue;
      if (rango > 1 && out.length) continue;
      out.push({ priority: det.conducta === 'incertidumbre' ? 'P0' : det.priority, text: frase(det, razon), track_id: det.track_id,
                 conducta: det.conducta, label: det.label, conf: det.conf, razon });
      Object.assign(m, { avisadoEn: ahora, banda: bandaDe(det), direccion: det.direction, prioridad: det.priority, conducta: det.conducta });
      this.ultimaVez = ahora;
    }
    return out;
  }

  debeAvisar(det, m, ahora) {
    if (det.priority !== 'P0' && m.frames < this.minFrames) return null;
    const b = bandaDe(det);
    if (m.avisadoEn == null) return 'new';
    const desde = ahora - m.avisadoEn;
    const d = det.distance_m || 99;
    if (det.zone != null) { if (b > m.banda) m.banda = b; }
    else if (m.banda < BANDAS.length && d > BANDAS[m.banda] * 1.25) m.banda = b;
    if (m.conducta === 'incertidumbre' && det.conducta === 'avisar' && desde >= 1.0) return 'confirmed';
    if (RANGO[det.priority] < RANGO[m.prioridad] && desde >= 1.0) return 'escalated';
    if (b < m.banda && desde >= 1.0) return 'closer';
    if (det.ttc_s != null && det.ttc_s < 3.0 && desde >= 2.0) return 'approaching';
    if (det.direction !== m.direccion && desde >= this.cooldown) return 'moved';
    if (det.priority === 'P0' && desde >= this.recordatorio) return 'reminder';
    return null;
  }
}
