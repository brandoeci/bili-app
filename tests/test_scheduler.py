from __future__ import annotations

import asyncio

import pytest

from app.scene.narrator import NarrationGate, scene_signature
from app.scene.postprocess import clean, reconcile_with_sensors
from app.scene.providers import CircuitBreaker
from app.scene.scheduler import SceneBusy, SceneScheduler
from app.scene.vlm_worker import VLMUnavailable


class FakeVLM:
    def __init__(self, text='', error=None):
        self.text, self.error, self.calls = text, error, 0

    def describe(self, image, prompt, timeout, max_tokens=96):
        self.calls += 1
        if self.error:
            raise self.error
        return self.text


NEAR_PERSON = [{'label': 'person', 'priority': 'P1', 'direction': 'left', 'distance_m': 2.0}]


def run(coro):
    return asyncio.run(coro)


def test_empty_vlm_falls_back_to_degraded_heuristic_that_never_claims_clear_path():
    scheduler = SceneScheduler(vlm=FakeVLM(''))
    result = run(scheduler.describe_scene(b'x', [], mode='local'))
    assert result['source'] == 'heuristic' and result['degraded']
    assert 'libre' not in result['text'].lower() and 'puede seguir' not in result['text'].lower()


def test_heuristic_reports_measured_objects_and_is_not_rate_limited():
    scheduler = SceneScheduler()
    first = run(scheduler.describe_scene(b'x', NEAR_PERSON, mode='local'))
    second = run(scheduler.describe_scene(b'x', NEAR_PERSON, mode='local'))
    assert 'persona a su izquierda' in first['text']
    assert second['source'] == 'heuristic'


def test_vlm_text_is_cleaned_and_used():
    scheduler = SceneScheduler(vlm=FakeVLM('**Claro**, camino libre al frente.'))
    # el VLM se invoca vía to_thread con firma (image, prompt, timeout, max_tokens)
    result = run(scheduler.describe_scene(b'not-a-jpeg', [], mode='local'))
    assert result['source'] == 'vlm_local'
    assert '*' not in result['text']


def test_unchanged_marker_is_flagged():
    scheduler = SceneScheduler(vlm=FakeVLM('SIN_CAMBIOS'))
    result = run(scheduler.describe_scene(b'x', [], mode='local', previous='Camino libre.'))
    assert result['unchanged']


def test_busy_vlm_does_not_trip_circuit_breaker():
    scheduler = SceneScheduler(vlm=FakeVLM(error=VLMUnavailable('cargando')))
    for _ in range(5):
        run(scheduler.describe_scene(b'x', [], mode='local'))
    assert scheduler.providers['vlm_local'].available()


def test_real_failures_open_circuit_breaker():
    vlm = FakeVLM(error=RuntimeError('boom'))
    scheduler = SceneScheduler(vlm=vlm)
    for _ in range(5):
        run(scheduler.describe_scene(b'x', [], mode='local'))
    assert vlm.calls == 3  # tras 3 fallos el circuito se abre y se deja de llamar


def test_background_request_is_skipped_while_busy():
    async def scenario():
        scheduler = SceneScheduler()
        async with scheduler._busy:
            with pytest.raises(SceneBusy):
                await scheduler.describe_scene(b'x', [], background=True)
    run(scenario())


def test_reconcile_adds_missing_critical_object():
    text = reconcile_with_sensors('Camino libre al frente.', [
        {'label': 'car', 'priority': 'P0', 'direction': 'right', 'distance_m': 2.0}])
    assert 'carro' in text and 'derecha' in text


def test_clean_strips_markup_and_preamble():
    assert clean('Claro, **hay** una puerta.') == 'Hay una puerta.'


def test_signature_ignores_track_ids_and_jitter():
    a = [{'label': 'person', 'direction': 'left', 'distance_m': 2.0, 'priority': 'P1', 'track_id': 1}]
    b = [{'label': 'person', 'direction': 'left', 'distance_m': 2.2, 'priority': 'P1', 'track_id': 9}]
    assert scene_signature(a) == scene_signature(b)


def test_gate_suppresses_repeated_descriptions_and_requests():
    gate = NarrationGate(min_gap_s=8, max_silence_s=45)
    sig = scene_signature(NEAR_PERSON)
    assert gate.should_request(sig, 0)
    gate.record_request(sig, 0)
    assert not gate.should_request(sig, 10)          # misma escena
    assert gate.should_request(frozenset(), 10)      # escena cambió
    assert gate.should_request(sig, 50)              # demasiado silencio
    gate.record_announcement('Persona a su izquierda, a dos metros.', 0)
    assert gate.is_repeat('Persona a su izquierda a dos metros', 30)
    assert not gate.is_repeat('Escalón hacia abajo al frente.', 30)


def test_circuit_breaker_half_open():
    breaker = CircuitBreaker(threshold=2, cooldown_s=0.0)
    breaker.failure()
    breaker.failure()
    assert not breaker.open  # cooldown 0 → half-open inmediato
