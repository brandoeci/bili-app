from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.alerts import AlertManager
from app.main import app
from app.schemas import Detection

client = TestClient(app)


def test_health():
    response = client.get('/health')
    assert response.status_code == 200
    data = response.json()
    assert data['status'] == 'ok'
    assert 'vlm_local_loading' in data['models_loaded']


def test_describe():
    response = client.post('/v1/describe', json={'mode': 'local', 'task': 'scene', 'speak': False})
    assert response.status_code in {200, 503}
    if response.status_code == 503:
        assert 'VLM' in response.json()['detail']
        return
    body = response.json()
    assert 'text' in body
    assert body['text']
    assert body['source'] in {'vlm_local', 'gemini', 'heuristic'}


def test_root():
    response = client.get('/')
    assert response.status_code == 200


def test_alerts_are_in_spanish():
    alert = AlertManager(cooldown_s=0).evaluate(
        [
            Detection(
                track_id=1,
                label='person',
                conf=0.9,
                bbox=(0, 0, 10, 10),
                direction='left',
                distance_m=1.0,
                priority='P0',
            )
        ]
    )[0]
    assert 'persona' in alert.text
    assert 'izquierda' in alert.text
    assert 'person ' not in alert.text
