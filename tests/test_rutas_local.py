"""La app en el teléfono (/local) y su service worker se sirven con el aislamiento que pide ONNX Runtime con hilos."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes_spike import router


def _cliente():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_la_pagina_local_se_sirve_aislada():
    r = _cliente().get('/local')
    assert r.status_code == 200 and 'Bili en el teléfono' in r.text
    assert r.headers['cross-origin-embedder-policy'] == 'require-corp'
    assert r.headers['cross-origin-opener-policy'] == 'same-origin'


def test_el_service_worker_cubre_todo_el_sitio():
    r = _cliente().get('/sw.js')
    assert r.status_code == 200 and r.headers['service-worker-allowed'] == '/'
    assert 'javascript' in r.headers['content-type']


def test_los_modulos_que_importa_la_pagina_existen():
    c = _cliente()
    for nombre in ('deteccion', 'seguimiento', 'fusion', 'alertas', 'decision', 'cercania', 'etiquetas'):
        assert c.get(f'/bili/{nombre}.js').status_code == 200, nombre
    assert c.get('/bili/otra.js').status_code == 404
