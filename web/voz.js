/* Cola de voz de Bili. Regla central: NINGUNA frase se corta a la mitad, porque una frase cortada no se entiende.
 *
 *  - Todo mensaje se dice por frases. Entre una frase y la siguiente se decide quién sigue.
 *  - Lo urgente (P0) pasa por delante, pero en el límite de una frase, no en medio. Si la frase en curso es muy larga y lo urgente
 *    lleva esperando demasiado, se corta y esa frase se repite ENTERA al reanudar. Lo que se cortó nunca se da por dicho.
 *  - El diálogo (carril 'dialogo': bienvenida, "¿a dónde quiere ir?", resumen de ruta, "¿comienzo?") es atómico: mientras dura,
 *    las alertas normales del detector esperan su turno en vez de colarse entre sus frases. Lo urgente no se borra: las frases del
 *    diálogo que estaban en cola se conservan y se dicen después.
 *  - Solo la persona puede callar a Bili a mitad de frase (interruptSoft: tocó la pantalla para hablar).
 * Sin dependencias del navegador: todo entra por `env`, así se prueba con Node y un reloj falso. */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.BiliVoz = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  const RANK = { P0: 0, P1: 1, P2: 2, P3: 3 };
  const MAX_AGE_MS = { P0: 4000, P1: 4000, P2: 20000, P3: 10000 };  // un aviso que no empezó a decirse y ya caducó se descarta
  const P0_ESPERA_MAX_MS = 2500;  // lo urgente espera a que acabe la frase; si esta es muy larga, pasado esto se corta

  /* "Encontré el Museo. Ruta a pie de unas 8 cuadras. ¿Comienzo? Diga sí o no." -> 4 frases. Las muy cortas ("Cra.", "Sí.") se pegan a la siguiente. */
  function partir(texto) {
    const t = String(texto == null ? '' : texto).replace(/\s+/g, ' ').trim();
    if (!t) return [];
    const out = [];
    for (const z of t.split(/(?<=[.!?…])\s+(?=[A-ZÁÉÍÓÚÑ¿¡0-9])/)) {
      if (out.length && out[out.length - 1].length < 14) out[out.length - 1] += ' ' + z;
      else out.push(z);
    }
    return out;
  }

  /* env: {
   *   synth: { speak(texto, alTerminar), cancel() }   alTerminar se llama al acabar O al fallar la frase
   *   now(), setTimeout(f, ms), clearTimeout(id)       (opcionales: por defecto los del navegador)
   *   vibrate(patron), interruptListen()               (opcionales) lo urgente vibra y corta la escucha
   *   cfg: { p0EsperaMaxMs, maxAgeMs }                  (opcional)
   * } */
  function create(env) {
    const now = env.now || (() => Date.now());
    const setT = env.setTimeout || ((f, ms) => setTimeout(f, ms));
    const clearT = env.clearTimeout || ((id) => clearTimeout(id));
    const cfg = Object.assign({ p0EsperaMaxMs: P0_ESPERA_MAX_MS, maxAgeMs: MAX_AGE_MS }, env.cfg || {});
    let queue = [], hablando = null, gen = 0, seq = 0, listening = false, dialogoActivo = false, timerCorte = null;
    const history = [];

    const terminar = (item) => { if (item && item.cb) { const cb = item.cb; item.cb = null; cb(); } };
    const esDialogo = (i) => i.lane === 'dialogo';
    function descartar(pred) {
      const fuera = queue.filter(pred);
      queue = queue.filter((i) => !pred(i));
      fuera.forEach(terminar);   // quien espera a que se diga no se queda colgado
    }

    function permitido(item) {
      if (item.rank === 0) return true;
      if (listening) return false;                       // la persona está hablando: solo lo urgente
      if (dialogoActivo && !esDialogo(item)) return false;  // el diálogo no se interrumpe con alertas normales
      return true;
    }
    function siguiente() {
      queue = queue.filter((i) => {
        if (i.rank === 0 || esDialogo(i) || i.i > 0) return true;   // lo urgente, el diálogo y lo ya empezado no caducan: mejor tarde que nunca
        if (now() - i.t > (cfg.maxAgeMs[i.priority] ?? 10000)) { terminar(i); return false; }
        return true;
      });
      // por urgencia; a igual urgencia, lo que YA empezó a decirse termina antes que nada nuevo; luego el diálogo; luego por llegada
      const orden = (a, b) => a.rank - b.rank || ((b.i > 0) - (a.i > 0)) || (esDialogo(b) - esDialogo(a)) || a.seq - b.seq;
      return queue.filter(permitido).sort(orden)[0] || null;
    }

    function pump() {
      if (hablando) return;
      const item = siguiente();
      if (!item) return;
      queue.splice(queue.indexOf(item), 1);
      const id = ++gen;
      hablando = { item, id };
      if (item.i === 0) { history.push(item.texto); if (history.length > 8) history.shift(); }
      env.synth.speak(item.partes[item.i], () => alTerminarFrase(id));
    }
    function alTerminarFrase(id) {
      if (!hablando || hablando.id !== id) return;           // la frase ya se canceló: su aviso tardío no cuenta
      clearT(timerCorte); timerCorte = null;
      const item = hablando.item;
      hablando = null;
      item.i++;
      if (item.i >= item.partes.length) terminar(item);
      else queue.push(item);                                 // vuelve a la cola: lo urgente puede pasar antes de su siguiente frase
      pump();
    }

    /* Corta la frase en curso (solo por lo urgente o por la persona). Si se corta por lo urgente, esa frase se repite entera. */
    function cortarFrase() {
      gen++; clearT(timerCorte); timerCorte = null;
      const item = hablando.item;
      hablando = null;
      env.synth.cancel();
      return item;
    }
    function vigilarP0() {
      if (!hablando || hablando.item.rank === 0 || !hablando.item.interruptible || timerCorte !== null) return;
      const id = hablando.id;
      timerCorte = setT(() => {
        timerCorte = null;
        if (!hablando || hablando.id !== id || !queue.some((i) => i.rank === 0)) return;
        queue.push(cortarFrase());                           // la frase no se da por dicha: se repetirá entera
        pump();
      }, cfg.p0EsperaMaxMs);
    }

    function speak(texto, priority = 'P3', interruptible = true, cb = null, opts = {}) {
      const partes = partir(texto);
      if (!partes.length) { if (cb) cb(); return; }
      const rank = RANK[priority] ?? 3;
      const item = { texto, partes, i: 0, rank, priority, interruptible, cb, t: now(), seq: ++seq, lane: opts.lane || null };
      if (rank === 0) {
        descartar((i) => i.rank !== 0 && !esDialogo(i) && i.i === 0);   // alertas normales viejas ya no valen; el diálogo se conserva
        if (env.vibrate) env.vibrate([200, 80, 200]);
        if (env.interruptListen) env.interruptListen();
      } else if (rank === 2) {
        descartar((i) => i.rank === 2 && i.i === 0);
      }
      queue.push(item);
      if (rank === 0) vigilarP0();
      pump();
    }

    return {
      speak,
      /* Se dice y devuelve una promesa que se cumple cuando TERMINÓ de decirse completo (o se descartó). */
      sayAndWait: (texto, priority = 'P1', opts = {}) => new Promise((res) => speak(texto, priority, true, res, opts)),
      /* La persona tocó la pantalla para hablar: se calla todo lo que no sea urgente, a mitad de frase si hace falta. */
      interruptSoft() {
        if (hablando && hablando.item.rank > 0) terminar(cortarFrase());
        descartar((i) => i.rank > 0);
      },
      setListening(b) { listening = !!b; if (!listening) pump(); },
      setDialogBusy(b) { dialogoActivo = !!b; if (!dialogoActivo) pump(); },
      /* ¿Hay alguien hablando o algo urgente por decir? Para no empezar a escuchar encima. */
      ocupada: () => !!hablando || queue.some((i) => i.rank === 0),
      ultimo: () => history[history.length - 1] || null,
      reset() {
        if (hablando) { const it = cortarFrase(); terminar(it); }
        const todo = queue; queue = []; todo.forEach(terminar);
        listening = dialogoActivo = false;
      },
      get hablando() { return hablando ? hablando.item.partes[hablando.item.i] : null; },
      get pendientes() { return queue.map((i) => i.texto); },
    };
  }

  return { create, partir, RANK, MAX_AGE_MS, P0_ESPERA_MAX_MS };
});
