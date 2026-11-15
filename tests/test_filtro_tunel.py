"""Lo que llega por el túnel de Cloudflare solo ve la página de prueba, y solo con la clave. Lo del Wi-Fi no cambia."""
from fastapi import FastAPI, WebSocket
from fastapi.testclient import TestClient

from app.api.routes_spike import SoloPruebaPorTunel

CF = {'cf-connecting-ip': '1.2.3.4'}


def _cliente(clave='abc123'):
    app = FastAPI()

    @app.get('/onnx-spike')
    def pagina():
        return {'ok': 'pagina'}

    @app.get('/bili/seguimiento.js')
    def modulo():
        return {'ok': 'modulo'}

    @app.get('/movil')
    def movil():
        return {'ok': 'movil'}

    @app.post('/v1/describe')
    def describir():
        return {'ok': 'gemini'}

    @app.websocket('/ws/frames')
    async def cuadros(ws: WebSocket):
        await ws.accept()
        await ws.send_text('hola')
        await ws.close()

    app.add_middleware(SoloPruebaPorTunel, clave=clave)
    return TestClient(app, base_url='https://testserver')


def test_por_wifi_todo_sigue_igual():
    c = _cliente()
    assert c.get('/movil').status_code == 200
    with c.websocket_connect('/ws/frames') as ws:
        assert ws.receive_text() == 'hola'


def test_por_el_tunel_sin_clave_no_hay_nada():
    c = _cliente()
    assert c.get('/onnx-spike', headers=CF).status_code == 404
    assert c.get('/onnx-spike?clave=mala', headers=CF).status_code == 404


def test_con_la_clave_del_enlace_entra_y_queda_la_cookie_para_los_modulos():
    c = _cliente()
    r = c.get('/onnx-spike?clave=abc123', headers=CF)
    assert r.status_code == 200 and 'bili_clave=abc123' in r.headers['set-cookie']
    assert c.get('/bili/seguimiento.js', headers=CF).status_code == 200   # con la cookie


def test_con_la_clave_tambien_entra_bili_en_el_telefono():
    app = FastAPI()
    for ruta in ('/local', '/sw.js', '/v1/voz.js', '/v1/nav.js', '/v1/voice.js'):
        app.add_api_route(ruta, lambda: {'ok': True})
    for ruta in ('/v1/rutas', '/v1/ubicacion'):
        app.add_api_route(ruta, lambda: {'ok': True}, methods=['POST'])
    app.add_middleware(SoloPruebaPorTunel, clave='abc123')
    c = TestClient(app, base_url='https://testserver')
    assert c.post('/v1/rutas', headers=CF).status_code == 404   # sin clave, tampoco la navegación
    assert c.get('/local', headers=CF).status_code == 404
    assert c.get('/local?clave=abc123', headers=CF).status_code == 200
    for ruta in ('/sw.js', '/v1/voz.js', '/v1/nav.js', '/v1/voice.js'):
        assert c.get(ruta, headers=CF).status_code == 200, ruta
    assert c.post('/v1/rutas', headers=CF).status_code == 200 and c.post('/v1/ubicacion', headers=CF).status_code == 200


def test_ni_con_la_clave_se_llega_al_resto_del_servidor():
    c = _cliente()
    c.get('/onnx-spike?clave=abc123', headers=CF)
    assert c.get('/movil', headers=CF).status_code == 404
    assert c.post('/v1/describe?clave=abc123', headers=CF).status_code == 404


def test_por_el_tunel_no_entran_cuadros_de_camara():
    import pytest
    from starlette.websockets import WebSocketDisconnect

    c = _cliente()
    with pytest.raises(WebSocketDisconnect):
        with c.websocket_connect('/ws/frames?clave=abc123', headers=CF) as ws:
            ws.receive_text()


def test_sin_clave_configurada_el_tunel_esta_cerrado():
    assert _cliente(clave='').get('/onnx-spike?clave=', headers=CF).status_code == 404
