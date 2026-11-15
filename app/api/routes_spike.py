"""Prueba de YOLO dentro del teléfono (ONNX). SOLO PARA DESARROLLO.

Se activa con ONNX_SPIKE=1. Sirve la página de medición y los modelos exportados: nunca debe estar activa en una
instalación pública, porque entrega el modelo propio a cualquiera que lo pida. Los .onnx se generan con
`yolo export format=onnx imgsz=640` y se copian a models/onnx/.
"""
from __future__ import annotations

import hmac
from urllib.parse import parse_qs

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.config import settings

router = APIRouter()

MODELOS = {'yolo26n', 'yolo26s', 'bili-hazards', 'bili-hazards-v6b', 'bili-hazards-v7a'}
FORMAS = {'640x480', '416x320'}  # alto x ancho de la entrada, vertical como la cámara del teléfono
PERMITIDOS = MODELOS | {f'{m}_{f}' for m in MODELOS for f in FORMAS}
MODULOS = {'deteccion', 'seguimiento', 'fusion', 'alertas', 'decision', 'cercania', 'etiquetas'}  # web/bili/

# Con estas dos cabeceras el navegador permite hilos en WebAssembly (SharedArrayBuffer), que aceleran el modelo.
AISLADO = {
    'Cross-Origin-Opener-Policy': 'same-origin',
    'Cross-Origin-Embedder-Policy': 'require-corp',
    'Cache-Control': 'no-store',
}


@router.get('/onnx-spike', include_in_schema=False)
def pagina_de_prueba():
    return FileResponse(settings.web_dir / 'onnx-spike.html', media_type='text/html', headers=AISLADO)


@router.get('/bili/{nombre}.js', include_in_schema=False)
def modulo_del_celular(nombre: str):
    """Los módulos de web/bili/ (detector, seguimiento, motor de decisión) que la página importa."""
    if nombre not in MODULOS:
        raise HTTPException(status_code=404, detail='No existe')
    return FileResponse(settings.web_dir / 'bili' / f'{nombre}.js', media_type='application/javascript',
                        headers={**AISLADO, 'Cross-Origin-Resource-Policy': 'same-origin'})


@router.get('/v1/onnx/{nombre}.onnx', include_in_schema=False)
def modelo_onnx(nombre: str):
    if nombre not in PERMITIDOS:  # lista cerrada: el nombre nunca se usa para armar una ruta libre
        raise HTTPException(status_code=404, detail='No existe')
    ruta = settings.base_dir / 'models' / 'onnx' / f'{nombre}.onnx'
    if not ruta.is_file():
        raise HTTPException(status_code=404, detail='Falta exportar el modelo a models/onnx/')
    return FileResponse(ruta, media_type='application/octet-stream', headers={**AISLADO, 'Cross-Origin-Resource-Policy': 'same-origin'})


COOKIE = 'bili_clave'


def _es_de_la_prueba(ruta: str) -> bool:
    return ruta == '/onnx-spike' or (ruta.startswith('/bili/') and ruta.endswith('.js')) or (ruta.startswith('/v1/onnx/') and ruta.endswith('.onnx'))


class SoloPruebaPorTunel:
    """Filtro para compartir la prueba por un túnel de Cloudflare sin exponer el resto del servidor.

    Lo que llega por Cloudflare (trae la cabecera cf-connecting-ip, que Cloudflare siempre agrega y el visitante no puede quitar) solo
    puede ver la página de prueba, sus módulos y los dos .onnx, y solo con la clave: la primera vez en el enlace (?clave=...), que deja
    una cookie; después con la cookie. Todo lo demás (la app, los WebSocket de la cámara, la descripción con Gemini) responde 404.
    Sin clave configurada, el túnel no deja pasar nada. Lo que llega por el Wi-Fi no cambia. Es ASGI puro para cubrir también WebSocket."""

    def __init__(self, app, clave: str = ''):
        self.app = app
        self.clave = clave

    def _clave_valida(self, dada: str) -> bool:
        return bool(self.clave) and hmac.compare_digest(dada.encode(), self.clave.encode())

    async def __call__(self, scope, receive, send):
        if scope['type'] not in ('http', 'websocket'):
            return await self.app(scope, receive, send)
        cabeceras = dict(scope.get('headers') or [])
        if b'cf-connecting-ip' not in cabeceras:
            return await self.app(scope, receive, send)
        ruta = scope.get('path', '')
        por_enlace = parse_qs(scope.get('query_string', b'').decode()).get('clave', [''])[0]
        galletas = dict(p.strip().split('=', 1) for p in cabeceras.get(b'cookie', b'').decode().split(';') if '=' in p)
        if scope['type'] == 'http' and _es_de_la_prueba(ruta) and (self._clave_valida(galletas.get(COOKIE, '')) or self._clave_valida(por_enlace)):
            if not self._clave_valida(por_enlace):
                return await self.app(scope, receive, send)

            async def con_cookie(mensaje):
                if mensaje['type'] == 'http.response.start':
                    mensaje.setdefault('headers', [])
                    mensaje['headers'] = [*mensaje['headers'], (b'set-cookie', f'{COOKIE}={self.clave}; Path=/; Secure; HttpOnly; SameSite=Strict'.encode())]
                await send(mensaje)

            return await self.app(scope, receive, con_cookie)
        if scope['type'] == 'websocket':
            await send({'type': 'websocket.close', 'code': 1008})
            return
        await send({'type': 'http.response.start', 'status': 404, 'headers': [(b'content-type', b'text/plain; charset=utf-8')]})
        await send({'type': 'http.response.body', 'body': b'No existe'})
