from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.schemas import ConfigUpdate

router = APIRouter(prefix='/v1')


@router.post('/session/start')
def start_session(request: dict | None = None):
    from app.main import app_state

    app_state.start()
    return {'status': 'started'}


@router.post('/session/stop')
def stop_session():
    from app.main import app_state

    app_state.stop()
    return {'status': 'stopped'}


@router.get('/config')
def get_config():
    from app.main import app_state

    return app_state.current_config()


@router.put('/config')
def update_config(payload: ConfigUpdate):
    from app.main import app_state

    return app_state.update_config(payload)


@router.post('/calibrate')
def calibrate(distance_m: float):
    """Colócate a `distance_m` metros de la cámara, de pie y entero en cuadro."""
    from app.main import app_state

    if not 0.5 <= distance_m <= 10:
        raise HTTPException(status_code=422, detail='distance_m debe estar entre 0.5 y 10')
    try:
        return app_state.calibrate_distance(distance_m)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post('/repeat')
def repeat(n: int = 1):
    """Repite el n-ésimo último mensaje hablado (1 = el último)."""
    from app.main import app_state

    text = app_state.repeat_last(n)
    if text is None:
        raise HTTPException(status_code=404, detail='No hay mensajes para repetir')
    return {'text': text}


@router.get('/history')
def history():
    from app.main import app_state

    return list(app_state.history)
