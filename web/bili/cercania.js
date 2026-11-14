// Copia de app/core/proximity.py: zonas de cercanía sobre la distancia ESTIMADA (muy_cerca, urgente, aviso, lejos), con histéresis.
import { GROUND } from './etiquetas.js';

export const ZONAS = ['muy_cerca', 'urgente', 'aviso', 'lejos'];
export const INDICE_ZONA = Object.fromEntries(ZONAS.map((z, i) => [z, i]));

export const CERCANIA_POR_DEFECTO = {
  size: { near: 1.5, urgent: 2.0, warn: 3.5 },
  ground: { near: 2.1, urgent: 3.0, warn: 5.0 },
  hysteresis: 1.15,
};

export function zona(label, distancia, anterior = null, cfg = CERCANIA_POR_DEFECTO) {
  const t = GROUND.has(label) ? cfg.ground : cfg.size;
  const bordes = [t.near, t.urgent, t.warn];
  let i = bordes.findIndex((b) => distancia < b);
  if (i < 0) i = bordes.length;
  if (anterior in INDICE_ZONA) {
    const prev = INDICE_ZONA[anterior];
    if (i > prev && prev < bordes.length && distancia < bordes[prev] * cfg.hysteresis) i = prev;
  }
  return ZONAS[i];
}

export function fraseDeZona(z) {
  return { muy_cerca: 'muy cerca', urgente: 'a menos de dos metros' }[z] ?? null;
}
