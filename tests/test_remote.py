from __future__ import annotations

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.core.camera import RemoteCamera
from app.main import app, app_state

client = TestClient(app)


def _jpeg(color: int = 128) -> bytes:
    ok, buf = cv2.imencode('.jpg', np.full((120, 160, 3), color, dtype=np.uint8))
    assert ok
    return buf.tobytes()


def test_remote_camera_accepts_jpeg_and_rejects_garbage():
    cam = RemoteCamera()
    assert cam.latest()[0] is None and not cam.is_open()
    assert cam.push_jpeg(_jpeg())
    frame, ts = cam.latest()
    assert frame.shape == (120, 160, 3) and ts > 0 and cam.is_open()
    assert not cam.push_jpeg(b'no es una imagen')
    assert cam.frames_received == 1


def test_ws_frames_feeds_the_camera():
    if not isinstance(app_state.camera, RemoteCamera):
        pytest.skip('CAMERA_SOURCE=local')
    before = app_state.camera.frames_received
    with client.websocket_connect('/ws/frames') as ws:
        ws.send_bytes(_jpeg())
        ws.send_bytes(b'basura')
        assert ws.receive_text() == 'frame-invalid'
    assert app_state.camera.frames_received == before + 1


def test_speech_goes_to_connected_phone():
    app_state.settings.audio_output = 'client'
    app_state._client_recent.clear()
    # con `with` se ejecuta el lifespan: sin él el servidor no tiene event loop para difundir eventos
    with TestClient(app) as live, live.websocket_connect('/ws/events') as ws:
        # al conectarse se anuncia el estado del sistema; se descarta hasta ver nuestra frase
        assert app_state._say('Cuidado: persona al frente, a un metro', priority='P0', force=True)
        for _ in range(10):
            msg = ws.receive_json()
            if msg.get('type') == 'speak' and 'persona' in msg['text']:
                assert msg['priority'] == 'P0'
                break
        else:
            pytest.fail('el celular no recibió el evento speak')


def test_mobile_page_is_served():
    response = client.get('/movil')
    assert response.status_code == 200
    assert 'getUserMedia' in response.text
    assert response.headers['cache-control'] == 'no-store'   # si el iPhone guarda una página vieja, sigue con código ya corregido
    assert 'Bienvenido a Bili, tu ayuda visual' in response.text   # lo que lee VoiceOver al abrir y lo que se dice al primer toque


def test_events_ws_contesta_pong_al_ping_del_telefono():
    """El teléfono pregunta cada pocos segundos '¿sigues ahí?': sin respuesta da la conexión por caída y avisa por voz."""
    with TestClient(app) as live, live.websocket_connect('/ws/events') as ws:
        ws.send_text('ping')
        for _ in range(20):  # al conectarse llegan antes los avisos del estado del sistema
            if ws.receive_json() == {'type': 'pong'}:
                break
        else:
            pytest.fail('el servidor no contestó pong')


def test_events_ws_no_deja_sockets_muertos_en_la_lista():
    with TestClient(app) as live:
        antes = len(app_state.websockets)
        with live.websocket_connect('/ws/events') as ws:
            ws.send_text('ping')
            assert len(app_state.websockets) == antes + 1
        for _ in range(50):  # el cierre se procesa en el event loop del servidor
            if len(app_state.websockets) == antes:
                break
            import time
            time.sleep(0.05)
        assert len(app_state.websockets) == antes
