"""El servidor de la nube: sin la clave no entrega nada (ni la página, ni el modelo, ni rutas); con ella, solo lo que usa /local."""
import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def nube(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, 'onnx_spike_clave', 'abc123')
    import app.nube

    return TestClient(importlib.reload(app.nube).app, base_url='https://testserver')


def test_sin_clave_no_hay_nada(nube):
    for ruta in ('/local', '/sw.js', '/bili/seguimiento.js', '/v1/voz.js', '/v1/onnx/bili-hazards-v7a_640x480.onnx'):
        assert nube.get(ruta).status_code == 404, ruta
    assert nube.post('/v1/rutas', json={}).status_code == 404


def test_con_la_clave_entra_la_app_del_telefono(nube):
    r = nube.get('/local?clave=abc123')
    assert r.status_code == 200 and 'Bili en el teléfono' in r.text
    for ruta in ('/sw.js', '/bili/seguimiento.js', '/v1/voz.js', '/v1/nav.js', '/v1/voice.js'):
        assert nube.get(ruta).status_code == 200, ruta


def test_ni_con_la_clave_hay_documentacion_ni_otras_rutas(nube):
    nube.get('/local?clave=abc123')
    for ruta in ('/docs', '/openapi.json', '/movil', '/'):
        assert nube.get(ruta).status_code == 404, ruta


def test_sin_clave_configurada_no_entrega_nada(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, 'onnx_spike_clave', '')
    import app.nube

    c = TestClient(importlib.reload(app.nube).app, base_url='https://testserver')
    assert c.get('/local?clave=').status_code == 404
