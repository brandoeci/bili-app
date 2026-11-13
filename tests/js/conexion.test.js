const test = require('node:test');
const assert = require('node:assert/strict');
const C = require('../../web/conexion.js');

/* Mundo falso: reloj que avanza de a un segundo y registro de lo que hace el vigilante. */
function mundo() {
  let t = 0, f = null;
  const log = [];
  const env = {
    now: () => t,
    setInterval: (fn) => { f = fn; return 1; },
    clearInterval: () => { f = null; },
    open: () => log.push(['open', t]),
    ping: () => log.push(['ping', t]),
    say: (x) => log.push(['say', t, x]),
  };
  const sup = C.create(env);
  const w = {
    sup, log, env,
    get t() { return t; },
    /* Avanza `ms` segundos; si `mensajes`, el servidor "habla" cada segundo. */
    avanzar(ms, mensajes = false) {
      for (let i = 0; i < ms / 1000; i++) { t += 1000; if (mensajes) sup.heard(); if (f) f(); }
    },
    de(tipo) { return log.filter((l) => l[0] === tipo); },
    dichos() { return log.filter((l) => l[0] === 'say').map((l) => l[2]); },
  };
  return w;
}

test('conexión sana: no reintenta ni dice nada, y pregunta "¿sigues ahí?" cada pocos segundos', () => {
  const m = mundo(); m.sup.start();
  m.avanzar(60000, true);
  assert.equal(m.de('open').length, 0);
  assert.deepEqual(m.dichos(), []);
  assert.ok(m.de('ping').length >= 10, 'ping cada ~4 s: ' + m.de('ping').length);
  assert.equal(m.sup.state, 'ok');
});

test('silencio total de 10 s = caída, aunque el navegador no haya avisado de nada', () => {
  const m = mundo(); m.sup.start();
  m.avanzar(9000);
  assert.equal(m.sup.state, 'ok', 'a los 9 s todavía no');
  m.avanzar(2000);
  assert.equal(m.sup.state, 'lost');
  assert.ok(m.de('open').length >= 1, 'intenta reconectar');
});

test('al caer, la persona lo OYE: se avisa una sola vez tras 3 s y nunca antes', () => {
  const m = mundo(); m.sup.start();
  m.avanzar(2000, true);
  m.sup.closed();
  m.avanzar(2000);
  assert.deepEqual(m.dichos(), [], 'a los 2 s de caída todavía no habla');
  m.avanzar(2000);
  assert.equal(m.dichos().length, 1);
  assert.match(m.dichos()[0], /Perdí la conexión con el servidor/);
  assert.match(m.dichos()[0], /bastón/);
  assert.match(m.dichos()[0], /Revise su conexión/);
  m.avanzar(20000);
  assert.equal(m.dichos().length, 1, 'no repite antes de los 30 s');
});

test('un parpadeo de menos de 3 s no molesta a nadie: ni aviso de caída ni de "recuperada"', () => {
  const m = mundo(); m.sup.start();
  m.avanzar(1000, true);
  m.sup.closed();
  m.avanzar(1000);
  m.sup.heard();
  m.avanzar(10000, true);
  assert.deepEqual(m.dichos(), []);
  assert.equal(m.sup.state, 'ok');
});

test('mientras siga caída recuerda cada 30 s, y al volver lo dice y deja de reintentar', () => {
  const m = mundo(); m.sup.start();
  m.sup.closed();
  m.avanzar(100000);
  const d = m.dichos();
  assert.match(d[0], /Perdí la conexión/);
  assert.ok(d.length >= 4 && d.slice(1).every((x) => /Sigo sin conexión/.test(x) && /Revise su conexión/.test(x)), JSON.stringify(d));
  const abiertos = m.de('open').length;
  m.sup.heard();
  assert.equal(m.dichos().at(-1), 'Conexión recuperada.');
  m.avanzar(30000, true);
  assert.equal(m.de('open').length, abiertos, 'ya conectado: no se vuelve a abrir');
  assert.equal(m.dichos().filter((x) => x === 'Conexión recuperada.').length, 1);
});

test('reintentos con espera creciente: inmediato, 1 s, 2,5 s y luego cada 5 s, redondeado al segundo del vigilante (no martilla al servidor)', () => {
  const m = mundo(); m.sup.start();
  m.avanzar(1000, true);
  m.sup.closed();
  m.avanzar(30000);
  const t0 = m.de('open')[0][1];
  const lapsos = m.de('open').map((o) => o[1] - t0);
  assert.deepEqual(lapsos.slice(0, 5), [0, 1000, 4000, 9000, 14000]);   // los 2,5 s se redondean al siguiente latido de 1 s
});

test('varios cierres seguidos (los dos canales) no reinician el reloj del aviso ni duplican nada', () => {
  const m = mundo(); m.sup.start();
  m.sup.closed(); m.avanzar(1000); m.sup.closed(); m.avanzar(1000); m.sup.closed();
  m.avanzar(1000);
  assert.equal(m.dichos().length, 1, 'avisa a los 3 s contados desde el primer cierre');
});

test('si vuelve a caer después de recuperarse, se avisa de nuevo', () => {
  const m = mundo(); m.sup.start();
  m.sup.closed(); m.avanzar(5000); m.sup.heard();
  m.avanzar(5000, true);
  m.sup.closed(); m.avanzar(5000);
  assert.equal(m.dichos().filter((x) => /Perdí la conexión/.test(x)).length, 2);
});

test('al volver la página al primer plano pregunta de inmediato y, sin respuesta en ~3 s, da la conexión por caída', () => {
  const m = mundo(); m.sup.start();
  m.avanzar(1000, true);
  const antes = m.de('ping').length;
  m.sup.wake();
  assert.equal(m.de('ping').length, antes + 1, 'pregunta ya');
  m.avanzar(2000);
  assert.equal(m.sup.state, 'ok', 'a los 2 s todavía espera');
  m.avanzar(2000);
  assert.equal(m.sup.state, 'lost');
});

test('al volver al primer plano, si el servidor contesta, todo sigue normal', () => {
  const m = mundo(); m.sup.start();
  m.avanzar(5000, true);
  m.sup.wake();
  m.sup.heard();   // el "pong"
  m.avanzar(20000, true);
  assert.equal(m.sup.state, 'ok');
  assert.deepEqual(m.dichos(), []);
});

test('si la página ya está caída, volver al primer plano reintenta ya, sin esperar la pausa', () => {
  const m = mundo(); m.sup.start();
  m.sup.closed(); m.avanzar(3000);
  const antes = m.de('open').length;
  m.sup.wake(); m.avanzar(1000);
  assert.ok(m.de('open').length > antes);
});

test('stop(): ya no vigila, no reintenta ni habla', () => {
  const m = mundo(); m.sup.start();
  m.sup.closed(); m.sup.stop();
  m.avanzar(60000);
  assert.equal(m.de('open').length, 0);
  assert.deepEqual(m.dichos(), []);
});

test('un cierre llegado después de stop() no hace nada (la persona apagó Bili)', () => {
  const m = mundo(); m.sup.start(); m.sup.stop();
  m.sup.closed(); m.avanzar(30000);
  assert.deepEqual(m.dichos(), []);
  assert.equal(m.sup.state, 'ok');
});
