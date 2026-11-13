/* Vigilante de la conexión con el servidor. Sin servidor no hay detección de obstáculos, y una persona ciega no ve un
 * letrero de "sin conexión": hay que DECIRLO. Detecta la caída aunque el navegador no se entere (el iPhone duerme el Wi-Fi
 * y el WebSocket puede seguir "abierto" durante minutos), reintenta y avisa por voz al caer, cada tanto mientras siga caída,
 * y al volver. Sin dependencias del navegador: recibe todo en `env`, para poder probarlo con Node y un reloj falso. */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.BiliConexion = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  const CFG = {
    tickMs: 1000,            // cada cuánto revisa
    pingMs: 4000,            // cada cuánto pregunta "¿sigues ahí?" al servidor
    silenceMs: 10000,        // sin NINGÚN mensaje durante tanto tiempo = conexión muerta, aunque el navegador no lo note
    wakeGraceMs: 3000,       // al volver al primer plano, el servidor tiene esto para contestar antes de darlo por caído
    announceAfterMs: 3000,   // no se avisa por un parpadeo: solo si la caída dura esto
    reminderMs: 30000,       // mientras siga caída, se recuerda cada tanto
    backoffMs: [1000, 2500, 5000],  // esperas entre reintentos (la última se repite)
  };

  const MSG = {
    lost: 'Perdí la conexión con el servidor. Ya no detecto obstáculos. Use su bastón. Revise su conexión.',
    still: 'Sigo sin conexión con el servidor. Use su bastón. Revise su conexión.',
    back: 'Conexión recuperada.',
  };

  /* env: { now(), setInterval(f, ms), clearInterval(id), open(), ping(), say(texto, prioridad), cfg? }
   *   open():  cierra los canales viejos y abre los dos de nuevo
   *   ping():  manda un "ping" por el canal de eventos (el servidor contesta "pong") */
  function create(env) {
    const cfg = Object.assign({}, CFG, env.cfg || {});
    let timer = null, running = false;
    let state = 'ok';              // 'ok' | 'lost'
    let lastHeard = 0, lastPing = 0, lostSince = 0, nextTry = 0, tries = 0, announced = false, lastSaid = 0;

    function markLost() {
      if (state === 'lost') return;
      state = 'lost'; lostSince = env.now(); tries = 0; announced = false; lastSaid = 0;
      nextTry = env.now();         // el primer reintento es inmediato
    }

    function tick() {
      if (!running) return;
      const t = env.now();
      if (state === 'ok') {
        if (t - lastHeard > cfg.silenceMs) { markLost(); } else if (t - lastPing >= cfg.pingMs) { lastPing = t; env.ping(); }
      }
      if (state === 'lost') {
        if (!announced && t - lostSince >= cfg.announceAfterMs) { announced = true; lastSaid = t; env.say(MSG.lost, 'P1'); }
        else if (announced && t - lastSaid >= cfg.reminderMs) { lastSaid = t; env.say(MSG.still, 'P1'); }
        if (t >= nextTry) {
          env.open();
          nextTry = t + cfg.backoffMs[Math.min(tries, cfg.backoffMs.length - 1)];
          tries++;
        }
      }
    }

    return {
      start() { running = true; const t = env.now(); lastHeard = lastPing = t; state = 'ok'; timer = env.setInterval(tick, cfg.tickMs); },
      stop() { running = false; if (timer !== null) env.clearInterval(timer); timer = null; },
      /* Llegó cualquier mensaje del servidor (pong, cuadro, voz...): la conexión funciona. */
      heard() {
        lastHeard = env.now();
        if (state === 'lost') { state = 'ok'; if (announced) env.say(MSG.back, 'P1'); announced = false; tries = 0; }
      },
      /* Se cerró un canal (o se perdió la red): se da por caída ya, sin esperar el silencio. */
      closed() { if (running) markLost(); },
      /* La página volvió al primer plano o volvió la red: revisar ahora mismo en vez de esperar. */
      wake() {
        if (!running) return;
        const t = env.now();
        if (state === 'lost') { nextTry = t; return; }
        lastPing = t; env.ping();
        // si el servidor no contesta pronto, se da por caída sin esperar todo el silencio normal
        lastHeard = Math.min(lastHeard, t - cfg.silenceMs + cfg.wakeGraceMs);
      },
      get state() { return state; },
    };
  }

  return { create, CFG, MSG };
});
