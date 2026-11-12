/* Diálogo por voz de Bili: la persona no puede ver botones, así que todo se resuelve hablando.
 * Reglas: Bili nunca escucha mientras habla, da tiempo para responder, y si no hay respuesta no insiste ni asume un "sí".
 * Sin dependencias del navegador: recibe sus entradas y salidas en `env` para poder probarlo con Node. */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.BiliVoice = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  const T = {
    askListenMs: 8000,      // tiempo para decir el destino
    confirmListenMs: 7000,  // tiempo para decir sí o no
    commandListenMs: 6000,  // tiempo para dar una orden durante la ruta
    maxInterrupts: 3,       // veces que una alerta urgente puede cortar la escucha antes de rendirse
    maxTries: 3,            // intentos de destino cuando se oye algo pero no se logra una ruta
  };

  function norm(t) {
    return (t || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/[^a-z0-9\s]/g, ' ').replace(/\s+/g, ' ').trim();
  }

  const YES = new Set(['si', 'claro', 'dale', 'listo', 'ok', 'okay', 'vale', 'confirmo', 'comienza', 'comienzo', 'empieza', 'empiece', 'adelante', 'correcto', 'afirmativo', 'exacto', 'perfecto', 'bueno', 'vamos', 'hagale']);
  const NO = new Set(['no', 'nop', 'nunca', 'cancela', 'cancelar', 'cancelo', 'negativo', 'otro', 'otra', 'cambiar', 'cambia']);

  /* 'yes' | 'no' | null. Una respuesta que mezcla sí y no ("sí... no") es ambigua: no se adivina. */
  function parseYesNo(text) {
    const tokens = norm(text).split(' ');
    const yes = tokens.some((w) => YES.has(w));
    const no = tokens.some((w) => NO.has(w));
    if (yes && !no) return 'yes';
    if (no && !yes) return 'no';
    return null;
  }

  const PREFIXES = [
    'me puedes llevar al', 'me puedes llevar a', 'puedes llevarme al', 'puedes llevarme a', 'quiero llegar al', 'quiero llegar a',
    'necesito ir al', 'necesito ir a', 'quiero ir al', 'quiero ir a', 'llévame hasta', 'llevame hasta', 'llévame al', 'llevame al',
    'llévame a', 'llevame a', 'guíame al', 'guiame al', 'guíame a', 'guiame a', 'voy para', 'voy al', 'voy a', 'vamos al', 'vamos a',
    'ruta al', 'ruta a', 'ir al', 'ir a', 'al', 'a',
  ].sort((x, y) => y.length - x.length);

  /* Quita "quiero ir a…", "llévame al…" y deja solo el lugar. Devuelve '' si no queda nada útil. */
  function cleanDestination(text) {
    let s = (text || '').trim().replace(/^por favor[, ]*/i, '').replace(/[,.\s]*por favor[.\s]*$/i, '').replace(/[.,;:!?¿¡]+$/g, '').trim();
    for (const p of PREFIXES) {
      const base = '^' + p.replace(/ /g, '\\s+');
      if (new RegExp(base + '$', 'i').test(s)) return '';  // solo dijo "ir a…" y nada más
      const re = new RegExp(base + '\\s+', 'i');
      if (re.test(s)) { s = s.replace(re, ''); break; }
    }
    s = s.trim();
    return s.length >= 3 ? s : '';
  }

  /* 'repeat' | 'newdest' | 'cancel' | 'where' | 'describe' | null */
  function parseCommand(text) {
    const n = norm(text);
    if (/\brep(it|et)/.test(n)) return 'repeat';
    if (/\b(nuevo destino|otro destino|cambiar|cambia el destino|nueva ruta|otra ruta)\b/.test(n)) return 'newdest';
    if (/\b(cancel|deten|detener|termin|parar|para|finaliz)/.test(n)) return 'cancel';
    if (/\b(donde estoy|cuanto falta|que tan lejos|cuanto queda|falta mucho)\b/.test(n)) return 'where';
    if (/\b(descri|que hay|que ves|que veo)/.test(n)) return 'describe';
    return null;
  }

  /* "sin destino", "ninguno", "solo quiero caminar": la persona no tiene una ruta, y eso es una respuesta válida. */
  function parseFree(text) {
    return /\b(sin destino|sin ruta|ningun\w*|no tengo|solo (quiero )?(camin\w*|pase\w*|anda\w*)|cualquier\w*|libre|no se)\b/.test(norm(text));
  }

  /* Para el sintetizador de voz: "Cra." lo deletrea; "Carrera" lo dice bien. */
  function speakable(text) {
    return (text || '')
      .replace(/\bCra?s?\.?(?=\s|$)/gi, 'Carrera').replace(/\bKr\.?(?=\s|$)/gi, 'Carrera')
      .replace(/\bCl\.?(?=\s|$)/gi, 'Calle').replace(/\bAv\.?(?=\s|$)/gi, 'Avenida')
      .replace(/\bAk\.?(?=\s|$)/gi, 'Avenida Carrera').replace(/\bAc\.?(?=\s|$)/gi, 'Avenida Calle')
      .replace(/\bDg\.?(?=\s|$)/gi, 'Diagonal').replace(/\bTv\.?(?=\s|$)/gi, 'Transversal')
      .replace(/\s*&\s*/g, ' con ').replace(/\s*#\s*/g, ' número ').replace(/\s+/g, ' ').trim();
  }

  const AYUDA = 'No entendí la orden. Puede decir: repetir, dónde estoy, describir, nuevo destino, o cancelar.';
  const TOQUE = 'Toque la pantalla y dígame el destino.';

  /* env: {
   *   say(text, priority) -> Promise            resuelve cuando Bili terminó de hablar
   *   listen(ms) -> Promise<{text}|{silence}|{interrupted}|{error}>
   *   whenQuiet() -> Promise                    resuelve cuando no hay nadie hablando
   *   beep(), interrupt()                       tono de "hable ahora" y callar lo no urgente
   *   findRoute(destino) -> Promise<{ok, ruta, speech} | {ok:false, message}>
   *   startRoute(ruta), cancelRoute(), repeat(), describe()
   *   whereText() -> Promise<string>            "Está en la Carrera 7, caminando hacia el norte. No tiene una ruta activa."
   * } */
  function createDialog(env) {
    let busy = false;
    let navigating = false;

    async function hear(ms) {
      for (let i = 0; i <= T.maxInterrupts; i++) {
        await env.whenQuiet();
        env.beep();
        const r = await env.listen(ms);
        if (!r.interrupted) return r;  // una alerta urgente cortó la escucha: se espera a que termine y se vuelve a escuchar
      }
      return { silence: true };
    }

    async function confirm(speech) {
      await env.say(speech, 'P1');
      for (let k = 0; k < 2; k++) {
        const r = await hear(T.confirmListenMs);
        if (r.error || r.silence) return 'silence';
        const a = parseYesNo(r.text);
        if (a) return a;
        if (k === 0) await env.say('No le entendí. Diga sí o no.', 'P1');
      }
      return 'silence';  // sin respuesta clara nunca se asume que sí
    }

    async function askDestination(prompt) {
      await env.say(prompt || '¿A dónde quiere ir? Hable después del tono. Si no quiere ir a ningún lugar, no diga nada.', 'P1');
      let r = await hear(T.askListenMs);
      for (let intento = 0; ; intento++) {
        if (r.error) { await env.say('No puedo escuchar ahora. ' + TOQUE, 'P1'); return 'error'; }
        if (r.silence) { await env.say('Entendido. Cuando quiera ir a un lugar, ' + TOQUE.toLowerCase(), 'P1'); return 'silence'; }
        if (parseFree(r.text)) {
          await env.say('Entendido, camino libre. Le aviso de los obstáculos. Si quiere ir a un lugar, ' + TOQUE.toLowerCase(), 'P1');
          return 'free';
        }
        const dest = cleanDestination(r.text);
        const res = dest ? await env.findRoute(dest) : null;
        if (res && res.ok) {
          const c = await confirm(res.speech);
          if (c === 'yes') { navigating = true; env.startRoute(res.ruta); return 'started'; }
          if (c === 'silence') { await env.say('No escuché una respuesta, así que no comienzo. ' + TOQUE, 'P1'); return 'silence'; }
          if (intento >= T.maxTries - 1) { await env.say('Está bien. ' + TOQUE, 'P1'); return 'declined'; }
          await env.say('Está bien. Dígame el destino otra vez, después del tono.', 'P1');
        } else {
          if (intento >= T.maxTries - 1) { await env.say('No logré encontrar ese lugar. ' + TOQUE, 'P1'); return 'failed'; }
          await env.say((res && res.message) || 'No le entendí. Dígame el destino otra vez, después del tono.', 'P1');
        }
        r = await hear(T.askListenMs);
      }
    }

    async function command() {
      const r = await hear(T.commandListenMs);
      if (r.error) { await env.say('No puedo escuchar ahora.', 'P1'); return 'error'; }
      if (r.silence) return 'silence';  // la persona tocó y no dijo nada: no se le habla de más
      switch (parseCommand(r.text)) {
        case 'repeat': env.repeat(); return 'repeat';
        case 'where': await env.say(await env.whereText(), 'P1'); return 'where';
        case 'describe': env.describe(); return 'describe';
        case 'cancel': navigating = false; env.cancelRoute(); await env.say('Ruta cancelada.', 'P1'); return 'cancel';
        case 'newdest': return 'newdest';
        default: await env.say(AYUDA, 'P1'); return 'unknown';
      }
    }

    async function guarded(fn) {
      if (busy) return 'busy';
      busy = true;
      try { return await fn(); } finally { busy = false; }
    }

    return {
      /* Al activar la app: pregunta el destino sin que la persona tenga que tocar nada. */
      start: () => guarded(() => askDestination()),
      /* Un toque en cualquier parte de la pantalla: Bili se calla y escucha. */
      async onTap() {
        if (busy) return 'busy';
        env.interrupt();
        if (!navigating) return guarded(() => askDestination('¿A dónde quiere ir? Hable después del tono.'));
        const out = await guarded(command);
        if (out === 'newdest') return guarded(() => askDestination('Dígame el nuevo destino, después del tono.'));
        return out;
      },
      routeStarted() { navigating = true; },  // una ruta que arrancó por otro camino (p. ej. escrita por un acompañante)
      routeEnded() { navigating = false; },
      get navigating() { return navigating; },
    };
  }

  return { createDialog, parseYesNo, cleanDestination, parseCommand, parseFree, speakable, norm, T };
});
