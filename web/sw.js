// Bili sin red (QA-2): guarda en el teléfono la página /local, sus módulos, la voz, ONNX Runtime y los modelos.
// - Modelos y ONNX Runtime (grandes y con versión fija): primero lo guardado; si no está, se baja y se guarda.
// - Página y módulos (chicos y cambian con el código): primero la red, con 3 s de espera; sin red, lo guardado.
// La primera vez hay que abrir /local con red y dejarlo cargar; desde ahí funciona en modo avión.
const CACHE = 'bili-local-v1';

self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (e) => e.waitUntil(self.clients.claim()));

function conLimite(peticion, ms) {
  const control = new AbortController();
  const t = setTimeout(() => control.abort(), ms);
  return fetch(peticion, { signal: control.signal }).finally(() => clearTimeout(t));
}

self.addEventListener('fetch', (e) => {
  if (e.request.method !== 'GET') return;
  const url = new URL(e.request.url);
  const propio = url.origin === self.location.origin;
  const grande = (propio && url.pathname.startsWith('/v1/onnx/')) || url.hostname === 'cdn.jsdelivr.net';
  const pagina = propio && (url.pathname === '/local' || url.pathname.startsWith('/bili/') || url.pathname === '/v1/voz.js');
  if (!grande && !pagina) return;
  e.respondWith((async () => {
    const cache = await caches.open(CACHE);
    if (grande) {
      const guardado = await cache.match(e.request, { ignoreSearch: true });
      if (guardado) return guardado;
      const r = await fetch(e.request);
      if (r.ok) await cache.put(e.request, r.clone());
      return r;
    }
    try {
      const r = await conLimite(e.request, 3000);
      if (r.ok) await cache.put(e.request, r.clone());
      return r;
    } catch (err) {
      const guardado = await cache.match(e.request, { ignoreSearch: true });
      if (guardado) return guardado;
      throw err;
    }
  })());
});
