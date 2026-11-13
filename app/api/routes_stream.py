from __future__ import annotations

import asyncio

import cv2
import numpy as np
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse

router = APIRouter()


@router.get('/stream.mjpg')
def stream_mjpg():
    from app.main import app_state

    app_state.start_scene_monitor()

    def generator():
        while True:
            frame = app_state.latest_frame()
            if frame is None:
                frame = np.zeros((480, 640, 3), dtype=np.uint8)
            ok, buffer = cv2.imencode('.jpg', frame)
            if not ok:
                continue
            yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')

    return StreamingResponse(generator(), media_type='multipart/x-mixed-replace; boundary=frame')


@router.websocket('/ws/events')
async def events_ws(websocket: WebSocket):
    await websocket.accept()
    from app.main import app_state

    app_state.register_ws(websocket)
    try:
        while True:
            texto = await websocket.receive_text()
            if texto == 'ping':  # el teléfono pregunta "¿sigues ahí?": así detecta una caída que el navegador no nota
                await websocket.send_json({'type': 'pong'})
    except WebSocketDisconnect:
        pass
    finally:
        app_state.unregister_ws(websocket)  # también si el canal se rompe de otra forma: no se deja un socket muerto en la lista


@router.websocket('/ws/frames')
async def frames_ws(websocket: WebSocket):
    """Entrada de video desde el celular: cada mensaje binario es un JPEG."""
    await websocket.accept()
    from app.core.camera import RemoteCamera
    from app.main import app_state

    camera = app_state.camera
    if not isinstance(camera, RemoteCamera):
        await websocket.close(code=1008, reason='El servidor usa cámara local (CAMERA_SOURCE=local)')
        return
    try:
        while True:
            data = await websocket.receive_bytes()
            # La decodificación va en un hilo para no frenar el event loop; si el pipeline va
            # atrasado el frame anterior se sobrescribe (latest-frame-wins).
            ok = await asyncio.to_thread(camera.push_jpeg, data)
            if not ok:
                await websocket.send_text('frame-invalid')
    except WebSocketDisconnect:
        pass
