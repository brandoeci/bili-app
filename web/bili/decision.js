// Copia de app/core/decision.py: avisar / incertidumbre (QA-3: "deténgase" sin nombrar la clase) / callar.

// clase -> [bajo, alto], medidos con el v7a (scripts/movil/umbrales_abstencion.py)
export const UMBRALES = {
  pothole: [0.25, 0.50],
  curb: [0.50, 0.50],   // B: sin banda dudosa (28 de 43 "deténgase" del recorrido propio eran bordillos dudosos)
  stairs: [0.25, 0.50],
  pole: [0.30, 0.40],
  obstacle: [0.25, 0.40],
  manhole: [0.35, 0.35],
};

export const normalizar = (label) => (label.toLowerCase().startsWith('stairs') ? 'stairs' : label.toLowerCase());

export function umbrales(label, tabla = UMBRALES, porDefecto = 0.35) {
  return tabla[normalizar(label)] ?? [porDefecto, porDefecto];
}

// A: "deténgase" solo si lo dudoso está al frente; a un lado se calla.
export function conducta(label, conf, prioridad, tabla = UMBRALES, porDefecto = 0.35, direccion = 'center') {
  if (prioridad === 'P3') return 'callar';
  const [bajo, alto] = umbrales(label, tabla, porDefecto);
  if (conf >= alto) return 'avisar';
  if (conf >= bajo && (prioridad === 'P0' || prioridad === 'P1') && direccion === 'center') return 'incertidumbre';
  return 'callar';
}

export const confianzaMinima = (tabla = UMBRALES) => Math.min(...Object.values(tabla).map(([b]) => b));
