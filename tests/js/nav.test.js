const test = require('node:test');
const assert = require('node:assert/strict');
const N = require('../../web/nav.js');
const DISTANCIAS = require('../fixtures/distancias.json');

const LAT0 = 4.65, LNG0 = -74.06;
const M_LAT = 111195, M_LNG = 111195 * Math.cos((LAT0 * Math.PI) / 180);
const P = (north, east) => ({ lat: LAT0 + north / M_LAT, lng: LNG0 + east / M_LNG });

function encode(points) {
  let out = '', pl = 0, pg = 0;
  const enc = (v) => {
    v = v < 0 ? ~(v << 1) : v << 1;
    let s = '';
    while (v >= 0x20) { s += String.fromCharCode((0x20 | (v & 0x1f)) + 63); v >>= 5; }
    return s + String.fromCharCode(v + 63);
  };
  for (const p of points) {
    const la = Math.round(p.lat * 1e5), lg = Math.round(p.lng * 1e5);
    out += enc(la - pl) + enc(lg - pg); pl = la; pg = lg;
  }
  return out;
}

/* 600 m al norte, giro a la derecha (este), 400 m, giro a la izquierda (norte), 100 m. */
function rutaDemo(cruces = []) {
  const pts = [P(0, 0), P(600, 0), P(600, 400), P(700, 400)];
  const pasos = [
    { indice: 0, maniobra: 'DEPART', accion: 'siga derecho', frase: 'Siga derecho unos 600 metros', inicio: pts[0], fin: pts[1] },
    { indice: 1, maniobra: 'TURN_RIGHT', accion: 'gire a la derecha', frase: 'Gire a la derecha y siga unos 400 metros', inicio: pts[1], fin: pts[2] },
    { indice: 2, maniobra: 'TURN_LEFT', accion: 'gire a la izquierda', frase: 'Gire a la izquierda y siga unos 100 metros hasta llegar a su destino', inicio: pts[2], fin: pts[3] },
  ];
  return { polilinea: encode(pts), pasos, destino: pts[3], cruces, cruces_consultados: true };
}

function caminar(nav, path, desde, hasta, paso = 4) {
  let t = 0;
  for (let a = desde; a <= hasta; a += paso) {
    nav.update({ ...N.positionAt(path, a), accuracy: 8, t });
    t += 3;
  }
}

function crear(ruta, opts = {}) {
  const spoken = [];
  const nav = new N.Navigator(ruta, { say: (text, priority) => spoken.push({ text, priority }), ...opts });
  return { nav, spoken, path: nav.path };
}

test('decodifica una polilínea de Google conocida', () => {
  const pts = N.decodePolyline('_p~iF~ps|U_ulLnnqC_mqNvxq`@');
  assert.deepEqual(pts.map((p) => [p.lat, p.lng]), [[38.5, -120.2], [40.7, -120.95], [43.252, -126.453]]);
});

test('distancias: pasos y metros de cerca, cuadras de lejos, nunca kilómetros (misma tabla que el servidor)', () => {
  for (const [metros, esperado] of DISTANCIAS) assert.equal(N.sayDistance(metros), esperado, `${metros} m`);
  for (const m of [150, 999, 1500, 5000, 20000]) assert.doesNotMatch(N.sayDistance(m), /kil[oó]metro/);
});

test('recorrido completo: orden de avisos, sin repetidos y llega', () => {
  const { nav, spoken, path } = crear(rutaDemo());
  caminar(nav, path, 0, path.length);
  const textos = spoken.map((s) => s.text);
  assert.equal(textos[0], 'Siga derecho unos 600 metros');
  const iPre = textos.findIndex((t) => /^En unos \d+ metros, gire a la derecha\.$/.test(t));
  const iAhora = textos.indexOf('Gire a la derecha y siga unos 400 metros');
  assert.ok(iPre > 0 && iAhora > iPre, 'primero el preaviso, luego el giro');
  assert.ok(textos.includes('Gire a la izquierda y siga unos 100 metros hasta llegar a su destino'));
  assert.equal(textos.at(-1), 'Llegó a su destino.');
  const fijos = textos.filter((t) => t !== 'Siga derecho, va bien.');
  assert.equal(new Set(fijos).size, fijos.length, 'ningún aviso repetido');
  assert.equal(nav.finished, true);
});

test('tramos largos: "Siga derecho, va bien." con prioridad baja y sin números', () => {
  const { nav, spoken, path } = crear(rutaDemo());
  caminar(nav, path, 0, 500);
  const vaBien = spoken.filter((s) => s.text === 'Siga derecho, va bien.');
  assert.ok(vaBien.length >= 3, 'cada ~100 m: al menos tres en 500 m');
  assert.ok(vaBien.every((s) => s.priority === 'P2'));
  assert.ok(vaBien.every((s) => !/\d/.test(s.text)), 'sin cifras que calcular');
});

test('no se dice "va bien" después del preaviso de un giro', () => {
  const { nav, spoken, path } = crear(rutaDemo());
  caminar(nav, path, 0, 590);  // el giro está en el metro 600
  const textos = spoken.map((s) => s.text);
  const iPre = textos.findIndex((t) => /^En unos \d+ metros, gire a la derecha\.$/.test(t));
  assert.ok(iPre > 0);
  assert.ok(textos.lastIndexOf('Siga derecho, va bien.') < iPre, 'ningún "va bien" tras el preaviso');
});

test('cruce con semáforo: aviso previo y luego "detenga el paso", una sola vez', () => {
  const ruta = rutaDemo([{ ...P(300, 2), tipo: 'semaforo' }]);
  const { nav, spoken, path } = crear(ruta);
  caminar(nav, path, 0, 400);
  const textos = spoken.map((s) => s.text);
  const iAviso = textos.findIndex((t) => t.startsWith('Se acerca un cruce con semáforo'));
  const iStop = textos.indexOf(N.STOP_MESSAGE);
  assert.ok(iAviso >= 0 && iStop > iAviso);
  assert.equal(textos.filter((t) => t === N.STOP_MESSAGE).length, 1);
});

test('nunca se dice que es seguro cruzar', () => {
  const ruta = rutaDemo([{ ...P(300, 0), tipo: 'semaforo' }, { ...P(450, 0), tipo: 'cebra' }]);
  const { nav, spoken, path } = crear(ruta);
  caminar(nav, path, 0, path.length);
  for (const s of spoken) assert.doesNotMatch(s.text, /es seguro|puede cruzar|adelante/i);
});

test('dos puntos del mismo cruce dan un solo aviso, y gana el semáforo', () => {
  const ruta = rutaDemo([{ ...P(300, 1), tipo: 'cruce' }, { ...P(306, -1), tipo: 'semaforo' }]);
  const { nav, spoken, path } = crear(ruta);
  caminar(nav, path, 0, 400);
  const avisos = spoken.filter((s) => s.text.startsWith('Se acerca'));
  assert.equal(avisos.length, 1);
  assert.match(avisos[0].text, /semáforo/);
});

test('un cruce lejos de la ruta o pegado al inicio se ignora', () => {
  const ruta = rutaDemo([{ ...P(300, 60), tipo: 'semaforo' }, { ...P(3, 0), tipo: 'semaforo' }]);
  const { nav, spoken, path } = crear(ruta);
  caminar(nav, path, 0, 400);
  assert.equal(spoken.filter((s) => /cruce|Detenga/.test(s.text)).length, 0);
});

test('GPS impreciso: avisa una vez, no da giros y se recupera', () => {
  const { nav, spoken, path } = crear(rutaDemo());
  const pos = N.positionAt(path, 560);
  nav.update({ ...pos, accuracy: 60, t: 0 });
  nav.update({ ...pos, accuracy: 60, t: 5 });
  assert.equal(spoken.filter((s) => s.text.startsWith('Posición imprecisa')).length, 1);
  assert.equal(spoken.filter((s) => /gire/i.test(s.text)).length, 0);
  nav.update({ ...pos, accuracy: 60, t: 40 });
  assert.equal(spoken.filter((s) => s.text.startsWith('Posición imprecisa')).length, 2, 'repite pasado el intervalo');
  nav.update({ ...pos, accuracy: 10, t: 45 });
  assert.ok(spoken.some((s) => s.text === 'Posición recuperada.'));
});

test('fuera de ruta: recalcula tras varias lecturas y no insiste', () => {
  const llamadas = [];
  const { nav, spoken, path } = crear(rutaDemo(), { onOffRoute: (p) => llamadas.push(p) });
  const lejos = (a, t) => ({ ...P(a, 80), accuracy: 8, t });
  nav.update(lejos(100, 0));
  nav.update(lejos(104, 3));
  assert.equal(llamadas.length, 0, 'dos lecturas no bastan');
  nav.update(lejos(108, 6));
  assert.equal(llamadas.length, 1);
  nav.update(lejos(112, 9));
  nav.update(lejos(116, 12));
  assert.equal(llamadas.length, 1, 'no recalcula otra vez dentro de 20 s');
  assert.equal(spoken.filter((s) => s.text.startsWith('Se salió de la ruta')).length, 1);
  nav.update({ ...N.positionAt(path, 130), accuracy: 8, t: 15 });
  assert.equal(llamadas.length, 1);
});

test('el progreso no retrocede aunque el GPS salte atrás', () => {
  const { nav, path } = crear(rutaDemo());
  nav.update({ ...N.positionAt(path, 300), accuracy: 8, t: 0 });
  nav.update({ ...N.positionAt(path, 290), accuracy: 8, t: 3 });
  assert.ok(nav.progress >= 299);
});

test('ruta de ida y vuelta por la misma calle: el desempate usa el progreso', () => {
  const pts = [P(0, 0), P(300, 0), P(0, 3)];
  const ruta = {
    polilinea: encode(pts), destino: pts[2], cruces: [],
    pasos: [
      { indice: 0, maniobra: 'DEPART', accion: 'siga derecho', frase: 'Siga derecho', inicio: pts[0], fin: pts[1] },
      { indice: 1, maniobra: 'UTURN_LEFT', accion: 'dé la vuelta', frase: 'Dé la vuelta', inicio: pts[1], fin: pts[2] },
    ],
  };
  const { nav, path } = crear(ruta);
  nav.update({ ...N.positionAt(path, 100), accuracy: 8, t: 0 });
  assert.ok(Math.abs(nav.progress - 100) < 5, 'en la subida debe quedar cerca de 100, no de 500');
});

test('maniobra desconocida: dice "continúe" al llegar, sin preaviso vacío y nunca "siga derecho"', () => {
  const r = rutaDemo();
  r.pasos[1].accion = 'continúe';
  r.pasos[1].frase = 'Continúe y siga unos 400 metros';
  const { nav, spoken, path } = crear(r);
  caminar(nav, path, 0, 620);
  const textos = spoken.map((s) => s.text);
  assert.ok(textos.includes('Continúe y siga unos 400 metros'));
  assert.ok(!textos.some((t) => /^En unos \d+ metros, continúe/.test(t)), 'sin preaviso');
  assert.ok(!textos.some((t) => /siga derecho unos 400/i.test(t)));
});

test('los "va bien" no se dicen entre el preaviso de un cruce y su "detenga el paso"', () => {
  const ruta = rutaDemo([{ ...P(180, 0), tipo: 'semaforo' }]);
  const { nav, spoken, path } = crear(ruta);
  caminar(nav, path, 0, 330);
  const textos = spoken.map((s) => s.text);
  const iAviso = textos.findIndex((t) => t.startsWith('Se acerca'));
  const iStop = textos.indexOf(N.STOP_MESSAGE);
  assert.ok(iAviso >= 0 && iStop > iAviso);
  assert.ok(!textos.slice(iAviso, iStop + 1).some((t) => t === 'Siga derecho, va bien.'));
  assert.ok(textos.some((t) => t === 'Siga derecho, va bien.'), 'sí hay "va bien" en otros momentos');
});

test('"detenga el paso" es urgente (P0); el preaviso del cruce no', () => {
  const ruta = rutaDemo([{ ...P(300, 0), tipo: 'semaforo' }]);
  const { nav, spoken, path } = crear(ruta);
  caminar(nav, path, 0, 400);
  assert.equal(spoken.find((s) => s.text === N.STOP_MESSAGE).priority, 'P0');
  assert.equal(spoken.find((s) => s.text.startsWith('Se acerca')).priority, 'P1');
});

test('rumbo en palabras', () => {
  assert.equal(N.headingWord(0), 'norte');
  assert.equal(N.headingWord(44), 'noreste');
  assert.equal(N.headingWord(90), 'este');
  assert.equal(N.headingWord(181), 'sur');
  assert.equal(N.headingWord(270), 'oeste');
  assert.equal(N.headingWord(359), 'norte');
  assert.equal(N.headingWord(-90), 'oeste');
});
