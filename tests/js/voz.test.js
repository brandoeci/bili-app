const test = require('node:test');
const assert = require('node:assert/strict');
const Z = require('../../web/voz.js');

/* Mundo falso: una voz que solo avanza cuando yo digo (`acabar`), reloj y temporizadores controlados. */
function mundo(cfg) {
  let t = 0, nextId = 1;
  const timers = [];
  const dichas = [];        // lo que la voz empezó a decir, en orden ('<corte>' cuando se cancela)
  let alTerminar = null;    // el "terminé" de la frase en curso
  const todos = [];         // todos los "terminé" entregados (para probar los tardíos)
  const efectos = { vibro: 0, cortoEscucha: 0 };
  const synth = {
    speak: (texto, done) => { dichas.push(texto); alTerminar = done; todos.push(done); },
    cancel: () => { dichas.push('<corte>'); },
  };
  const voz = Z.create({
    synth, now: () => t,
    setTimeout: (f, ms) => { const x = { id: nextId++, f, at: t + ms, vivo: true }; timers.push(x); return x.id; },
    clearTimeout: (id) => { const x = timers.find((y) => y.id === id); if (x) x.vivo = false; },
    vibrate: () => efectos.vibro++, interruptListen: () => efectos.cortoEscucha++, cfg,
  });
  return {
    voz, dichas, efectos,
    /* La voz termina la frase que estaba diciendo. */
    acabar() { const f = alTerminar; alTerminar = null; if (f) f(); },
    /* Termina todas las frases hasta que no quede nada por decir. */
    acabarTodo() { for (let n = 0; n < 50 && alTerminar; n++) this.acabar(); },
    /* El "terminé" tardío de una frase que ya se canceló (el navegador lo manda después). */
    /* Llama al "terminé" número n entregado (0 = el primero): simula el aviso tardío de una frase cancelada. */
    terminarViejo(n) { todos[n](); },
    avanzar(ms) { t += ms; for (const x of timers.filter((y) => y.vivo && y.at <= t)) { x.vivo = false; x.f(); } },
    get t() { return t; },
  };
}

test('partir: frases, y las muy cortas o las abreviaturas no rompen el texto', () => {
  assert.deepEqual(Z.partir('Encontré el Museo del Oro. Ruta a pie de unas 8 cuadras. ¿Comienzo? Diga sí o no.'),
    ['Encontré el Museo del Oro.', 'Ruta a pie de unas 8 cuadras.', '¿Comienzo?', 'Diga sí o no.'].reduce((a, x) => (a.length && a[a.length - 1].length < 14 ? (a[a.length - 1] += ' ' + x, a) : (a.push(x), a)), []));
  assert.deepEqual(Z.partir('Cra. 7 con Calle 72. Siga derecho.'), ['Cra. 7 con Calle 72.', 'Siga derecho.']);
  assert.deepEqual(Z.partir('  Hola  '), ['Hola']);
  assert.deepEqual(Z.partir(''), []);
  assert.deepEqual(Z.partir(null), []);
});

test('un mensaje largo se dice entero, frase por frase y en orden', async () => {
  const m = mundo();
  const fin = m.voz.sayAndWait('Primera frase larga de prueba. Segunda frase larga de prueba. Tercera frase larga de prueba.');
  let listo = false; fin.then(() => { listo = true; });
  m.acabar(); m.acabar();
  await Promise.resolve();
  assert.equal(listo, false, 'todavía falta la última frase');
  m.acabar();
  await fin;
  assert.deepEqual(m.dichas, ['Primera frase larga de prueba.', 'Segunda frase larga de prueba.', 'Tercera frase larga de prueba.']);
});

test('una alerta normal que llega a mitad de un mensaje NO lo corta y espera a que termine', () => {
  const m = mundo();
  m.voz.speak('Un mensaje con dos frases largas. Aquí va la segunda frase larga.', 'P1');
  m.voz.speak('Cuidado, persona a la izquierda.', 'P1');
  assert.deepEqual(m.dichas, ['Un mensaje con dos frases largas.']);
  m.acabar();
  assert.equal(m.dichas.at(-1), 'Aquí va la segunda frase larga.', 'no se cuela entre las frases');
  m.acabar();
  assert.equal(m.dichas.at(-1), 'Cuidado, persona a la izquierda.');
  assert.ok(!m.dichas.includes('<corte>'));
});

test('lo urgente (P0) espera al final de la frase en curso, se dice, y el mensaje sigue desde donde iba', () => {
  const m = mundo();
  m.voz.speak('Encontré el Museo del Oro. Ruta a pie de unas ocho cuadras. Desea comenzar ahora.', 'P1', true, null, { lane: 'dialogo' });
  m.voz.speak('Alto. Obstáculo al frente.', 'P0');
  assert.deepEqual(m.dichas, ['Encontré el Museo del Oro.'], 'la frase en curso no se corta');
  m.acabar();
  assert.equal(m.dichas.at(-1), 'Alto. Obstáculo al frente.');
  m.acabar();   // "Alto." es corta y se pega a la siguiente: una sola frase
  assert.equal(m.dichas.at(-1), 'Ruta a pie de unas ocho cuadras.', 'el diálogo continúa: ninguna frase se pierde');
  m.acabar();
  assert.equal(m.dichas.at(-1), 'Desea comenzar ahora.');
  assert.ok(!m.dichas.includes('<corte>'));
  assert.equal(m.efectos.vibro, 1);
});

test('si la frase en curso es muy larga y lo urgente espera demasiado, se corta y esa frase se REPITE entera después', () => {
  const m = mundo();
  m.voz.speak('Una frase muy larga que no termina nunca. Y otra más.', 'P1');
  m.voz.speak('Alto ahora.', 'P0');
  m.avanzar(2000);
  assert.ok(!m.dichas.includes('<corte>'), 'a los 2 s todavía espera');
  m.avanzar(600);
  assert.deepEqual(m.dichas.slice(-2), ['<corte>', 'Alto ahora.']);
  m.acabar();
  assert.equal(m.dichas.at(-1), 'Una frase muy larga que no termina nunca.', 'la frase cortada vuelve entera, no se da por dicha');
  m.acabar();
  assert.equal(m.dichas.at(-1), 'Y otra más.');
});

test('el aviso tardío de una frase cancelada no confunde a la cola', () => {
  const m = mundo();
  m.voz.speak('Una frase muy larga que no termina nunca. Y otra más.', 'P1');
  m.voz.speak('Alto ahora.', 'P0');
  m.avanzar(3000);                       // se corta la frase larga y suena lo urgente
  const antes = m.dichas.length;
  m.terminarViejo(0);                    // el navegador avisa, tarde, que la frase cortada "terminó"
  assert.equal(m.dichas.length, antes, 'ese aviso no hace avanzar nada ni da la frase por dicha');
  m.acabar();                            // termina de verdad "Alto ahora."
  assert.equal(m.dichas.at(-1), 'Una frase muy larga que no termina nunca.', 'y la frase cortada se repite entera');
});

test('lo que NO es interrumpible (mensajes del sistema) nunca se corta, ni por lo urgente', () => {
  const m = mundo();
  m.voz.speak('Iniciando el sistema con calma total.', 'P1', false);
  m.voz.speak('Alto ahora.', 'P0');
  m.avanzar(10000);
  assert.ok(!m.dichas.includes('<corte>'));
  m.acabar();
  assert.equal(m.dichas.at(-1), 'Alto ahora.');
});

test('lo urgente no borra las frases del diálogo que esperaban; sí borra alertas normales viejas', async () => {
  const m = mundo();
  m.voz.speak('Mensaje que ya está sonando ahora mismo.', 'P1');
  const pregunta = m.voz.sayAndWait('Encontré el destino. ¿Comienzo? Diga sí o no.', 'P1', { lane: 'dialogo' });
  m.voz.speak('Alerta normal vieja que espera turno.', 'P1');
  m.voz.speak('Alto ahora.', 'P0');
  assert.deepEqual(m.voz.pendientes.filter((x) => /Alerta normal vieja/.test(x)), [], 'la alerta normal vieja se descartó');
  assert.ok(m.voz.pendientes.some((x) => /Encontré el destino/.test(x)), 'la pregunta del diálogo se conserva');
  let dicha = false; pregunta.then(() => { dicha = true; });
  m.acabarTodo();
  await pregunta;
  assert.equal(dicha, true);
  assert.ok(m.dichas.includes('Diga sí o no.') || m.dichas.some((d) => /Diga sí o no/.test(d)), 'la pregunta se dijo completa');
});

test('el diálogo es atómico: mientras dura, una alerta normal del detector espera y no se cuela entre sus frases', () => {
  const m = mundo();
  m.voz.setDialogBusy(true);
  m.voz.speak('Alerta normal del detector ahora.', 'P1');
  m.voz.speak('Primera frase del diálogo en curso. Segunda frase del diálogo en curso.', 'P1', true, null, { lane: 'dialogo' });
  assert.deepEqual(m.dichas, ['Primera frase del diálogo en curso.']);
  m.acabar();
  assert.equal(m.dichas.at(-1), 'Segunda frase del diálogo en curso.');
  m.acabar();
  assert.equal(m.dichas.length, 2, 'con el diálogo activo, la alerta sigue esperando');
  m.voz.setDialogBusy(false);
  assert.equal(m.dichas.at(-1), 'Alerta normal del detector ahora.', 'al terminar el diálogo, se dice');
});

test('mientras la persona habla, solo lo urgente suena; lo normal espera a que termine de hablar', () => {
  const m = mundo();
  m.voz.setListening(true);
  m.voz.speak('Alto ahora.', 'P0');
  assert.deepEqual(m.dichas, ['Alto ahora.']);
  assert.equal(m.efectos.cortoEscucha, 1, 'y corta la escucha para que la persona lo oiga');
  m.acabar();
  m.voz.speak('Aviso normal mientras escucha.', 'P1');
  assert.equal(m.dichas.length, 1, 'escuchando: lo normal espera');
  m.voz.setListening(false);
  assert.equal(m.dichas.at(-1), 'Aviso normal mientras escucha.');
});

test('lo urgente que espera detrás de un mensaje largo NO caduca (mejor tarde que nunca)', () => {
  const m = mundo();
  m.voz.speak('Iniciando el sistema con calma total.', 'P1', false);
  m.voz.speak('Alto ahora.', 'P0');
  m.avanzar(60000);
  m.acabar();
  assert.equal(m.dichas.at(-1), 'Alto ahora.');
});

test('un mensaje que ya empezó termina antes que otro nuevo del mismo nivel, aunque lleguen en el mismo instante', () => {
  const m = mundo();   // reloj congelado: todo llega "al mismo tiempo"
  m.voz.speak('Mensaje uno primera frase larga. Mensaje uno segunda frase larga.', 'P1');
  m.voz.speak('Mensaje dos, completamente distinto.', 'P1');
  m.acabar();
  assert.equal(m.dichas.at(-1), 'Mensaje uno segunda frase larga.');
});

test('la persona toca para hablar: Bili se calla a mitad de frase y nada queda colgado', async () => {
  const m = mundo();
  const dicho = m.voz.sayAndWait('Una frase que la persona va a interrumpir. Y otra.', 'P1');
  const espera = m.voz.sayAndWait('Otro mensaje en cola, nunca llega a sonar.', 'P1');
  m.voz.interruptSoft();
  assert.equal(m.dichas.at(-1), '<corte>');
  await Promise.all([dicho, espera]);   // si alguno quedara colgado, esta prueba no termina
  assert.deepEqual(m.voz.pendientes, []);
});

test('lo urgente no se corta por interruptSoft: la persona tocó, pero un aviso de peligro sigue', () => {
  const m = mundo();
  m.voz.speak('Alto ahora.', 'P0');
  m.voz.interruptSoft();
  assert.ok(!m.dichas.includes('<corte>'));
});

test('un aviso normal que esperó demasiado sin empezar caduca; uno del diálogo no', () => {
  const m = mundo();
  m.voz.speak('Mensaje en curso de larga duración total.', 'P1');
  m.voz.speak('Aviso normal que se queda esperando.', 'P1');
  m.voz.speak('Frase del diálogo que también espera.', 'P1', true, null, { lane: 'dialogo' });
  m.avanzar(5000);
  m.acabar();   // termina el primero
  assert.equal(m.dichas.at(-1), 'Frase del diálogo que también espera.', 'el diálogo no caduca');
  m.acabar();
  assert.ok(!m.dichas.includes('Aviso normal que se queda esperando.'), 'el aviso normal caducó: ya no es actual');
});

test('detector: un aviso urgente nuevo reemplaza al urgente que esperaba; no al que ya suena', () => {
  const m = mundo();
  const D = { lane: 'deteccion' };
  m.voz.speak('Cuidado: perro a su derecha, muy cerca.', 'P0', true, null, D);
  m.voz.speak('Cuidado: gato a su derecha, muy cerca.', 'P0', true, null, D);
  m.voz.speak('Cuidado: perro al frente, muy cerca.', 'P0', true, null, D);
  assert.deepEqual(m.voz.pendientes, ['Cuidado: perro al frente, muy cerca.']);
  m.acabarTodo();
  assert.deepEqual(m.dichas, ['Cuidado: perro a su derecha, muy cerca.', 'Cuidado: perro al frente, muy cerca.']);
});

test('detector: un P1 nuevo reemplaza al P1 que esperaba, pero no a un P0', () => {
  const m = mundo();
  const D = { lane: 'deteccion' };
  m.voz.speak('Mensaje en curso de larga duración total.', 'P1');
  m.voz.speak('Cuidado: perro al frente, muy cerca.', 'P0', true, null, D);
  m.voz.speak('Computador al frente, muy cerca.', 'P1', true, null, D);
  m.voz.speak('Televisor al frente, muy cerca.', 'P1', true, null, D);
  assert.deepEqual(m.voz.pendientes, ['Cuidado: perro al frente, muy cerca.', 'Televisor al frente, muy cerca.']);
});

test('detector: sus avisos no borran lo de la navegación ni el diálogo', () => {
  const m = mundo();
  m.voz.speak('Mensaje en curso de larga duración total.', 'P1');
  m.voz.speak('En unos 40 metros, gire a la derecha.', 'P1');
  m.voz.speak('¿A dónde quiere ir?', 'P1', true, null, { lane: 'dialogo' });
  m.voz.speak('Computador al frente, muy cerca.', 'P1', true, null, { lane: 'deteccion' });
  assert.equal(m.voz.pendientes.length, 3);
});

test('un aviso P2 nuevo reemplaza al P2 que seguía esperando', () => {
  const m = mundo();
  m.voz.speak('Mensaje en curso de larga duración total.', 'P1');
  m.voz.speak('Siga derecho, va bien uno.', 'P2');
  m.voz.speak('Siga derecho, va bien dos.', 'P2');
  assert.deepEqual(m.voz.pendientes, ['Siga derecho, va bien dos.']);
});

test('el "terminé" de sayAndWait se cumple una sola vez', async () => {
  const m = mundo();
  let veces = 0;
  m.voz.speak('Una sola frase de prueba aquí.', 'P1', true, () => veces++);
  m.acabar(); m.acabar(); m.acabar();
  await Promise.resolve();
  assert.equal(veces, 1);
});

test('texto vacío: no se dice nada y quien espera no se cuelga', async () => {
  const m = mundo();
  await m.voz.sayAndWait('   ');
  await m.voz.sayAndWait(undefined);
  assert.deepEqual(m.dichas, []);
});

test('reset (apagar Bili): calla todo y libera a quien esperaba', async () => {
  const m = mundo();
  const a = m.voz.sayAndWait('Algo que se está diciendo ahora mismo.', 'P1');
  const b = m.voz.sayAndWait('Algo que esperaba su turno aquí.', 'P1');
  m.voz.reset();
  await Promise.all([a, b]);
  assert.equal(m.voz.ocupada(), false);
});

test('ocupada(): sirve para no empezar a escuchar encima de la voz', () => {
  const m = mundo();
  assert.equal(m.voz.ocupada(), false);
  m.voz.speak('Algo que se está diciendo ahora mismo.', 'P1');
  assert.equal(m.voz.ocupada(), true);
  m.acabar();
  assert.equal(m.voz.ocupada(), false);
});
