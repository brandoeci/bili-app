// Copia de app/core/fusion.py para el celular (sin mapa de profundidad: el celular no corre ese modelo).
// Detección cruda {track_id, label, conf, bbox:[x1,y1,x2,y2]} -> dirección, distancia suavizada, velocidad, TTC, zona, prioridad y conducta.
import { CERCANIA_POR_DEFECTO, zona as calcularZona } from './cercania.js';
import { conducta as decidir, UMBRALES } from './decision.js';
import { GROUND, HAZARDS, MOVING, REAL_HEIGHT_M, REAL_WIDTH_M, VEHICLES, redondear } from './etiquetas.js';

const ALTURA_CAMARA_M = 1.3, SUELO_LEJOS_M = 10.0, ALTURA_POR_DEFECTO_M = 0.7, FACTOR_BASE_CORTADA = 0.5;
const EMA = 0.5, VIDA_TRACK_S = 2.0;

export class Fusion {
  constructor({ focal = 0.8, cercania = CERCANIA_POR_DEFECTO, decision = UMBRALES, decidirConducta = true } = {}) {
    this.focal = focal;
    this.cercania = cercania;
    this.decision = decision;
    this.decidirConducta = decidirConducta;
    this.tracks = new Map();
  }

  /** @param ahora segundos (monótonos). @returns detecciones fusionadas, mismas claves que app.schemas.Detection */
  actualizar(crudas, alto, ancho, ahora) {
    for (const [k, t] of this.tracks) if (ahora - t.ts >= VIDA_TRACK_S) this.tracks.delete(k);
    return crudas.map((d) => {
      const [x1, , x2] = d.bbox;
      const px = (x1 + x2) / 2 / Math.max(ancho, 1);
      const direction = px < 0.33 ? 'left' : px > 0.66 ? 'right' : 'center';
      const label = d.label.toLowerCase();
      let distancia = GROUND.has(label) ? this.distanciaSuelo(d.bbox, ancho, alto) : this.distanciaCaja(label, d.bbox, ancho, alto);
      let velocidad = null, ttc = null;
      const prev = d.track_id != null ? this.tracks.get(d.track_id) : undefined;
      if (prev) {
        distancia = EMA * distancia + (1 - EMA) * prev.distancia;
        const dt = Math.max(1e-3, ahora - prev.ts);
        velocidad = EMA * ((prev.distancia - distancia) / dt) + (1 - EMA) * prev.velocidad;
        ttc = velocidad > 0.3 ? distancia / velocidad : null;
      }
      const z = calcularZona(label, distancia, prev ? prev.zona : null, this.cercania);
      if (d.track_id != null) this.tracks.set(d.track_id, { distancia, velocidad: velocidad || 0, ts: ahora, zona: z });
      const priority = Fusion.prioridad(label, distancia, direction, ttc, z);
      return {
        track_id: d.track_id ?? null, label, conf: d.conf, bbox: d.bbox, direction,
        clock: { left: 10, center: 12, right: 2 }[direction],
        distance_m: redondear(distancia, 2),
        approach_speed_mps: velocidad == null ? null : redondear(velocidad, 2),
        ttc_s: ttc == null ? null : redondear(ttc, 1),
        priority, zone: z,
        conducta: this.decidirConducta ? decidir(label, d.conf, priority, this.decision) : null,
        note: null,
      };
    });
  }

  distanciaCaja(label, [x1, y1, x2, y2], w, h) {
    const focal = this.focal * w;
    const porAlto = (REAL_HEIGHT_M[label] ?? ALTURA_POR_DEFECTO_M) * focal / Math.max(1, y2 - y1);
    const anchoReal = REAL_WIDTH_M[label];
    const porAncho = anchoReal ? anchoReal * focal / Math.max(1, x2 - x1) : null;
    const cortadaV = y1 <= 2 || y2 >= h - 2;
    const cortadaH = x1 <= 2 || x2 >= w - 2;
    let d;
    if (porAncho == null || (cortadaH && !cortadaV)) d = porAlto;
    else if (cortadaV && !cortadaH) d = porAncho;
    else if (cortadaV && cortadaH) d = Math.min(porAlto, porAncho);
    else d = porAlto;
    return Math.max(0.3, d);
  }

  distanciaSuelo(bbox, w, h) {
    const bajo = bbox[3] - h / 2;
    if (bajo < 2) return SUELO_LEJOS_M;
    const d = Math.min(SUELO_LEJOS_M, Math.max(0.3, ALTURA_CAMARA_M * this.focal * w / bajo));
    return bbox[3] >= h - 2 ? Math.max(0.3, d * FACTOR_BASE_CORTADA) : d;
  }

  static prioridad(label, distancia, direccion, ttc = null, zona = null) {
    const base = Fusion.prioridadBase(label, distancia, direccion, ttc);
    if (zona == null || label === 'manhole') return base;
    const enCamino = direccion === 'center';
    let piso = 'P3';
    if (zona === 'muy_cerca') {
      const critico = HAZARDS.has(label) || MOVING.has(label) || GROUND.has(label);
      if (HAZARDS.has(label) || (enCamino && critico)) piso = 'P0';
      else if (enCamino || MOVING.has(label)) piso = 'P1';
    } else if (zona === 'urgente' && enCamino) piso = 'P1';
    return base < piso ? base : piso;
  }

  static prioridadBase(label, d, direccion, ttc = null) {
    const enCamino = direccion === 'center';
    if (ttc != null && ttc < 2.5 && (MOVING.has(label) || HAZARDS.has(label))) return 'P0';
    if (VEHICLES.has(label)) {
      if (d < 3 || (enCamino && d < 5)) return d < 3 ? 'P0' : 'P1';
      return d < 8 ? 'P2' : 'P3';
    }
    if (label === 'manhole') return 'P3';
    if (label === 'pothole') return d < 4.0 ? 'P0' : d < 6.0 ? 'P1' : 'P2';
    if (HAZARDS.has(label)) return d < 2.5 ? 'P0' : d < 5 ? 'P1' : 'P2';
    if (MOVING.has(label)) {
      if (d < 1.2 && enCamino) return 'P0';
      if (d < 2 || (enCamino && d < 3)) return 'P1';
      return d < 5 ? 'P2' : 'P3';
    }
    if (enCamino && d < 1.5) return 'P1';
    if (enCamino && d < 3) return 'P2';
    return 'P3';
  }
}
