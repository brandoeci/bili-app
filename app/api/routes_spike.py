"""Prueba de YOLO dentro del teléfono (ONNX). SOLO PARA DESARROLLO.

Se activa con ONNX_SPIKE=1. Sirve la página de medición y los modelos exportados: nunca debe estar activa en una
instalación pública, porque entrega el modelo propio a cualquiera que lo pida. Los .onnx se generan con
`yolo export format=onnx imgsz=640` y se copian a models/onnx/.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.config import settings

router = APIRouter()

MODELOS = {'yolo26n', 'yolo26s', 'bili-hazards', 'bili-hazards-v6b', 'bili-hazards-v7a'}
FORMAS = {'640x480', '416x320'}  # alto x ancho de la entrada, vertical como la cámara del teléfono
PERMITIDOS = MODELOS | {f'{m}_{f}' for m in MODELOS for f in FORMAS}
MODULOS = {'deteccion', 'seguimiento', 'fusion', 'alertas', 'decision', 'cercania', 'etiquetas'}  # web/bili/

# Con estas dos cabeceras el navegador permite hilos en WebAssembly (SharedArrayBuffer), que aceleran el modelo.
AISLADO = {
    'Cross-Origin-Opener-Policy': 'same-origin',
    'Cross-Origin-Embedder-Policy': 'require-corp',
    'Cache-Control': 'no-store',
}


@router.get('/onnx-spike', include_in_schema=False)
def pagina_de_prueba():
    return FileResponse(settings.web_dir / 'onnx-spike.html', media_type='text/html', headers=AISLADO)


@router.get('/bili/{nombre}.js', include_in_schema=False)
def modulo_del_celular(nombre: str):
    """Los módulos de web/bili/ (detector, seguimiento, motor de decisión) que la página importa."""
    if nombre not in MODULOS:
        raise HTTPException(status_code=404, detail='No existe')
    return FileResponse(settings.web_dir / 'bili' / f'{nombre}.js', media_type='application/javascript',
                        headers={**AISLADO, 'Cross-Origin-Resource-Policy': 'same-origin'})


@router.get('/v1/onnx/{nombre}.onnx', include_in_schema=False)
def modelo_onnx(nombre: str):
    if nombre not in PERMITIDOS:  # lista cerrada: el nombre nunca se usa para armar una ruta libre
        raise HTTPException(status_code=404, detail='No existe')
    ruta = settings.base_dir / 'models' / 'onnx' / f'{nombre}.onnx'
    if not ruta.is_file():
        raise HTTPException(status_code=404, detail='Falta exportar el modelo a models/onnx/')
    return FileResponse(ruta, media_type='application/octet-stream', headers={**AISLADO, 'Cross-Origin-Resource-Policy': 'same-origin'})
