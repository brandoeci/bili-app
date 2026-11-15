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
    menuListenMs: 7000,     // tiempo para decir "nuevo destino" o "apagar" tras mantener dos dedos
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

  /* "Estoy en la calle 72 con séptima" -> "calle 72 con séptima". Devuelve '' si no queda nada útil. */
  function cleanOrigin(text) {
    const s = (text || '').trim().replace(/^por favor[, ]*/i, '')
      .replace(/^(yo\s+)?(estoy|me\s+encuentro|me\s+ubico|ando|voy)\s+(en|por)(\s+|$)/i, '').replace(/^en\s+/i, '');
    return cleanDestination(s);
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

  /* Menú de dos dedos: 'newdest' | 'off' | null. Ante la duda (nada claro, las dos cosas, o un "no") NO se apaga: seguir guiando es lo seguro. */
  function parseMenu(text) {
    const n = norm(text);
    if (!n || /\bno\b/.test(n)) return null;
    const off = /\b(apag\w*|cancel\w*|deten\w*|parar?|termin\w*|finaliz\w*|salir)\b/.test(n);
    const nuevo = /\b(nuev\w*|otr[oa]|cambi\w*|destino|ruta)\b/.test(n);
    if (off === nuevo) return null;
    return off ? 'off' : 'newdest';
  }

  /* Gesto de mantener N dedos en la pantalla: aviso a mitad de camino y disparo al completar el tiempo.
   * Se alimenta con el número de dedos que hay tocando (touches(n)) cada vez que cambia; no depende del navegador. */
  function createHold({ fingers = 2, holdMs = 2000, warnMs = 1000, onWarn = () => {}, onFire = () => {},
    setT = (f, ms) => setTimeout(f, ms), clearT = (t) => clearTimeout(t), now = () => Date.now() } = {}) {
    let warnT = null, fireT = null, active = false, lastFire = -Infinity;
    const clear = () => { clearT(warnT); clearT(fireT); warnT = fireT = null; active = false; };
    return {
      touches(n) {
        if (n === fingers && !active) {
          active = true;
          warnT = setT(() => { if (active) onWarn(); }, warnMs);
          fireT = setT(() => { clear(); lastFire = now(); onFire(); }, holdMs);
        } else if (n !== fingers && active) clear();  // soltó un dedo o puso otro: no era el gesto
      },
      /* Al soltar los dedos el navegador manda un "click": tras el gesto hay que ignorarlo. */
      suppressClick() { return now() - lastFire < 1200; },
      get active() { return active; },
    };
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

  /* Qué se le dice a la persona cuando algo falla. Solo se dicen los mensajes pensados para ella (marcados con paraLaPersona);
   * un error técnico ("Load failed", "Failed to fetch"...) no se lee: devuelve null y Bili pide repetir. */
  function mensajeDeError(err) {
    return err && err.paraLaPersona === true && typeof err.message === 'string' && err.message.trim() ? err.message : null;
  }
  const REPETIR = 'No le entendí. Repita después del tono.';

  /* Qué se dice si falla buscar la ruta. Ubicación: mensajes claros. Un error técnico de red ("Load failed") devuelve null:
   * sin mensaje, Bili dice REPETIR. Un error de geolocalización se reconoce por sus constantes (PERMISSION_DENIED...), no solo por
   * tener "code": otras excepciones del navegador también traen un code numérico. */
  function mensajeDeFalloDeRuta(err) {
    const geo = err && typeof err.PERMISSION_DENIED === 'number';
    if (geo && err.code === err.PERMISSION_DENIED) return 'No tengo permiso para usar la ubicación. Actívela en los ajustes del teléfono.';
    if (geo) return 'No pude obtener su ubicación. Salga a un lugar abierto e intente de nuevo.';
    if (err && err.message === 'sin-gps') return 'Este teléfono no tiene ubicación disponible.';
    return mensajeDeError(err);
  }
  /* Error de la petición de ruta. Solo los códigos con un motivo escrito para la persona (no encontré el lugar, queda lejos,
   * límite diario, no se pudo calcular) se dicen; el resto (500, 503 "no está configurado", etc.) es técnico y se calla. */
  function errorDeRuta(status, detalle) {
    const e = new Error(typeof detalle === 'string' ? detalle : 'Revise el destino e intente de nuevo.');
    e.paraLaPersona = [404, 422, 429, 502].includes(status) && typeof detalle === 'string';
    return e;
  }

  const AYUDA = 'No entendí la orden. Puede decir: repetir, dónde estoy, describir, nuevo destino, o cancelar.';
  const TOQUE = 'Toque la pantalla y dígame el destino.';
  const MENU = '¿Nuevo destino o apagar? Hable después del tono.';

  /* env: {
   *   say(text, priority) -> Promise            resuelve cuando Bili terminó de hablar
   *   listen(ms) -> Promise<{text}|{silence}|{interrupted}|{error}>
   *   whenQuiet() -> Promise                    resuelve cuando no hay nadie hablando
   *   beep(), interrupt()                       tono de "hable ahora" y callar lo no urgente
   *   findRoute(destino, origenDicho?) -> Promise<{ok, ruta, speech} | {ok:false, message, needOrigin?}>
   *                                             needOrigin: no hay ubicación del GPS; Bili pregunta dónde está y vuelve a buscar
   *   startRoute(ruta), cancelRoute(), repeat(), describe()
   *   whereText() -> Promise<string>            "Está en la Carrera 7, caminando hacia el norte. No tiene una ruta activa."
   * } */
  function createDialog(env) {
    let busy = false;
    let navigating = false;

    async function hear(ms) {
      for (let i = 0; i <= T.maxInterrupts; i++) {
        await env.whenQuiet();
        await env.beep();   // si el tono es asíncrono, se espera a que acabe: que no lo corte ni lo oiga el reconocimiento
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

    /* Sin GPS: "¿En qué dirección está?". Devuelve lo que dijo la persona, o '' si no respondió nada útil. */
    async function askOrigin(motivo) {
      await env.say(`${motivo ? motivo + ' ' : ''}Para calcular la ruta, dígame dónde está ahora, por ejemplo: calle 72 con carrera 7. Hable después del tono.`, 'P1');
      for (let k = 0; k < 2; k++) {
        const r = await hear(T.askListenMs);
        if (r.error || r.silence) return '';
        const o = cleanOrigin(r.text);
        if (o) return o;
        if (k === 0) await env.say(REPETIR, 'P1');
      }
      return '';
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
        let res = dest ? await env.findRoute(dest) : null;
        if (res && res.needOrigin) {
          const origen = await askOrigin(res.message);
          if (!origen) { await env.say('Sin saber dónde está no puedo calcular la ruta. ' + TOQUE, 'P1'); return 'no-origin'; }
          res = await env.findRoute(dest, origen);
        }
        if (res && res.ok) {
          const c = await confirm(res.speech);
          if (c === 'yes') { navigating = true; env.startRoute(res.ruta); return 'started'; }
          if (c === 'silence') { await env.say('No escuché una respuesta, así que no comienzo. ' + TOQUE, 'P1'); return 'silence'; }
          if (intento >= T.maxTries - 1) { await env.say('Está bien. ' + TOQUE, 'P1'); return 'declined'; }
          await env.say('Está bien. Dígame el destino otra vez, después del tono.', 'P1');
        } else {
          if (intento >= T.maxTries - 1) { await env.say('No logré encontrar ese lugar. ' + TOQUE, 'P1'); return 'failed'; }
          await env.say((res && res.message) || REPETIR, 'P1');
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
      if (env.busy) env.busy(true);   // mientras dure el diálogo, las alertas normales esperan en vez de colarse entre sus frases
      try { return await fn(); } finally { busy = false; if (env.busy) env.busy(false); }
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
      /* Dos dedos mantenidos: corta lo que Bili esté diciendo y pregunta "¿nuevo destino o apagar?".
       * Sin ruta activa hace lo mismo que un toque (preguntar el destino). Apagar solo ocurre si la persona lo dice claro. */
      async onMenu() {
        if (busy) return 'busy';
        env.interrupt();
        if (!navigating) return guarded(() => askDestination('¿A dónde quiere ir? Hable después del tono.'));
        return guarded(async () => {
          await env.say(MENU, 'P1');
          const r = await hear(T.menuListenMs);
          if (r.error) { await env.say('No puedo escuchar ahora. Mantenga dos dedos para intentarlo de nuevo.', 'P1'); return 'error'; }
          if (r.silence) { await env.say('Sigo guiándolo.', 'P1'); return 'silence'; }
          const op = parseMenu(r.text);
          if (op === 'off') {
            navigating = false;
            await env.say('Guía apagada.', 'P1');
            (env.shutdown || env.cancelRoute)();
            return 'off';
          }
          if (op === 'newdest') { await askDestination('Dígame el nuevo destino, después del tono.'); return 'newdest'; }
          await env.say('No le entendí. Sigo guiándolo. Mantenga dos dedos para intentarlo de nuevo.', 'P1');
          return 'unknown';
        });
      },
      routeStarted() { navigating = true; },  // una ruta que arrancó por otro camino (p. ej. escrita por un acompañante)
      routeEnded() { navigating = false; },
      get navigating() { return navigating; },
    };
  }

  return { createDialog, createHold, parseYesNo, cleanDestination, cleanOrigin, parseCommand, parseMenu, parseFree, mensajeDeError, mensajeDeFalloDeRuta, errorDeRuta, speakable, norm, T };
});
