from __future__ import annotations

import logging

import httpx

from app.routing.base import NotConfigured, PlaceNotFound, ProviderError, RouteNotFound
from app.routing.models import LatLng, Paso, Ruta
from app.routing.spanish import accion_de, frase_de_paso, resumen_de_ruta

# La clave de Geocoding viaja en la URL: sin esto httpx la escribiría en los registros.
logging.getLogger('httpx').setLevel(logging.WARNING)

ROUTES_URL = 'https://routes.googleapis.com/directions/v2:computeRoutes'
GEOCODE_URL = 'https://maps.googleapis.com/maps/api/geocode/json'

# Sin opciones de tráfico ni paradas: así la llamada se factura como Essentials.
FIELD_MASK = ','.join(
    [
        'routes.distanceMeters',
        'routes.duration',
        'routes.warnings',
        'routes.polyline.encodedPolyline',
        'routes.legs.steps.distanceMeters',
        'routes.legs.steps.navigationInstruction',
        'routes.legs.steps.startLocation',
        'routes.legs.steps.endLocation',
    ]
)

# Caja (en grados, ~17 km) alrededor del origen para sesgar la búsqueda de direcciones.
GEOCODE_BIAS_DEG = 0.15


def _latlng(loc: dict) -> LatLng:
    ll = loc['latLng']
    return LatLng(lat=ll['latitude'], lng=ll['longitude'])


def _segundos(duracion: str | None) -> int:
    # Google devuelve "660s"
    try:
        return int(float((duracion or '0s').rstrip('s')))
    except ValueError:
        return 0


def parse_ruta(data: dict) -> Ruta:
    routes = data.get('routes') or []
    if not routes:
        raise RouteNotFound('sin ruta a pie')
    route = routes[0]
    raw_steps = [s for leg in route.get('legs', []) for s in leg.get('steps', [])]
    if not raw_steps:
        # Sin pasos no hay indicaciones que dictar; no se improvisa una ruta.
        raise RouteNotFound('la respuesta no trae pasos')

    pasos: list[Paso] = []
    for i, s in enumerate(raw_steps):
        nav = s.get('navigationInstruction') or {}
        maniobra = nav.get('maneuver') or ('DEPART' if i == 0 else 'MANEUVER_UNSPECIFIED')
        accion = accion_de(maniobra)
        dist = int(s.get('distanceMeters', 0))
        pasos.append(
            Paso(
                indice=i,
                maniobra=maniobra,
                accion=accion,
                distancia_m=dist,
                frase=frase_de_paso(accion, dist, es_ultimo=i == len(raw_steps) - 1),
                detalle=nav.get('instructions'),
                inicio=_latlng(s['startLocation']),
                fin=_latlng(s['endLocation']),
            )
        )

    distancia = int(route.get('distanceMeters', sum(p.distancia_m for p in pasos)))
    duracion = _segundos(route.get('duration'))
    return Ruta(
        distancia_m=distancia,
        duracion_s=duracion,
        resumen=resumen_de_ruta(distancia, duracion),
        advertencias=list(route.get('warnings') or []),
        pasos=pasos,
        polilinea=(route.get('polyline') or {}).get('encodedPolyline', ''),
        destino=pasos[-1].fin,
    )


class GoogleRoutesProvider:
    def __init__(self, api_key: str, timeout: float = 8.0, transport: httpx.AsyncBaseTransport | None = None):
        if not api_key:
            raise NotConfigured('Falta GOOGLE_MAPS_API_KEY')
        self._key = api_key
        self._client = httpx.AsyncClient(timeout=timeout, transport=transport)

    async def walk_route(self, origen: LatLng, destino: LatLng) -> Ruta:
        body = {
            'origin': {'location': {'latLng': {'latitude': origen.lat, 'longitude': origen.lng}}},
            'destination': {'location': {'latLng': {'latitude': destino.lat, 'longitude': destino.lng}}},
            'travelMode': 'WALK',  # fijo: no hay forma de pedir otro modo
            'languageCode': 'es-419',
            'units': 'METRIC',
        }
        headers = {'X-Goog-Api-Key': self._key, 'X-Goog-FieldMask': FIELD_MASK}
        try:
            response = await self._client.post(ROUTES_URL, json=body, headers=headers)
        except httpx.HTTPError as exc:
            raise ProviderError(f'sin conexión con el proveedor ({type(exc).__name__})') from exc
        if response.status_code != 200:
            raise ProviderError(f'el proveedor respondió HTTP {response.status_code}')
        return parse_ruta(response.json())

    async def geocode(self, texto: str, cerca: LatLng) -> tuple[LatLng, str]:
        d = GEOCODE_BIAS_DEG
        params = {
            'address': texto,
            'region': 'co',
            'components': 'country:CO',
            'bounds': f'{cerca.lat - d},{cerca.lng - d}|{cerca.lat + d},{cerca.lng + d}',
            'language': 'es',
            'key': self._key,
        }
        try:
            response = await self._client.get(GEOCODE_URL, params=params)
        except httpx.HTTPError as exc:
            raise ProviderError(f'sin conexión con el proveedor ({type(exc).__name__})') from exc
        if response.status_code != 200:
            raise ProviderError(f'el proveedor respondió HTTP {response.status_code}')
        data = response.json()
        status = data.get('status')
        if status == 'ZERO_RESULTS':
            raise PlaceNotFound('sin resultados')
        if status != 'OK' or not data.get('results'):
            raise ProviderError(f'geocodificación: {status}')
        best = data['results'][0]
        loc = best['geometry']['location']
        return LatLng(lat=loc['lat'], lng=loc['lng']), best.get('formatted_address', texto)

    async def reverse(self, punto: LatLng) -> str | None:
        """Calle (o esquina) donde está la persona. Prefiere la esquina: "Cl 72 & Ak 7" dice más que "Calle 72"."""
        params = {
            'latlng': f'{punto.lat},{punto.lng}',
            'result_type': 'intersection|route',
            'language': 'es',
            'key': self._key,
        }
        try:
            response = await self._client.get(GEOCODE_URL, params=params)
        except httpx.HTTPError as exc:
            raise ProviderError(f'sin conexión con el proveedor ({type(exc).__name__})') from exc
        if response.status_code != 200:
            raise ProviderError(f'el proveedor respondió HTTP {response.status_code}')
        data = response.json()
        status = data.get('status')
        if status == 'ZERO_RESULTS':
            return None
        if status != 'OK':
            raise ProviderError(f'geocodificación inversa: {status}')
        results = data.get('results', [])
        for r in results:
            if 'intersection' in r.get('types', []):
                return r['formatted_address'].split(',')[0].strip()
        for r in results:
            for c in r.get('address_components', []):
                if 'route' in c.get('types', []):
                    return c['long_name']
        return None
