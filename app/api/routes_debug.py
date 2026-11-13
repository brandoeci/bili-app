from __future__ import annotations

import cv2
import numpy as np
from fastapi import APIRouter, File, HTTPException, UploadFile

router = APIRouter()


@router.get('/health')
def health():
    from app.main import app_state

    return app_state.health()


@router.get('/metrics')
def metrics():
    from app.main import app_state

    return app_state.metrics_snapshot()


@router.get('/v1/navigation')
def navigation():
    from app.main import app_state

    return app_state.pipeline.navigation or {'sectors': {}, 'hazards': [], 'suggestion': None, 'floor_ok': False}


@router.get('/v1/depth.jpg')
def depth_preview():
    from fastapi.responses import Response

    from app.main import app_state

    if not app_state.settings.debug_endpoints:
        raise HTTPException(status_code=404, detail='Deshabilitado (DEBUG_ENDPOINTS=false)')

    data = app_state.depth_preview_jpeg()
    if data is None:
        raise HTTPException(status_code=503, detail='El modelo de profundidad no está listo')
    return Response(content=data, media_type='image/jpeg')


@router.post('/v1/detect')
async def detect_image(file: UploadFile = File(...)):
    from app.main import app_state

    data = await file.read()
    array = np.frombuffer(data, dtype=np.uint8)
    image = cv2.imdecode(array, cv2.IMREAD_COLOR)
    if image is None:
        raise HTTPException(status_code=400, detail='No se pudo decodificar la imagen')
    result = app_state.detect_image(image)
    return {'detections': [d.model_dump() for d in result]}


@router.get('/movil')
def mobile():
    from fastapi.responses import FileResponse

    from app.config import settings

    # Sin caché: si el iPhone se queda con una página vieja, sigue usando código ya corregido (y leía errores técnicos en voz alta)
    return FileResponse(settings.web_dir / 'movil.html', headers={'Cache-Control': 'no-store'})


@router.get('/')
def root():
    from fastapi.responses import FileResponse

    from app.config import settings

    index_path = settings.web_dir / 'index.html'
    return FileResponse(index_path)
