from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import routes_spike
from app.main import app as app_principal


def _cliente() -> TestClient:
    app = FastAPI()
    app.include_router(routes_spike.router)
    return TestClient(app)


def test_la_prueba_de_onnx_no_existe_si_no_se_activa():
    # Entrega el modelo propio: por defecto (ONNX_SPIKE sin activar) no debe haber ninguna ruta
    c = TestClient(app_principal)  # sin "with": no arranca la cámara ni los modelos
    assert c.get('/onnx-spike').status_code == 404
    assert c.get('/v1/onnx/yolo26s.onnx').status_code == 404


def test_la_pagina_trae_las_cabeceras_para_hilos_de_webassembly():
    r = _cliente().get('/onnx-spike')
    assert r.status_code == 200
    assert r.headers['cross-origin-opener-policy'] == 'same-origin'
    assert r.headers['cross-origin-embedder-policy'] == 'require-corp'


def test_solo_se_sirven_los_modelos_de_la_lista(tmp_path, monkeypatch):
    onnx = tmp_path / 'models' / 'onnx'
    onnx.mkdir(parents=True)
    (onnx / 'yolo26s.onnx').write_bytes(b'abc')
    (onnx / 'secreto.onnx').write_bytes(b'no')
    monkeypatch.setattr(routes_spike.settings, 'base_dir', tmp_path)
    c = _cliente()
    assert c.get('/v1/onnx/yolo26s.onnx').content == b'abc'
    assert c.get('/v1/onnx/secreto.onnx').status_code == 404  # existe en disco pero no está en la lista
    assert c.get('/v1/onnx/..%2Fsecreto.onnx').status_code == 404
    assert c.get('/v1/onnx/bili-hazards.onnx').status_code == 404  # en la lista pero sin exportar
    (onnx / 'yolo26n_416x320.onnx').write_bytes(b'n')
    assert c.get('/v1/onnx/yolo26n_416x320.onnx').content == b'n'  # variante de forma permitida
    assert c.get('/v1/onnx/yolo26n_999x999.onnx').status_code == 404  # forma que no está en la lista
