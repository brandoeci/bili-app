// Detector en el celular: geometría del letterbox y decodificación de la salida cruda de YOLO (ONNX).
//
// Módulo puro (sin DOM ni ONNX Runtime): corre igual en el navegador y en Node, para poder probarlo contra Python.
// El modelo exportado (YOLO26s, `end2end=False`) devuelve [1, 4 + clases, N]: cx, cy, w, h en píxeles de la ENTRADA y una
// puntuación por clase. Aquí se filtra por confianza, se quitan cajas repetidas (NMS por clase, como Ultralytics con
// agnostic=False) y se llevan las cajas a las coordenadas del cuadro original de la cámara.

/**
 * Cómo encajar un cuadro de srcW x srcH en la entrada del modelo (H x W) sin deformarlo: escala única y bandas grises
 * centradas. Es la misma cuenta que el LetterBox de Ultralytics (centrado; con un píxel impar, la banda de arriba/izquierda
 * es la menor). Si el relleno no es idéntico al del entrenamiento y la evaluación, las detecciones cambian (medido: con
 * otro relleno solo coincidía el 77 % de las cajas).
 */
export function letterbox(srcW, srcH, H, W) {
  const escala = Math.min(H / srcH, W / srcW);
  const w = Math.round(srcW * escala);
  const h = Math.round(srcH * escala);
  return { escala, w, h, padX: (W - w) >> 1, padY: (H - h) >> 1, H, W };
}

function iou(a, b) {
  const iw = Math.min(a.x2, b.x2) - Math.max(a.x1, b.x1);
  const ih = Math.min(a.y2, b.y2) - Math.max(a.y1, b.y1);
  if (iw <= 0 || ih <= 0) return 0;
  const inter = iw * ih;
  return inter / ((a.x2 - a.x1) * (a.y2 - a.y1) + (b.x2 - b.x1) * (b.y2 - b.y1) - inter);
}

/**
 * Salida cruda -> detecciones en coordenadas de la entrada del modelo.
 * @param {Float32Array} datos  tensor [1, 4 + nClases, N] aplanado
 * @param {number} nClases
 * @param {{conf?: number, iou?: number, claseConf?: Object<number, number>, maxDet?: number, ancho?: number, alto?: number}} op
 *   conf: umbral general; claseConf: umbral más alto por índice de clase (escaleras: 0,50); iou: umbral de NMS;
 *   ancho/alto: tamaño de la entrada; si se dan, las cajas se recortan a la imagen (como Ultralytics: un poste alto sale con y1 < 0).
 * @returns {{clase: number, conf: number, x1: number, y1: number, x2: number, y2: number}[]} ordenadas por confianza
 */
export function decodificar(datos, nClases, op = {}) {
  const conf = op.conf ?? 0.35;
  const umbralIou = op.iou ?? 0.5;
  const claseConf = op.claseConf ?? {};
  const maxDet = op.maxDet ?? 300;
  const N = datos.length / (4 + nClases);
  if (!Number.isInteger(N)) throw new Error(`tamaño de salida ${datos.length} no cuadra con ${nClases} clases`);
  const cand = [];
  for (let i = 0; i < N; i++) {
    let mejor = -1, c = 0;
    for (let k = 0; k < nClases; k++) {
      const v = datos[(4 + k) * N + i];
      if (v > mejor) { mejor = v; c = k; }
    }
    if (mejor < conf || mejor < (claseConf[c] ?? 0)) continue;
    const cx = datos[i], cy = datos[N + i], w = datos[2 * N + i], h = datos[3 * N + i];
    cand.push({ clase: c, conf: mejor, x1: cx - w / 2, y1: cy - h / 2, x2: cx + w / 2, y2: cy + h / 2 });
  }
  cand.sort((a, b) => b.conf - a.conf);
  const quedan = [];
  for (const a of cand) {
    if (quedan.length >= maxDet) break;
    if (quedan.every((b) => b.clase !== a.clase || iou(a, b) <= umbralIou)) quedan.push(a);
  }
  if (op.ancho && op.alto) {   // el recorte va DESPUÉS del NMS, como en Ultralytics
    for (const d of quedan) {
      d.x1 = Math.min(op.ancho, Math.max(0, d.x1)); d.x2 = Math.min(op.ancho, Math.max(0, d.x2));
      d.y1 = Math.min(op.alto, Math.max(0, d.y1)); d.y2 = Math.min(op.alto, Math.max(0, d.y2));
    }
  }
  return quedan;
}

/** Lleva una detección de la entrada del modelo al cuadro original, recortada a sus bordes. */
export function aCuadro(det, lb, srcW, srcH) {
  const x = (v) => Math.min(srcW, Math.max(0, (v - lb.padX) / lb.escala));
  const y = (v) => Math.min(srcH, Math.max(0, (v - lb.padY) / lb.escala));
  return { ...det, x1: x(det.x1), y1: y(det.y1), x2: x(det.x2), y2: y(det.y2) };
}
