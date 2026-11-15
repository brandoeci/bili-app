"""Bili en la nube (Google Cloud Run): lo único que el teléfono no puede hacer solo.

El teléfono detecta, decide y habla por su cuenta (/local). Le falta un sitio fijo de dónde bajar la página y los modelos la primera
vez, y alguien que guarde la clave de Google para pedir rutas. Este servidor hace solo eso: no recibe imágenes, no tiene PyTorch ni
WebSocket. Todo pide la clave (?clave= la primera vez, después la cookie), porque entrega el modelo propio.

    uvicorn app.nube:app --port 8080        # con ONNX_SPIKE_CLAVE y GOOGLE_MAPS_API_KEY en el entorno
"""
from __future__ import annotations

from fastapi import FastAPI

from app.api.routes_routing import router as rutas
from app.api.routes_spike import SoloPruebaPorTunel, router as telefono
from app.config import settings

app = FastAPI(title='Bili (nube)', docs_url=None, redoc_url=None, openapi_url=None)
app.include_router(telefono)
app.include_router(rutas)
app.add_middleware(SoloPruebaPorTunel, clave=settings.onnx_spike_clave, siempre=True)
