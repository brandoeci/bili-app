const test = require('node:test');
const assert = require('node:assert/strict');
const V = require('../../web/voice.js');

/* Entorno falso. `escucha` es el guion de lo que "oye" Bili en cada intento de escucha. */
function entorno(escucha = [], opts = {}) {
  const log = [];
  let hablando = false;
  const env = {
    log,
    hablo: [],
    iniciada: null,
    cancelada: 0,
    say: async (text) => {
      hablando = true; log.push('say:' + text); env.hablo.push(text);
      await new Promise((r) => setImmediate(r));
      hablando = false;
    },
    listen: async (ms) => {
      assert.equal(hablando, false, 'Bili empezó a escuchar mientras hablaba');
      log.push('listen:' + ms);
      const next = escucha.shift();
      return next === undefined ? { silence: true } : next;
    },
    whenQuiet: async () => { log.push('quiet'); },
    beep: () => log.push('beep'),
    interrupt: () => log.push('interrupt'),
    findRoute: async (dest) => {
      log.push('find:' + dest);
      return opts.find ? opts.find(dest) : { ok: true, ruta: { destino: dest }, speech: `Encontré ${dest}. ¿Comienzo? Diga sí o no.` };
    },
    startRoute: (r) => { env.iniciada = r; log.push('start'); },
    cancelRoute: () => { env.cancelada++; },
    repeat: () => log.push('repeat'),
    describe: () => log.push('describe'),
    whereText: async () => 'Está en la Carrera 7. Faltan unos 300 metros.',
  };
  return env;
}

const dicho = (text) => ({ text });

test('sí / no / ambiguo', () => {
  for (const t of ['sí', 'Si', 'claro que sí', 'dale', 'listo, comienza', 'OK']) assert.equal(V.parseYesNo(t), 'yes', t);
  for (const t of ['no', 'No, gracias', 'cancelar', 'otro lugar', 'nop']) assert.equal(V.parseYesNo(t), 'no', t);
  for (const t of ['sí no', 'no sí', 'mmm', '', 'el parque']) assert.equal(V.parseYesNo(t), null, t);
});

test('destino: se quitan las muletillas y se conserva el lugar', () => {
  assert.equal(V.cleanDestination('Quiero ir a la Biblioteca Luis Ángel Arango'), 'la Biblioteca Luis Ángel Arango');
  assert.equal(V.cleanDestination('Llévame al Museo del Oro, por favor'), 'Museo del Oro');
  assert.equal(V.cleanDestination('voy para la calle 72 con carrera 10.'), 'la calle 72 con carrera 10');
  assert.equal(V.cleanDestination('Avenida Caracas con calle 26'), 'Avenida Caracas con calle 26', 'no corta una "a" dentro de la palabra');
  assert.equal(V.cleanDestination('a la 93'), 'la 93');
  assert.equal(V.cleanDestination('ir a'), '');
  assert.equal(V.cleanDestination(''), '');
});

test('órdenes durante la ruta', () => {
  assert.equal(V.parseCommand('repite eso'), 'repeat');
  assert.equal(V.parseCommand('repetir'), 'repeat');
  assert.equal(V.parseCommand('dónde estoy'), 'where');
  assert.equal(V.parseCommand('cuánto falta'), 'where');
  assert.equal(V.parseCommand('describe lo que hay'), 'describe');
  assert.equal(V.parseCommand('cancelar la ruta'), 'cancel');
  assert.equal(V.parseCommand('quiero otro destino'), 'newdest');
  assert.equal(V.parseCommand('banana'), null);
});

test('origen dicho: se quitan "estoy en…" y se conserva el lugar', () => {
  assert.equal(V.cleanOrigin('Estoy en la calle 72 con séptima'), 'la calle 72 con séptima');
  assert.equal(V.cleanOrigin('me encuentro en el parque de la 93'), 'el parque de la 93');
  assert.equal(V.cleanOrigin('carrera 7 con calle 45'), 'carrera 7 con calle 45');
  assert.equal(V.cleanOrigin('estoy en'), '');
});

test('sin GPS: pregunta dónde está, busca con eso y sigue como siempre', async () => {
  const pedidos = [];
  const env = entorno([dicho('al Museo del Oro'), dicho('estoy en la calle 72 con séptima'), dicho('sí')], {
    find: (dest) => (pedidos.length ? { ok: true, ruta: { destino: dest }, speech: 'Encontré el museo. ¿Comienzo?' } : { ok: false, needOrigin: true, message: 'No sé dónde está.' }),
  });
  const buscar = env.findRoute;
  env.findRoute = async (dest, origen) => { const r = await buscar(dest); pedidos.push([dest, origen]); return r; };
  const out = await V.createDialog(env).start();
  assert.equal(out, 'started');
  assert.deepEqual(pedidos, [['Museo del Oro', undefined], ['Museo del Oro', 'la calle 72 con séptima']]);
  assert.ok(env.hablo.some((t) => t.startsWith('No sé dónde está. Para calcular la ruta, dígame dónde está ahora')));
});

test('sin GPS y sin respuesta sobre dónde está: no inventa la ruta', async () => {
  const env = entorno([dicho('al Museo del Oro')], { find: () => ({ ok: false, needOrigin: true }) });
  const out = await V.createDialog(env).start();
  assert.equal(out, 'no-origin');
  assert.equal(env.iniciada, null);
  assert.ok(env.hablo.at(-1).startsWith('Sin saber dónde está no puedo calcular la ruta.'));
});

test('camino feliz: pregunta, busca, confirma y comienza', async () => {
  const env = entorno([dicho('quiero ir al Museo del Oro'), dicho('sí')]);
  const out = await V.createDialog(env).start();
  assert.equal(out, 'started');
  assert.deepEqual(env.iniciada, { destino: 'Museo del Oro' });
  const i = (s) => env.log.findIndex((l) => l.startsWith(s));
  assert.ok(i('say:¿A dónde quiere ir?') < i('beep') && i('beep') < i('listen:8000'), 'pregunta, tono y luego escucha');
  assert.ok(env.log.includes('find:Museo del Oro'));
});

test('si la persona no dice nada: no se insiste, no se busca nada y se explica cómo volver a empezar', async () => {
  const env = entorno([{ silence: true }]);
  const out = await V.createDialog(env).start();
  assert.equal(out, 'silence');
  assert.equal(env.log.filter((l) => l.startsWith('listen')).length, 1, 'una sola escucha, sin reintentos');
  assert.ok(!env.log.some((l) => l.startsWith('find')));
  assert.match(env.hablo.at(-1), /toque la pantalla/i);
});

test('se da tiempo de verdad: 8 s para el destino y 7 s para confirmar', async () => {
  const env = entorno([dicho('Parque Simón Bolívar'), dicho('sí')]);
  await V.createDialog(env).start();
  assert.ok(env.log.includes('listen:8000'));
  assert.ok(env.log.includes('listen:7000'));
});

test('sin respuesta a la confirmación nunca se comienza', async () => {
  const env = entorno([dicho('Museo del Oro'), { silence: true }]);
  const out = await V.createDialog(env).start();
  assert.equal(out, 'silence');
  assert.equal(env.iniciada, null);
  assert.equal(env.log.includes('start'), false);
});

test('respuesta incomprensible a la confirmación: se repite una vez y luego no se comienza', async () => {
  const env = entorno([dicho('Museo del Oro'), dicho('mmm bananas'), dicho('eh quizá')]);
  const out = await V.createDialog(env).start();
  assert.equal(out, 'silence');
  assert.equal(env.hablo.filter((t) => t === 'No le entendí. Diga sí o no.').length, 1);
  assert.equal(env.iniciada, null);
});

test('si dice que no, vuelve a preguntar el destino', async () => {
  const env = entorno([dicho('Museo del Oro'), dicho('no'), dicho('Biblioteca Nacional'), dicho('sí')]);
  const out = await V.createDialog(env).start();
  assert.equal(out, 'started');
  assert.deepEqual(env.iniciada, { destino: 'Biblioteca Nacional' });
  assert.ok(env.hablo.includes('Está bien. Dígame el destino otra vez, después del tono.'));
});

test('lugar no encontrado: avisa el motivo y reintenta, con un tope', async () => {
  const find = () => ({ ok: false, message: 'No encontré ese lugar.' });
  const env = entorno([dicho('xyzxyz'), dicho('xyzxyz'), dicho('xyzxyz')], { find });
  const out = await V.createDialog(env).start();
  assert.equal(out, 'failed');
  assert.equal(env.hablo.filter((t) => t === 'No encontré ese lugar.').length, 2);
  assert.match(env.hablo.at(-1), /toque la pantalla/i);
});

test('una alerta urgente corta la escucha: se espera a que termine y se vuelve a escuchar', async () => {
  const env = entorno([{ interrupted: true }, dicho('Museo del Oro'), dicho('sí')]);
  const out = await V.createDialog(env).start();
  assert.equal(out, 'started');
  assert.ok(env.log.filter((l) => l === 'quiet').length >= 2);
  assert.equal(env.log.filter((l) => l === 'listen:8000').length, 2, 'volvió a escuchar el destino');
});

test('si las alertas no paran, se rinde sin quedarse escuchando para siempre', async () => {
  const env = entorno(Array(10).fill({ interrupted: true }));
  const out = await V.createDialog(env).start();
  assert.equal(out, 'silence');
  assert.ok(env.log.filter((l) => l.startsWith('listen')).length <= V.T.maxInterrupts + 1);
});

test('no se puede escuchar si no hay micrófono o permiso', async () => {
  const env = entorno([{ error: 'not-allowed' }]);
  const out = await V.createDialog(env).start();
  assert.equal(out, 'error');
  assert.match(env.hablo.at(-1), /toque la pantalla/i);
});

test('un toque sin ruta activa pregunta el destino y calla lo no urgente', async () => {
  const env = entorno([dicho('Museo del Oro'), dicho('claro')]);
  const out = await V.createDialog(env).onTap();
  assert.equal(out, 'started');
  assert.equal(env.log[0], 'interrupt');
});

async function conRutaActiva(escucha) {
  const env = entorno([dicho('Museo del Oro'), dicho('sí'), ...escucha]);
  const d = V.createDialog(env);
  await d.start();
  env.log.length = 0; env.hablo.length = 0;
  return { env, d };
}

test('durante la ruta: repetir, dónde estoy, describir', async () => {
  const { env, d } = await conRutaActiva([dicho('repite'), dicho('dónde estoy'), dicho('describe')]);
  assert.equal(await d.onTap(), 'repeat');
  assert.equal(await d.onTap(), 'where');
  assert.equal(await d.onTap(), 'describe');
  assert.ok(env.log.includes('repeat') && env.log.includes('describe'));
  assert.ok(env.hablo.includes('Está en la Carrera 7. Faltan unos 300 metros.'));
});

test('durante la ruta: cancelar', async () => {
  const { env, d } = await conRutaActiva([dicho('cancelar')]);
  assert.equal(await d.onTap(), 'cancel');
  assert.equal(env.cancelada, 1);
  assert.equal(d.navigating, false);
  assert.ok(env.hablo.includes('Ruta cancelada.'));
});

test('durante la ruta: un toque sin decir nada no genera ningún mensaje', async () => {
  const { env, d } = await conRutaActiva([{ silence: true }]);
  assert.equal(await d.onTap(), 'silence');
  assert.deepEqual(env.hablo, []);
});

test('durante la ruta: una orden desconocida explica qué se puede decir', async () => {
  const { env, d } = await conRutaActiva([dicho('banana')]);
  assert.equal(await d.onTap(), 'unknown');
  assert.match(env.hablo[0], /repetir.*cancelar/);
});

test('durante la ruta: nuevo destino no cancela la ruta vieja hasta confirmar la nueva', async () => {
  const { env, d } = await conRutaActiva([dicho('nuevo destino'), dicho('Biblioteca Nacional'), dicho('sí')]);
  assert.equal(await d.onTap(), 'started');
  assert.deepEqual(env.iniciada, { destino: 'Biblioteca Nacional' });
  assert.equal(env.cancelada, 0);
});

test('al terminar la ruta, un toque vuelve a preguntar el destino', async () => {
  const env = entorno([dicho('Museo del Oro'), dicho('sí'), dicho('Biblioteca Nacional'), dicho('sí')]);
  const d = V.createDialog(env);
  await d.start();
  d.routeEnded();
  assert.equal(await d.onTap(), 'started');
});

test('un toque mientras hay un diálogo en curso no abre una segunda escucha', async () => {
  const env = entorno([dicho('Museo del Oro'), dicho('sí')]);
  const d = V.createDialog(env);
  const primero = d.start();
  const segundo = await d.onTap();
  assert.equal(segundo, 'busy');
  await primero;
  assert.equal(env.log.filter((l) => l.startsWith('listen')).length, 2);
});

test('una ruta iniciada por otro camino también escucha órdenes con el toque', async () => {
  const env = entorno([dicho('cancelar')]);
  const d = V.createDialog(env);
  d.routeStarted();
  assert.equal(await d.onTap(), 'cancel');
  assert.equal(env.cancelada, 1);
});

test('"sin destino" es una respuesta válida: camino libre, sin buscar ruta ni confirmar', async () => {
  for (const frase of ['sin destino', 'ninguno', 'solo quiero caminar', 'no tengo ruta', 'sin ruta']) {
    const env = entorno([dicho(frase)]);
    const out = await V.createDialog(env).start();
    assert.equal(out, 'free', frase);
    assert.ok(!env.log.some((l) => l.startsWith('find')), frase);
    assert.match(env.hablo.at(-1), /camino libre.*obstáculos/i);
    assert.equal(env.iniciada, null);
  }
});

test('un destino real no se confunde con "sin destino"', () => {
  for (const t of ['Museo del Oro', 'la calle 72 con carrera 10', 'Parque Nacional', 'Biblioteca Luis Ángel Arango']) assert.equal(V.parseFree(t), false, t);
});

test('abreviaturas de dirección se dicen completas', () => {
  assert.equal(V.speakable('Cra. 6 #15-88'), 'Carrera 6 número 15-88');
  assert.equal(V.speakable('Cl 72 & Ak 7'), 'Calle 72 con Avenida Carrera 7');
  assert.equal(V.speakable('Av. Caracas con Cl. 26'), 'Avenida Caracas con Calle 26');
  assert.equal(V.speakable('Carrera 7'), 'Carrera 7');
  assert.equal(V.speakable('Cristo Rey'), 'Cristo Rey', 'no toca palabras que solo empiezan igual');
});

/* ---------- Menú de dos dedos: "¿nuevo destino o apagar?" ---------- */

test('menú: qué se entiende de lo que dice la persona', () => {
  const casos = [
    ['apagar', 'off'], ['apagado', 'off'], ['apaga la guía', 'off'], ['Apagar.', 'off'], ['cancelar', 'off'], ['terminar', 'off'],
    ['nuevo destino', 'newdest'], ['otro destino', 'newdest'], ['quiero cambiar de ruta', 'newdest'], ['una nueva ruta', 'newdest'],
    ['no apagar', null],                  // negación: ante la duda no se apaga
    ['no quiero apagar', null],
    ['apagar y nuevo destino', null],     // las dos cosas: no se adivina
    ['hola', null], ['', null], [undefined, null],
  ];
  for (const [texto, esperado] of casos) assert.equal(V.parseMenu(texto), esperado, JSON.stringify(texto));
});

test('menú: "apagar" dice que apaga, y solo después apaga todo', async () => {
  const { env, d } = await conRutaActiva([dicho('apagar')]);
  let apagado = 0;
  env.shutdown = () => { apagado++; env.log.push('shutdown'); };
  assert.equal(await d.onMenu(), 'off');
  assert.equal(apagado, 1);
  const i = env.log.indexOf('say:Guía apagada.');
  assert.ok(i >= 0 && env.log.indexOf('shutdown') > i, 'primero lo dice, después apaga');
  assert.equal(env.log[0], 'interrupt', 'lo primero es callar lo que se estuviera diciendo');
  assert.ok(env.hablo[0].includes('Nuevo destino o apagar'));
  assert.equal(d.navigating, false);
});

test('menú: "nuevo destino" pregunta el destino y no cancela la ruta vieja hasta confirmar la nueva', async () => {
  const { env, d } = await conRutaActiva([dicho('nuevo destino'), dicho('Biblioteca Nacional'), dicho('sí')]);
  let apagado = 0;
  env.shutdown = () => { apagado++; };
  assert.equal(await d.onMenu(), 'newdest');
  assert.deepEqual(env.iniciada, { destino: 'Biblioteca Nacional' });
  assert.equal(apagado, 0);
  assert.equal(env.cancelada, 0);
});

test('menú: sin respuesta o sin entender, la guía NO se apaga', async () => {
  for (const escucha of [[], [dicho('mmm no sé')], [dicho('no apagar')], [dicho('apagar nuevo destino')]]) {
    const { env, d } = await conRutaActiva(escucha);
    let apagado = 0;
    env.shutdown = () => { apagado++; };
    const r = await d.onMenu();
    assert.ok(['silence', 'unknown'].includes(r), r);
    assert.equal(apagado, 0, JSON.stringify(escucha));
    assert.equal(env.cancelada, 0);
    assert.equal(d.navigating, true);
    assert.ok(env.hablo.some((t) => t.includes('Sigo guiándolo')));
  }
});

test('menú: si no se puede escuchar, avisa cómo reintentar y no apaga', async () => {
  const { env, d } = await conRutaActiva([{ error: 'not-allowed' }]);
  let apagado = 0;
  env.shutdown = () => { apagado++; };
  assert.equal(await d.onMenu(), 'error');
  assert.equal(apagado, 0);
  assert.ok(env.hablo.some((t) => t.includes('dos dedos')));
});

test('menú: sin ruta activa, dos dedos hacen lo mismo que un toque (preguntar el destino)', async () => {
  const env = entorno([dicho('Museo del Oro'), dicho('sí')]);
  const d = V.createDialog(env);
  assert.equal(await d.onMenu(), 'started');
  assert.deepEqual(env.iniciada, { destino: 'Museo del Oro' });
});

test('menú: con un diálogo en curso no abre una segunda escucha', async () => {
  const env = entorno([dicho('Museo del Oro'), dicho('sí')]);
  const d = V.createDialog(env);
  const primero = d.start();
  assert.equal(await d.onMenu(), 'busy');
  await primero;
  assert.equal(env.log.filter((l) => l.startsWith('listen')).length, 2);
});

test('menú: una alerta urgente que corta la escucha no se pierde ni apaga nada', async () => {
  const { env, d } = await conRutaActiva([{ interrupted: true }, dicho('nuevo destino'), dicho('Biblioteca Nacional'), dicho('sí')]);
  assert.equal(await d.onMenu(), 'newdest');
  assert.equal(env.log.filter((l) => l.startsWith('listen')).length >= 3, true);
});

/* ---------- Gesto de mantener dos dedos ---------- */

function reloj() {
  let t = 0; const pend = [];
  return {
    setT: (f, ms) => { const x = { f, at: t + ms, vivo: true }; pend.push(x); return x; },
    clearT: (x) => { if (x) x.vivo = false; },
    now: () => t,
    avanzar(ms) { t += ms; for (const x of pend.filter((p) => p.vivo && p.at <= t).sort((a, b) => a.at - b.at)) { x.vivo = false; x.f(); } },
  };
}

test('dos dedos: pitido al segundo y disparo a los dos segundos, una sola vez', () => {
  const r = reloj(); const ev = [];
  const h = V.createHold({ onWarn: () => ev.push('aviso'), onFire: () => ev.push('menu'), setT: r.setT, clearT: r.clearT, now: r.now });
  h.touches(1); h.touches(2);
  r.avanzar(900); assert.deepEqual(ev, []);
  r.avanzar(200); assert.deepEqual(ev, ['aviso']);
  r.avanzar(800); assert.deepEqual(ev, ['aviso']);            // 1900 ms: todavía no
  r.avanzar(100); assert.deepEqual(ev, ['aviso', 'menu']);    // 2000 ms: se abre el menú
  r.avanzar(5000); assert.deepEqual(ev, ['aviso', 'menu'], 'no se repite mientras sigan los dedos');
});

test('dos dedos: si suelta antes de tiempo, no pasa nada (ni aviso ni menú)', () => {
  const r = reloj(); const ev = [];
  const h = V.createHold({ onWarn: () => ev.push('aviso'), onFire: () => ev.push('menu'), setT: r.setT, clearT: r.clearT, now: r.now });
  h.touches(2); r.avanzar(600); h.touches(1); r.avanzar(5000);
  assert.deepEqual(ev, []);
  h.touches(0);
});

test('dos dedos: un tercer dedo cancela (no es el gesto), y se puede volver a empezar', () => {
  const r = reloj(); const ev = [];
  const h = V.createHold({ onWarn: () => ev.push('aviso'), onFire: () => ev.push('menu'), setT: r.setT, clearT: r.clearT, now: r.now });
  h.touches(2); r.avanzar(1500); h.touches(3); r.avanzar(3000);
  assert.deepEqual(ev, ['aviso']);   // el aviso ya había sonado, pero el menú no se abre
  h.touches(0); h.touches(2); r.avanzar(2000);
  assert.deepEqual(ev, ['aviso', 'aviso', 'menu']);
});

test('dos dedos: un solo dedo (un toque normal) nunca activa el gesto', () => {
  const r = reloj(); const ev = [];
  const h = V.createHold({ onWarn: () => ev.push('aviso'), onFire: () => ev.push('menu'), setT: r.setT, clearT: r.clearT, now: r.now });
  h.touches(1); r.avanzar(10000); h.touches(0);
  assert.deepEqual(ev, []);
});

test('dos dedos: el "click" que manda el navegador al soltar se ignora justo después del gesto, no antes ni mucho después', () => {
  const r = reloj();
  const h = V.createHold({ setT: r.setT, clearT: r.clearT, now: r.now });
  assert.equal(h.suppressClick(), false, 'antes de cualquier gesto, los toques funcionan');
  h.touches(2); r.avanzar(2000);
  assert.equal(h.suppressClick(), true);
  r.avanzar(1300);
  assert.equal(h.suppressClick(), false, 'pasado un momento, un toque normal vuelve a funcionar');
});

/* ---------- Errores: lo técnico no se lee en voz alta ---------- */

test('un error técnico no se dice: "Load failed" y compañía se callan', () => {
  for (const err of [new Error('Load failed'), new TypeError('Failed to fetch'), new Error('NetworkError when attempting to fetch resource.'),
    new Error('The operation couldn\u2019t be completed. (kCFErrorDomainCFNetwork error 2.)'), new Error('HTTP 500'), null, undefined, 'Load failed', {}]) {
    assert.equal(V.mensajeDeError(err), null, String(err && err.message || err));
  }
});

test('un mensaje que el servidor escribió para la persona sí se dice', () => {
  const e = new Error('No encontré ese lugar'); e.paraLaPersona = true;
  assert.equal(V.mensajeDeError(e), 'No encontré ese lugar');
  const vacio = new Error('   '); vacio.paraLaPersona = true;
  assert.equal(V.mensajeDeError(vacio), null, 'un mensaje vacío no se dice');
  const falso = new Error('Load failed'); falso.paraLaPersona = 'sí';
  assert.equal(V.mensajeDeError(falso), null, 'solo la marca exacta cuenta');
});

test('si buscar la ruta falla por algo técnico, Bili dice "No le entendí. Repita después del tono." y vuelve a escuchar', async () => {
  const env = entorno([dicho('Museo del Oro'), dicho('Museo del Oro')], { find: () => ({ ok: false }) });  // sin mensaje: error técnico
  const d = V.createDialog(env);
  await d.start();
  assert.equal(env.hablo.filter((t) => t === 'No le entendí. Repita después del tono.').length >= 1, true, JSON.stringify(env.hablo));
  assert.ok(!env.hablo.some((t) => /load failed|failed|error|http/i.test(t)), 'nada técnico en voz alta');
  assert.equal(env.log.filter((l) => l.startsWith('listen')).length >= 2, true, 'vuelve a escuchar');
});

test('si el servidor sí dio un motivo claro, se dice ese (no el genérico)', async () => {
  const env = entorno([dicho('Chía'), dicho('sí')], { find: (dest) => dest === 'Chía'
    ? { ok: false, message: 'Encontré Chía, pero queda a 25 kilómetros. Es demasiado lejos para ir a pie.' } : { ok: true, ruta: {}, speech: 'x' } });
  const d = V.createDialog(env);
  await d.start();
  assert.ok(env.hablo.some((t) => t.includes('demasiado lejos para ir a pie')));
  assert.ok(!env.hablo.includes('No le entendí. Repita después del tono.') || env.hablo.indexOf('No le entendí. Repita después del tono.') > env.hablo.findIndex((t) => t.includes('demasiado lejos')));
});

test('errores de la petición de ruta: solo se dicen los códigos con un motivo escrito para la persona', () => {
  for (const status of [404, 422, 429, 502]) assert.equal(V.mensajeDeError(V.errorDeRuta(status, 'No encontré ese lugar')), 'No encontré ese lugar', String(status));
  for (const status of [400, 401, 403, 500, 503, 504]) assert.equal(V.mensajeDeError(V.errorDeRuta(status, 'Las rutas no están configuradas en el servidor')), null, String(status));
  assert.equal(V.mensajeDeError(V.errorDeRuta(422, { loc: ['body'], msg: 'campo requerido' })), null, 'un detalle que no es texto (validación) no se lee');
  assert.equal(V.mensajeDeError(V.errorDeRuta(404, undefined)), null);
});

/* ---------- Si falla buscar la ruta (sin conexión, sin GPS...) ---------- */

function errorGeo(code) {  // así llega un GeolocationPositionError del navegador
  const e = new Error('geo'); e.code = code; e.PERMISSION_DENIED = 1; e.POSITION_UNAVAILABLE = 2; e.TIMEOUT = 3; return e;
}

test('sin conexión: ningún error técnico de red llega a la voz (el caso real del iPhone)', () => {
  for (const err of [new TypeError('Load failed'), new TypeError('Failed to fetch'), new Error('Load failed'),
    new TypeError('NetworkError when attempting to fetch resource.'), new DOMException('The network connection was lost.', 'NetworkError'),
    new DOMException('The operation was aborted.', 'AbortError')]) {
    assert.equal(V.mensajeDeFalloDeRuta(err), null, `${err.name}: ${err.message}`);
  }
});

test('ubicación: cada fallo tiene su mensaje claro', () => {
  assert.match(V.mensajeDeFalloDeRuta(errorGeo(1)), /permiso para usar la ubicación/);
  assert.match(V.mensajeDeFalloDeRuta(errorGeo(2)), /No pude obtener su ubicación/);
  assert.match(V.mensajeDeFalloDeRuta(errorGeo(3)), /No pude obtener su ubicación/);
  assert.match(V.mensajeDeFalloDeRuta(new Error('sin-gps')), /no tiene ubicación disponible/);
});

test('una excepción del navegador con "code" que NO es de ubicación no se confunde con un fallo de GPS', () => {
  const e = new DOMException('The network connection was lost.', 'NetworkError');   // trae code 19
  assert.equal(typeof e.code, 'number');
  assert.equal(V.mensajeDeFalloDeRuta(e), null);
});

test('el motivo escrito por el servidor para la persona sí se dice', () => {
  assert.equal(V.mensajeDeFalloDeRuta(V.errorDeRuta(404, 'No encontré ese lugar')), 'No encontré ese lugar');
});

test('de punta a punta: sin conexión, la persona dice el destino y oye "No le entendí. Repita después del tono."', async () => {
  const env = entorno([dicho('Museo del Oro'), dicho('Museo del Oro'), dicho('Museo del Oro')], {
    find: () => { const m = V.mensajeDeFalloDeRuta(new TypeError('Load failed')); return { ok: false, message: m ? V.speakable(m) : undefined }; },
  });
  const d = V.createDialog(env);
  await d.start();
  assert.ok(env.hablo.includes('No le entendí. Repita después del tono.'), JSON.stringify(env.hablo));
  assert.ok(!env.hablo.some((t) => /load failed|failed|network/i.test(t)), 'nada técnico en voz alta');
});

/* ---------- El diálogo avisa cuándo está ocupado ---------- */

test('el diálogo avisa que está ocupado mientras dura y que terminó al acabar (las alertas normales esperan)', async () => {
  const env = entorno([dicho('Museo del Oro'), dicho('sí')]);
  const estados = [];
  env.busy = (b) => estados.push(b);
  const d = V.createDialog(env);
  await d.start();
  assert.equal(estados[0], true);
  assert.equal(estados.at(-1), false, 'al terminar el diálogo queda libre');
  assert.equal(estados.filter((x) => x === true).length, estados.filter((x) => x === false).length, 'cada "ocupado" tiene su "libre"');
});

test('si el diálogo falla a la mitad, igual queda libre (no se quedan callando las alertas para siempre)', async () => {
  const env = entorno([dicho('Museo del Oro')], { find: () => { throw new Error('boom'); } });
  const estados = [];
  env.busy = (b) => estados.push(b);
  const d = V.createDialog(env);
  await assert.rejects(() => d.start());
  assert.equal(estados.at(-1), false);
});

test('un toque mientras el diálogo ya está ocupado no lo marca ocupado dos veces', async () => {
  const env = entorno([dicho('Museo del Oro'), dicho('sí')]);
  const estados = [];
  env.busy = (b) => estados.push(b);
  const d = V.createDialog(env);
  const primero = d.start();
  await d.onTap();
  await primero;
  assert.equal(estados.filter((x) => x === true).length, 1);
});
