/* Seguimiento de ruta a pie. Corre en el teléfono: una vez descargada la ruta no necesita red.
 * Sin dependencias, para poder probarlo con Node (tests/js/nav.test.js). */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.BiliNav = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  const CFG = {
    maxAccuracyM: 30,      // peor que esto no se dan giros: un GPS impreciso puede mandar el giro a la esquina equivocada
    offRouteM: 35,         // distancia a la ruta para considerar que se salió
    offRouteFixes: 3,      // lecturas seguidas fuera de ruta antes de recalcular
    recalcMinGapS: 20,
    preTurnM: 45,          // "en unos 40 metros, gire…"
    atTurnM: 12,           // "gire a la derecha y siga…"
    checkInEveryM: 100,    // "Siga derecho, va bien.": lo que importa es saber que Bili sigue ahí, no cuánto falta
    checkInMinLeftM: 100,
    crossingWarnM: 40,
    crossingStopM: 10,
    crossingSnapM: 20,     // un cruce a más de esto de la ruta no es de esta ruta
    crossingMergeM: 15,
    arriveM: 15,
    impreciseRepeatS: 30,
  };

  const R = 6371000;
  const rad = (d) => (d * Math.PI) / 180;

  function haversine(a, b) {
    const dphi = rad(b.lat - a.lat), dl = rad(b.lng - a.lng);
    const h = Math.sin(dphi / 2) ** 2 + Math.cos(rad(a.lat)) * Math.cos(rad(b.lat)) * Math.sin(dl / 2) ** 2;
    return 2 * R * Math.asin(Math.sqrt(h));
  }

  function decodePolyline(str) {
    const out = [];
    let i = 0, lat = 0, lng = 0;
    while (i < str.length) {
      for (let axis = 0; axis < 2; axis++) {
        let result = 0, shift = 0, b;
        do {
          if (i >= str.length) throw new Error('polilínea truncada');
          b = str.charCodeAt(i++) - 63;
          result |= (b & 0x1f) << shift;
          shift += 5;
        } while (b >= 0x20);
        const delta = result & 1 ? ~(result >> 1) : result >> 1;
        if (axis === 0) lat += delta; else lng += delta;
      }
      out.push({ lat: lat / 1e5, lng: lng / 1e5 });
    }
    return out;
  }

  // Metros locales (equirrectangular): suficiente para tramos de pocos kilómetros.
  function toXY(p, ref) {
    return { x: rad(p.lng - ref.lng) * Math.cos(rad(ref.lat)) * R, y: rad(p.lat - ref.lat) * R };
  }

  function buildPath(points) {
    const cum = [0];
    for (let i = 1; i < points.length; i++) cum.push(cum[i - 1] + haversine(points[i - 1], points[i]));
    return { points, cum, length: cum[cum.length - 1] };
  }

  /* Proyecta p sobre la ruta. Devuelve { dist, along }. `hint` desempata cuando la ruta pasa dos veces por el mismo sitio. */
  function project(path, p, hint) {
    const { points, cum } = path;
    const cands = [];
    for (let i = 0; i < points.length - 1; i++) {
      const a = toXY(points[i], p), b = toXY(points[i + 1], p); // p queda en el origen (0,0)
      const dx = b.x - a.x, dy = b.y - a.y, len2 = dx * dx + dy * dy;
      let t = len2 > 0 ? -(a.x * dx + a.y * dy) / len2 : 0;
      t = Math.max(0, Math.min(1, t));
      const cx = a.x + t * dx, cy = a.y + t * dy;
      cands.push({ dist: Math.hypot(cx, cy), along: cum[i] + t * (cum[i + 1] - cum[i]) });
    }
    if (!cands.length) return { dist: haversine(points[0], p), along: 0 };
    const best = Math.min(...cands.map((c) => c.dist));
    const near = cands.filter((c) => c.dist <= best + 5);
    if (hint == null) return near.reduce((m, c) => (c.dist < m.dist ? c : m));
    return near.reduce((m, c) => (Math.abs(c.along - hint) < Math.abs(m.along - hint) ? c : m));
  }

  function positionAt(path, along) {
    const a = Math.max(0, Math.min(path.length, along));
    let i = 1;
    while (i < path.cum.length - 1 && path.cum[i] < a) i++;
    const span = path.cum[i] - path.cum[i - 1] || 1;
    const t = (a - path.cum[i - 1]) / span;
    const p0 = path.points[i - 1], p1 = path.points[i];
    return { lat: p0.lat + (p1.lat - p0.lat) * t, lng: p0.lng + (p1.lng - p0.lng) * t };
  }

  /* Como habla quien camina: pasos y metros de cerca, cuadras de lejos (una cuadra ~ 100 m en Bogotá). Nunca kilómetros.
   * Misma regla que app/routing/spanish.py; las dos se prueban con tests/fixtures/distancias.json. */
  const METROS_POR_CUADRA = 100;
  function sayDistance(m) {
    m = Math.max(0, m);
    if (m < 8) return 'unos pocos pasos';
    if (m < 20) return `unos ${Math.round(m / 5) * 5} metros`;
    if (m < 100) return `unos ${Math.round(m / 10) * 10} metros`;
    if (m < 150) return `unos ${Math.round(m / 50) * 50} metros`;
    return `unas ${Math.max(2, Math.round(m / METROS_POR_CUADRA))} cuadras`;
  }

  const PUNTOS = ['norte', 'noreste', 'este', 'sureste', 'sur', 'suroeste', 'oeste', 'noroeste'];
  function headingWord(deg) {
    return PUNTOS[Math.round((((deg % 360) + 360) % 360) / 45) % 8];
  }

  const CROSSING_NAME = { semaforo: 'cruce con semáforo', cebra: 'paso peatonal', cruce: 'posible cruce de calle' };
  const CROSSING_RANK = { semaforo: 0, cebra: 1, cruce: 2 };
  const STOP_MESSAGE = 'Detenga el paso. Cruce solo si escucha que no vienen vehículos.';

  class Navigator {
    /* ruta: respuesta de POST /v1/rutas. opts: { say(text, priority), onOffRoute(pos), now() } */
    constructor(ruta, opts = {}) {
      this.cfg = { ...CFG, ...(opts.cfg || {}) };
      this.say = opts.say || (() => {});
      this.onOffRoute = opts.onOffRoute || (() => {});
      this.now = opts.now || (() => Date.now() / 1000);
      this.path = buildPath(decodePolyline(ruta.polilinea));
      this.destino = ruta.destino;
      this.progress = 0;
      this.finished = false;
      this.said = new Set();
      this.events = [];
      this.offCount = 0;
      this.lastRecalc = -1e9;
      this.imprecise = false;
      this.lastImpreciseSay = -1e9;
      this.lastCheckAlong = 0;

      let prev = 0;
      this.steps = ruta.pasos.map((p) => {
        const s = Math.max(prev, project(this.path, p.inicio).along);
        prev = s;
        return { ...p, startAlong: s };
      });

      this.crossings = this._prepareCrossings(ruta.cruces || []);
    }

    _prepareCrossings(cruces) {
      const snapped = [];
      for (const c of cruces) {
        const pr = project(this.path, c);
        if (pr.dist <= this.cfg.crossingSnapM && pr.along > 8 && pr.along < this.path.length - 8) {
          snapped.push({ tipo: c.tipo, along: pr.along });
        }
      }
      // Dos puntos del mismo cruce (ambas aceras) son un solo aviso: gana el más informativo.
      snapped.sort((a, b) => CROSSING_RANK[a.tipo] - CROSSING_RANK[b.tipo]);
      const kept = [];
      for (const c of snapped) if (kept.every((k) => Math.abs(k.along - c.along) > this.cfg.crossingMergeM)) kept.push(c);
      return kept.sort((a, b) => a.along - b.along);
    }

    _say(text, priority) {
      const ev = { text, priority };
      this.events.push(ev);
      this._batch.push(ev);
      this.say(text, priority);
    }

    get remainingM() { return Math.max(0, this.path.length - this.progress); }

    update(pos) {
      this._batch = [];
      if (this.finished) return this._batch;
      const t = pos.t != null ? pos.t : this.now();

      if (pos.accuracy != null && pos.accuracy > this.cfg.maxAccuracyM) {
        this.imprecise = true;
        if (t - this.lastImpreciseSay >= this.cfg.impreciseRepeatS) {
          this.lastImpreciseSay = t;
          this._say('Posición imprecisa. Avance con cuidado: por ahora no puedo darle giros.', 'P1');
        }
        return this._batch;
      }
      if (this.imprecise) {
        this.imprecise = false;
        this._say('Posición recuperada.', 'P2');
      }

      const proj = project(this.path, pos, this.progress);

      if (proj.dist > this.cfg.offRouteM) {
        this.offCount++;
        if (this.offCount >= this.cfg.offRouteFixes && t - this.lastRecalc >= this.cfg.recalcMinGapS) {
          this.lastRecalc = t;
          this._say('Se salió de la ruta. Recalculando.', 'P1');
          this.onOffRoute(pos);
        }
        return this._batch;
      }
      this.offCount = 0;

      if (proj.along > this.progress) this.progress = proj.along;

      if (this.remainingM <= this.cfg.arriveM || haversine(pos, this.destino) <= this.cfg.arriveM) {
        this.finished = true;
        this._say('Llegó a su destino.', 'P1');
        return this._batch;
      }

      this._turns();
      this._crossingsAlert();
      return this._batch;
    }

    _once(key) {
      if (this.said.has(key)) return false;
      this.said.add(key);
      return true;
    }

    _turns() {
      const c = this.cfg;
      if (this._once('start')) this._say(this.steps[0].frase, 'P1');

      const nextIdx = this.steps.findIndex((s, i) => i > 0 && s.startAlong > this.progress - 8);
      const left = nextIdx === -1 ? this.remainingM : this.steps[nextIdx].startAlong - this.progress;

      if (nextIdx !== -1) {
        const s = this.steps[nextIdx];
        // Un tramo sin maniobra clara ('continúe') no merece preaviso: no hay nada que prepararse a hacer.
        if (s.accion !== 'continúe' && left <= c.preTurnM && left > c.atTurnM && this._once('pre' + nextIdx)) {
          this._say(`En ${sayDistance(left)}, ${s.accion}.`, 'P1');
        }
        if (left <= c.atTurnM && this._once('now' + nextIdx)) {
          this._say(s.frase, 'P1');
          this.lastCheckAlong = this.progress;
        }
      }

      // Los "va bien" son lo menos urgente: no se dicen si un cruce está por avisarse.
      const cruceCerca = this.crossings.some((x) => x.along - this.progress > -5 && x.along - this.progress <= c.crossingWarnM + 20);
      if (!cruceCerca && left > c.checkInMinLeftM && this.progress - this.lastCheckAlong >= c.checkInEveryM) {
        this.lastCheckAlong = this.progress;
        this._say('Siga derecho, va bien.', 'P2');
      }
    }

    _crossingsAlert() {
      const c = this.cfg;
      this.crossings.forEach((x, k) => {
        const d = x.along - this.progress;
        if (d < -5) return;
        if (d <= c.crossingWarnM && d > c.crossingStopM && this._once('cp' + k)) {
          this._say(`Se acerca un ${CROSSING_NAME[x.tipo]} en ${sayDistance(d)}.`, 'P1');
        }
        if (d <= c.crossingStopM && this._once('cn' + k)) {
          this.said.add('cp' + k); // si no hubo aviso previo, ya no tiene sentido darlo
          this._say(STOP_MESSAGE, 'P0');  // en un cruce corta cualquier otra cosa, incluida la escucha
        }
      });
    }
  }

  return { Navigator, decodePolyline, buildPath, project, positionAt, haversine, sayDistance, headingWord, CFG, STOP_MESSAGE };
});
