from __future__ import annotations

from functools import lru_cache

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from app.config import settings
from app.routing.base import NotConfigured, PlaceNotFound, ProviderError, RouteNotFound, RouteProvider
from app.routing.google import GoogleRoutesProvider
from app.routing.limiter import DailyCap
from app.routing.models import LatLng, Ruta, RutaRequest
from app.routing.osm import CrucesLocales
from app.routing.polyline import decode_polyline
from app.routing.spanish import ADVERTENCIA_BILI

router = APIRouter(prefix='/v1')


@lru_cache(maxsize=1)
def get_provider() -> RouteProvider:
    try:
        return GoogleRoutesProvider(settings.google_maps_api_key, timeout=settings.routes_timeout_s)
    except NotConfigured as exc:
        raise HTTPException(status_code=503, detail='Las rutas no están configuradas en el servidor') from exc


@lru_cache(maxsize=1)
def get_cap() -> DailyCap:
    return DailyCap(settings.routes_daily_limit)


@lru_cache(maxsize=1)
def get_cruces() -> CrucesLocales | None:
    """Índice de cruces de OpenStreetMap. None si el archivo no se descargó (la ruta funciona igual, con aviso)."""
    ruta = settings.base_dir / settings.osm_cruces_path
    if not ruta.exists():
        return None
    try:
        return CrucesLocales.desde_archivo(ruta)
    except ProviderError:
        return None


def _take(cap: DailyCap) -> None:
    if not cap.take():
        raise HTTPException(status_code=429, detail='Se alcanzó el límite diario de rutas')


@router.post('/rutas', response_model=Ruta)
async def calcular_ruta(
    req: RutaRequest,
    provider: RouteProvider = Depends(get_provider),
    cap: DailyCap = Depends(get_cap),
    osm: CrucesLocales | None = Depends(get_cruces),
):
    """Ruta a pie del origen al destino. No se guarda nada: ni ubicación ni ruta."""
    try:
        destino, confirmado = req.destino, None
        if destino is None:
            _take(cap)
            destino, confirmado = await provider.geocode(req.destino_texto or '', req.origen)
        _take(cap)
        ruta = await provider.walk_route(req.origen, destino)
    except PlaceNotFound as exc:
        raise HTTPException(status_code=404, detail='No encontré ese lugar') from exc
    except RouteNotFound as exc:
        raise HTTPException(status_code=404, detail='No encontré una ruta a pie hasta ese destino') from exc
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail='No se pudo calcular la ruta ahora') from exc

    if ruta.distancia_m > settings.routes_max_walk_m:
        # Se dice qué lugar se encontró: si Google lo ubicó mal, la persona se entera y puede corregirlo.
        lugar = confirmado or 'ese lugar'
        km = round(ruta.distancia_m / 1000)
        raise HTTPException(status_code=422, detail=f'Encontré {lugar}, pero queda a {km} kilómetros. Es demasiado lejos para ir a pie.')

    # Cruces de calle (OpenStreetMap). Si falla, la ruta sigue valiendo, pero el cliente debe saber que no hay datos.
    try:
        if osm is None:
            raise ProviderError('sin archivo de cruces')
        ruta.cruces = osm.cruces_cerca(decode_polyline(ruta.polilinea))
        ruta.cruces_consultados = True
    except (ProviderError, ValueError):
        ruta.cruces, ruta.cruces_consultados = [], False
        ruta.advertencias.append('No pude consultar los cruces de calle. Avance con precaución en cada esquina.')

    # La advertencia de Bili va siempre primero; las del proveedor (p. ej. "puede faltar andén") se conservan.
    ruta.advertencias = [ADVERTENCIA_BILI, *ruta.advertencias]
    ruta.destino_confirmado = confirmado
    return ruta


@router.post('/ubicacion')
async def ubicacion(
    punto: LatLng,
    provider: RouteProvider = Depends(get_provider),
    cap: DailyCap = Depends(get_cap),
):
    """En qué calle está la persona. Es POST a propósito: así las coordenadas no quedan escritas en la URL de los registros."""
    _take(cap)
    try:
        return {'calle': await provider.reverse(punto)}
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail='No pude saber dónde está ahora') from exc


@router.get('/{nombre}.js', include_in_schema=False)
def script_del_telefono(nombre: str):
    """Lógica que corre en el teléfono (seguimiento de ruta y diálogo por voz)."""
    if nombre not in {'nav', 'voice', 'conexion', 'voz'}:
        raise HTTPException(status_code=404, detail='No existe')
    return FileResponse(settings.web_dir / f'{nombre}.js', media_type='application/javascript', headers={'Cache-Control': 'no-cache'})
