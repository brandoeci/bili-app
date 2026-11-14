// Copia de app/core/labels.py para el celular. Si cambia allá, cambia aquí: la prueba de paridad (scripts/movil/paridad_motor.*) lo detecta.

export const LABELS_ES = {
  'person': 'persona', 'car': 'carro', 'truck': 'camión', 'bus': 'bus', 'motorcycle': 'motocicleta', 'bicycle': 'bicicleta',
  'chair': 'silla', 'bench': 'banca', 'couch': 'sofá', 'bed': 'cama', 'dining table': 'mesa', 'potted plant': 'matera',
  'dog': 'perro', 'cat': 'gato', 'horse': 'caballo', 'traffic light': 'semáforo', 'stop sign': 'señal de pare',
  'fire hydrant': 'hidrante', 'parking meter': 'parquímetro', 'backpack': 'mochila', 'suitcase': 'maleta', 'umbrella': 'paraguas',
  'bottle': 'botella', 'cell phone': 'teléfono', 'laptop': 'computador', 'tv': 'televisor', 'toilet': 'inodoro', 'sink': 'lavamanos',
  'refrigerator': 'nevera', 'skateboard': 'patineta', 'obstacle': 'obstáculo', 'drop': 'desnivel hacia abajo', 'stairs': 'escaleras',
  'stairs_up': 'escaleras que suben', 'stairs_down': 'escaleras que bajan', 'step_up': 'escalón hacia arriba', 'wall': 'pared',
  'door': 'puerta', 'pothole': 'hueco', 'manhole': 'tapa de alcantarilla', 'curb': 'bordillo', 'pole': 'poste',
};

export const REAL_HEIGHT_M = {
  'person': 1.7, 'car': 1.5, 'truck': 3.0, 'bus': 3.0, 'motorcycle': 1.2, 'bicycle': 1.0, 'chair': 0.9, 'bench': 0.8, 'couch': 0.9,
  'bed': 0.6, 'dining table': 0.75, 'potted plant': 0.6, 'dog': 0.5, 'cat': 0.3, 'horse': 1.6, 'traffic light': 0.9, 'stop sign': 0.75,
  'fire hydrant': 0.7, 'suitcase': 0.6, 'backpack': 0.45, 'door': 2.0, 'tv': 0.5, 'refrigerator': 1.7, 'umbrella': 0.9, 'skateboard': 0.12,
  'laptop': 0.28, 'cell phone': 0.15, 'bottle': 0.25, 'parking meter': 1.3, 'toilet': 0.7, 'sink': 0.3,
};

export const REAL_WIDTH_M = {
  'person': 0.5, 'car': 1.8, 'truck': 2.4, 'bus': 2.5, 'motorcycle': 0.8, 'bicycle': 0.6, 'chair': 0.5, 'bench': 1.5, 'couch': 1.8, 'dog': 0.35,
};

export const VEHICLES = new Set(['car', 'truck', 'bus', 'motorcycle', 'bicycle']);
export const MOVING = new Set([...VEHICLES, 'person', 'dog', 'cat', 'horse', 'skateboard']);
export const HAZARDS = new Set(['obstacle', 'drop', 'stairs', 'stairs_up', 'stairs_down', 'step_up', 'wall', 'pothole', 'curb']);
export const GROUND = new Set(['pothole', 'manhole', 'curb', 'pole', 'obstacle', 'drop', 'wall', 'stairs', 'stairs_up', 'stairs_down', 'step_up']);

export function labelEs(label) {
  const k = label.toLowerCase();
  return LABELS_ES[k] || LABELS_ES[k.replaceAll('_', ' ')] || k.replaceAll('_', ' ');
}

/** Igual que str.capitalize() de Python: primera en mayúscula, el resto en minúscula. */
export function capitalizar(s) {
  return s ? s[0].toUpperCase() + s.slice(1).toLowerCase() : s;
}

/** round() de Python: redondeo al par en los empates exactos (round(2.5) = 2). En JS, Math.round(2.5) = 3: sin esto cambian frases. */
export function redondear(x, decimales = 0) {
  const m = 10 ** decimales;
  const y = x * m;
  const frac = y - Math.floor(y);
  if (frac === 0.5) {
    const abajo = Math.floor(y);
    return (abajo % 2 === 0 ? abajo : abajo + 1) / m;
  }
  return decimales === 0 ? Math.round(y) : Number(x.toFixed(decimales));
}
