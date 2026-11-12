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
