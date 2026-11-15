// Seguimiento entre cuadros (IDs): copia de ByteTrack de Ultralytics 8.4 (trackers/byte_tracker.py con bytetrack.yaml).
//
// En el servidor los IDs los da `model.track`. Aquí se copia el algoritmo paso a paso, con las mismas rarezas, para que los
// mismos cuadros den los mismos IDs (scripts/movil/paridad_seguimiento.*). Los cálculos que Ultralytics hace en float32
// (cajas de las detecciones e IoU) se redondean con Math.fround; el filtro de Kalman va en float64 como en numpy.
// No se copia la compensación de movimiento de cámara de BoT-SORT: necesita OpenCV (flujo óptico) y no cabe en el navegador.

const f32 = Math.fround;
const EPS32 = f32(1e-7);
const NUEVO = 0, SEGUIDO = 1, PERDIDO = 2, QUITADO = 3;

/** Valores de bytetrack.yaml. */
export const BYTETRACK = {
  track_high_thresh: 0.25,
  track_low_thresh: 0.1,
  new_track_thresh: 0.25,
  track_buffer: 30,
  match_thresh: 0.8,
  fuse_score: true,
};

// ---------- Filtro de Kalman (x, y, aspecto, alto y sus velocidades), KalmanFilterXYAH ----------

const W_POS = 1.0 / 20;
const W_VEL = 1.0 / 160;

function diag(v) {
  return v.map((s, i) => v.map((_, j) => (i === j ? s * s : 0)));
}

function kalmanIniciar(z) {
  const h = z[3];
  const std = [2 * W_POS * h, 2 * W_POS * h, 1e-2, 2 * W_POS * h, 10 * W_VEL * h, 10 * W_VEL * h, 1e-5, 10 * W_VEL * h];
  return { mean: [z[0], z[1], z[2], z[3], 0, 0, 0, 0], cov: diag(std) };
}

// Velocidad constante: x' = x + v. Con solo dos términos distintos de cero por suma, el resultado es el mismo que el de numpy.
function kalmanPredecir(mean, cov) {
  const h = mean[3];
  const q = diag([W_POS * h, W_POS * h, 1e-2, W_POS * h, W_VEL * h, W_VEL * h, 1e-5, W_VEL * h]);
  const m = mean.map((v, i) => (i < 4 ? v + mean[i + 4] : v));
  const fp = cov.map((fila, i) => fila.map((v, j) => (i < 4 ? v + cov[i + 4][j] : v)));   // F·P
  const c = fp.map((fila, i) => fila.map((v, j) => (j < 4 ? v + fila[j + 4] : v) + q[i][j]));   // (F·P)·Fᵀ + Q
  return { mean: m, cov: c };
}

/** Resuelve A·X = B (A de 4x4) con eliminación gaussiana y pivoteo parcial, como numpy.linalg.solve. */
function resolver(A, B) {
  const n = A.length, k = B[0].length;
  const a = A.map((f) => f.slice()), b = B.map((f) => f.slice());
  for (let c = 0; c < n; c++) {
    let p = c;
    for (let r = c + 1; r < n; r++) if (Math.abs(a[r][c]) > Math.abs(a[p][c])) p = r;
    [a[c], a[p]] = [a[p], a[c]];
    [b[c], b[p]] = [b[p], b[c]];
    for (let r = c + 1; r < n; r++) {
      const f = a[r][c] / a[c][c];
      for (let j = c; j < n; j++) a[r][j] -= f * a[c][j];
      for (let j = 0; j < k; j++) b[r][j] -= f * b[c][j];
    }
  }
  const x = Array.from({ length: n }, () => new Array(k).fill(0));
  for (let r = n - 1; r >= 0; r--) {
    for (let j = 0; j < k; j++) {
      let s = b[r][j];
      for (let c = r + 1; c < n; c++) s -= a[r][c] * x[c][j];
      x[r][j] = s / a[r][r];
    }
  }
  return x;
}

function kalmanCorregir(mean, cov, z) {
  const h = mean[3];
  const r = diag([W_POS * h, W_POS * h, 1e-1, W_POS * h]);
  const S = [0, 1, 2, 3].map((i) => [0, 1, 2, 3].map((j) => cov[i][j] + r[i][j]));
  const PHt = cov.map((fila) => fila.slice(0, 4));                                    // P·Hᵀ (8x4)
  const Kt = resolver(S, [0, 1, 2, 3].map((i) => PHt.map((fila) => fila[i])));        // Kᵀ = S⁻¹·(P·Hᵀ)ᵀ (4x8)
  const K = PHt.map((_, i) => [0, 1, 2, 3].map((j) => Kt[j][i]));                    // 8x4
  const innov = [0, 1, 2, 3].map((i) => z[i] - mean[i]);
  const m = mean.map((v, i) => v + K[i].reduce((s, kij, j) => s + innov[j] * kij, 0));
  const KS = K.map((fila) => [0, 1, 2, 3].map((j) => fila.reduce((s, kik, k) => s + kik * S[k][j], 0)));
  const c = cov.map((fila, i) => fila.map((v, j) => v - KS[i].reduce((s, x, k) => s + x * K[j][k], 0)));
  return { mean: m, cov: c };
}

// ---------- Pistas (STrack) ----------

/** tlwh en float32 -> (x centro, y centro, aspecto, alto), en float32 como `tlwh_to_xyah` sobre el arreglo de la detección. */
function xyahDe(t) {
  return [f32(t[0] + t[2] / 2), f32(t[1] + t[3] / 2), f32(t[2] / t[3]), t[3]];
}

class Pista {
  constructor(xyxy, score, cls, idx) {
    // Boxes.xywh en float32 y luego xywh2ltwh en float64 que vuelve a float32 (como en STrack.__init__)
    const [x1, y1, x2, y2] = xyxy.map(f32);
    const cx = f32(f32(x1 + x2) / 2), cy = f32(f32(y1 + y2) / 2), w = f32(x2 - x1), h = f32(y2 - y1);
    this._tlwh = [f32(cx - w / 2), f32(cy - h / 2), w, h];
    this.mean = null;
    this.cov = null;
    this.activa = false;   // is_activated
    this.estado = NUEVO;
    this.score = f32(score);
    this.cls = cls;
    this.idx = idx;
    this.trackId = 0;
    this.frame = 0;        // frame_id (= end_frame)
    this.inicio = 0;       // start_frame
    this.largo = 0;        // tracklet_len
  }

  get tlwh() {
    if (this.mean === null) return this._tlwh.slice();
    const [x, y, a, h] = this.mean;
    const w = a * h;
    return [x - w / 2, y - h / 2, w, h];
  }

  get xyxy() {
    const t = this.tlwh;
    if (this.mean === null) return [t[0], t[1], f32(t[0] + t[2]), f32(t[1] + t[3])];
    return [t[0], t[1], t[2] + t[0], t[3] + t[1]];
  }

  activar(siguienteId, frame) {
    this.trackId = siguienteId();
    ({ mean: this.mean, cov: this.cov } = kalmanIniciar(xyahDe(this._tlwh)));
    this.largo = 0;
    this.estado = SEGUIDO;
    if (frame === 1) this.activa = true;
    this.frame = frame;
    this.inicio = frame;
  }

  reactivar(det, frame) {
    ({ mean: this.mean, cov: this.cov } = kalmanCorregir(this.mean, this.cov, xyahDe(det.tlwh)));
    this.largo = 0;
    this.estado = SEGUIDO;
    this.activa = true;
    this.frame = frame;
    this.score = det.score;
    this.cls = det.cls;
    this.idx = det.idx;
  }

  actualizar(det, frame) {
    this.frame = frame;
    this.largo += 1;
    ({ mean: this.mean, cov: this.cov } = kalmanCorregir(this.mean, this.cov, xyahDe(det.tlwh)));
    this.estado = SEGUIDO;
    this.activa = true;
    this.score = det.score;
    this.cls = det.cls;
    this.idx = det.idx;
  }
}

// ---------- Asociación ----------

/** 1 - IoU entre cajas, en float32 como `matching.iou_distance` (bbox_ioa con eps 1e-7). */
function distanciaIou(as, bs) {
  const A = as.map((t) => t.xyxy.map(f32)), B = bs.map((t) => t.xyxy.map(f32));
  return A.map((a) => B.map((b) => {
    const iw = Math.max(0, f32(Math.min(a[2], b[2]) - Math.max(a[0], b[0])));
    const ih = Math.max(0, f32(Math.min(a[3], b[3]) - Math.max(a[1], b[1])));
    const inter = f32(iw * ih);
    const areaB = f32(f32(b[2] - b[0]) * f32(b[3] - b[1]));
    const areaA = f32(f32(a[2] - a[0]) * f32(a[3] - a[1]));
    const union = f32(f32(areaB + areaA) - inter);
    return f32(1 - f32(inter / f32(union + EPS32)));
  }));
}

function fusionarPuntaje(costos, dets) {
  return costos.map((fila) => fila.map((c, j) => f32(1 - f32(f32(1 - c) * dets[j].score))));
}

/**
 * Asignación de costo mínimo con límite, como `lap.lapjv(costo, extend_cost=True, cost_limit=umbral)`: se agranda la matriz con
 * filas y columnas "sin pareja" que cuestan umbral/2 cada una, así que un par solo se empareja si cuesta menos que el umbral.
 * Se resuelve con el método húngaro (óptimo, igual que lapjv salvo empates exactos).
 */
export function asignar(costos, umbral, m) {
  const n = costos.length;
  if (n === 0 || m === 0) return { pares: [], sinA: [...Array(n).keys()], sinB: [...Array(m).keys()] };
  const N = n + m;
  const c = (i, j) => (i < n && j < m ? costos[i][j] : i >= n && j >= m ? 0 : umbral / 2);
  // Húngaro con potenciales (O(N³)), índices desde 1.
  const u = new Array(N + 1).fill(0), v = new Array(N + 1).fill(0), p = new Array(N + 1).fill(0), camino = new Array(N + 1).fill(0);
  for (let i = 1; i <= N; i++) {
    p[0] = i;
    let j0 = 0;
    const minv = new Array(N + 1).fill(Infinity), usado = new Array(N + 1).fill(false);
    do {
      usado[j0] = true;
      const i0 = p[j0];
      let delta = Infinity, j1 = 0;
      for (let j = 1; j <= N; j++) {
        if (usado[j]) continue;
        const cur = c(i0 - 1, j - 1) - u[i0] - v[j];
        if (cur < minv[j]) { minv[j] = cur; camino[j] = j0; }
        if (minv[j] < delta) { delta = minv[j]; j1 = j; }
      }
      for (let j = 0; j <= N; j++) {
        if (usado[j]) { u[p[j]] += delta; v[j] -= delta; } else minv[j] -= delta;
      }
      j0 = j1;
    } while (p[j0] !== 0);
    do { const j1 = camino[j0]; p[j0] = p[j1]; j0 = j1; } while (j0);
  }
  const x = new Array(N).fill(-1);
  for (let j = 1; j <= N; j++) x[p[j] - 1] = j - 1;
  const pares = [], sinA = [], ocupadas = new Set();
  for (let i = 0; i < n; i++) {
    if (x[i] < m) { pares.push([i, x[i]]); ocupadas.add(x[i]); } else sinA.push(i);
  }
  const sinB = [...Array(m).keys()].filter((j) => !ocupadas.has(j));
  return { pares, sinA, sinB };
}

const unir = (a, b) => { const ids = new Set(a.map((t) => t.trackId)); return a.concat(b.filter((t) => !ids.has(t.trackId))); };
const restar = (a, b) => { const ids = new Set(b.map((t) => t.trackId)); return a.filter((t) => !ids.has(t.trackId)); };

function quitarRepetidas(as, bs) {
  const d = distanciaIou(as, bs);
  const dupA = new Set(), dupB = new Set();
  d.forEach((fila, p) => fila.forEach((v, q) => {
    if (!(v < 0.15)) return;
    const tp = as[p].frame - as[p].inicio, tq = bs[q].frame - bs[q].inicio;
    if (tp > tq) dupB.add(q); else dupA.add(p);
  }));
  return [as.filter((_, i) => !dupA.has(i)), bs.filter((_, i) => !dupB.has(i))];
}

// ---------- El seguidor ----------

export class Seguidor {
  constructor(config = BYTETRACK) {
    this.args = { ...BYTETRACK, ...config };
    this.reiniciar();
  }

  reiniciar() {
    this.seguidas = [];   // tracked_stracks
    this.perdidas = [];   // lost_stracks
    this.quitadas = [];   // removed_stracks (historial de hasta 1000, como Ultralytics)
    this.frame = 0;
    let n = 0;
    this.siguienteId = () => ++n;
  }

  /**
   * Un cuadro de detecciones -> pistas confirmadas en este cuadro.
   * @param {{bbox: number[], conf: number, cls?: any, label?: string}[]} dets  cajas x1, y1, x2, y2 en píxeles del cuadro
   * @returns {Pista[]} cada una con trackId, xyxy (estado del filtro), score, cls e idx (índice de la detección de entrada)
   */
  actualizar(dets) {
    const a = this.args;
    this.frame += 1;
    const activadas = [], reencontradas = [], perdidas = [], quitadas = [];

    // numpy compara el puntaje (float32) contra el umbral convertido a float32
    const alto = f32(a.track_high_thresh), bajo = f32(a.track_low_thresh), nuevo = f32(a.new_track_thresh);
    const altas = [], bajas = [];
    dets.forEach((d, i) => {
      const t = new Pista(d.bbox, d.conf, d.cls ?? d.label, i);
      if (!(t._tlwh[2] > 0 && t._tlwh[3] > 0)) return;   // una caja sin alto daría un estado infinito en el filtro
      if (t.score >= alto) altas.push(t);
      else if (t.score > bajo) bajas.push(t);
    });

    const sinConfirmar = this.seguidas.filter((t) => !t.activa);
    const confirmadas = this.seguidas.filter((t) => t.activa);
    const pool = unir(confirmadas, this.perdidas);
    for (const t of pool) {   // predicción; las que no están seguidas no cambian de tamaño
      const mean = t.mean.slice();
      if (t.estado !== SEGUIDO) mean[7] = 0;
      ({ mean: t.mean, cov: t.cov } = kalmanPredecir(mean, t.cov));
    }

    const aplicar = (t, d) => {
      if (t.estado === SEGUIDO) { t.actualizar(d, this.frame); activadas.push(t); } else { t.reactivar(d, this.frame); reencontradas.push(t); }
    };

    // 1) pistas contra detecciones de confianza alta (IoU por confianza)
    let costos = distanciaIou(pool, altas);
    if (a.fuse_score) costos = fusionarPuntaje(costos, altas);
    let r = asignar(costos, a.match_thresh, altas.length);
    for (const [i, j] of r.pares) aplicar(pool[i], altas[j]);
    let libresAltas = r.sinB;

    // 2) las que siguen sin pareja contra detecciones de confianza baja (solo IoU)
    const resto = r.sinA.map((i) => pool[i]).filter((t) => t.estado === SEGUIDO);
    let sinPareja;
    if (resto.length && bajas.length) {
      r = asignar(distanciaIou(resto, bajas), 0.5, bajas.length);
      for (const [i, j] of r.pares) aplicar(resto[i], bajas[j]);
      sinPareja = r.sinA;
    } else sinPareja = resto.map((_, i) => i);
    for (const i of sinPareja) { resto[i].estado = PERDIDO; perdidas.push(resto[i]); }

    // 3) pistas nuevas de hace un cuadro (sin confirmar) contra las detecciones altas que quedaron
    let candidatas = libresAltas.map((i) => altas[i]);
    let libres = candidatas.map((_, i) => i);
    if (sinConfirmar.length) {
      costos = distanciaIou(sinConfirmar, candidatas);
      if (a.fuse_score) costos = fusionarPuntaje(costos, candidatas);
      r = asignar(costos, 0.7, candidatas.length);
      for (const [i, j] of r.pares) { sinConfirmar[i].actualizar(candidatas[j], this.frame); activadas.push(sinConfirmar[i]); }
      for (const i of r.sinA) { sinConfirmar[i].estado = QUITADO; quitadas.push(sinConfirmar[i]); }
      libres = r.sinB;
    }

    // 4) lo que sobra con confianza suficiente abre una pista (se confirma si vuelve a aparecer en el cuadro siguiente)
    for (const i of libres) {
      const t = candidatas[i];
      if (t.score < nuevo) continue;
      t.activar(this.siguienteId, this.frame);
      activadas.push(t);
    }

    // 5) se olvidan las perdidas hace más de track_buffer cuadros
    for (const t of this.perdidas) {
      if (this.frame - t.frame > a.track_buffer) { t.estado = QUITADO; quitadas.push(t); }
    }

    // merge_track_pools
    this.seguidas = this.seguidas.filter((t) => t.estado === SEGUIDO);
    this.seguidas = unir(unir(this.seguidas, activadas), reencontradas);
    this.perdidas = restar(this.perdidas, this.seguidas).concat(perdidas);
    this.perdidas = restar(this.perdidas, this.quitadas);
    [this.seguidas, this.perdidas] = quitarRepetidas(this.seguidas, this.perdidas);
    this.quitadas = this.quitadas.concat(quitadas);
    if (this.quitadas.length > 1000) this.quitadas = this.quitadas.slice(-1000);

    return this.seguidas.filter((t) => t.activa);
  }

  /** ¿Hay pistas nuevas esperando confirmación? (Ultralytics entonces no devuelve nada en ese cuadro). */
  hayPendientes() {
    return this.seguidas.some((t) => !t.activa);
  }
}

/**
 * Lo que entrega `YoloDetector.track` en el servidor: detecciones con track_id y la caja del filtro, en enteros y recortada al
 * cuadro. Si el seguidor no devuelve nada y no hay pistas pendientes, Ultralytics deja pasar las detecciones sin ID.
 * @param {Seguidor} seguidor
 * @param {{bbox: number[], conf: number, label: string}[]} dets
 * @param {number} ancho
 * @param {number} alto
 * @param {number} desplazamiento  se suma a los IDs (dos detectores no deben compartir números)
 */
export function seguir(seguidor, dets, ancho, alto, desplazamiento = 0) {
  const recortar = ([x1, y1, x2, y2]) => [Math.max(0, Math.trunc(x1)), Math.max(0, Math.trunc(y1)), Math.min(ancho, Math.trunc(x2)), Math.min(alto, Math.trunc(y2))];
  const pistas = seguidor.actualizar(dets);
  if (pistas.length === 0) {
    if (seguidor.hayPendientes()) return [];
    return dets.map((d) => ({ track_id: null, label: d.label, conf: f32(d.conf), bbox: recortar(d.bbox.map(f32)) }));
  }
  return pistas.map((t) => ({
    track_id: t.trackId + desplazamiento,
    label: dets[t.idx].label,
    conf: t.score,
    bbox: recortar(t.xyxy.map(f32)),
  }));
}
