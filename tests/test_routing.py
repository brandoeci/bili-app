from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api.routes_routing import get_cap, get_provider
from app.main import app
from app.routing.base import NotConfigured, PlaceNotFound, ProviderError, RouteNotFound
from app.routing.google import GoogleRoutesProvider, parse_ruta
from app.routing.limiter import DailyCap
from app.routing.models import LatLng, Paso, Ruta
from app.routing.spanish import ADVERTENCIA_BILI, accion_de, decir_distancia, decir_duracion, frase_de_paso

ORIGEN = {'lat': 4.7110, 'lng': -74.0721}
DESTINO = {'lat': 4.7130, 'lng': -74.0700}


def _step(maniobra, dist, a=(4.711, -74.072), b=(4.712, -74.071), texto='Gira'):
    nav = {'instructions': texto}
    if maniobra:
        nav['maneuver'] = maniobra
    return {
        'distanceMeters': dist,
        'navigationInstruction': nav,
        'startLocation': {'latLng': {'latitude': a[0], 'longitude': a[1]}},
        'endLocation': {'latLng': {'latitude': b[0], 'longitude': b[1]}},
    }


def google_response(steps=None, warnings=None):
    steps = steps if steps is not None else [_step('DEPART', 120), _step('TURN_RIGHT', 60), _step('TURN_LEFT', 30)]
    return {
        'routes': [
            {
                'distanceMeters': sum(s['distanceMeters'] for s in steps),
                'duration': '240s',
                'warnings': warnings or [],
                'polyline': {'encodedPolyline': 'abc'},
                'legs': [{'steps': steps}],
            }
        ]
    }


def provider_with(handler):
    return GoogleRoutesProvider('CLAVE-DE-PRUEBA', transport=httpx.MockTransport(handler))


def run(coro):
    return asyncio.run(coro)


# --- español ---------------------------------------------------------------------------------------------------


def test_acciones_en_espanol():
    assert accion_de('TURN_RIGHT') == 'gire a la derecha'
    assert accion_de('TURN_LEFT') == 'gire a la izquierda'
    assert accion_de('DEPART') == 'siga derecho'


def test_maniobra_desconocida_nunca_dice_siga_derecho():
    # Una maniobra que no entendemos puede ser un giro: es más seguro decir "continúe" que "siga derecho".
    assert accion_de('ROUNDABOUT_LEFT') == 'continúe'
    assert accion_de('ALGO_NUEVO') != 'siga derecho'


DISTANCIAS = json.loads((Path(__file__).parent / 'fixtures' / 'distancias.json').read_text(encoding='utf-8'))


@pytest.mark.parametrize('metros,esperado', DISTANCIAS)
def test_distancia_dicha_como_habla_quien_camina(metros, esperado):
    # La misma tabla se prueba en tests/js/nav.test.js: servidor y teléfono deben decir lo mismo
    assert decir_distancia(metros) == esperado


@pytest.mark.parametrize('metros', [150, 999, 1500, 5000, 20000])
def test_nunca_kilometros(metros):
    assert 'kilómetro' not in decir_distancia(metros)


@pytest.mark.parametrize(
    'segundos,esperado',
    [(30, 'un minuto'), (540, 'unos 9 minutos'), (660, 'unos 10 minutos'), (1200, 'unos 20 minutos'), (3480, 'una hora'), (3900, 'una hora y 5 minutos'), (7920, 'unas 2 horas y 10 minutos')],
)
def test_duracion(segundos, esperado):
    assert decir_duracion(segundos) == esperado


def test_frases():
    assert frase_de_paso('gire a la derecha', 47, es_ultimo=False) == 'Gire a la derecha y siga unos 50 metros'
    assert frase_de_paso('gire a la derecha', 3, es_ultimo=False) == 'Gire a la derecha'
    assert frase_de_paso('siga derecho', 40, es_ultimo=True) == 'Siga derecho unos 40 metros hasta llegar a su destino'
    assert frase_de_paso('siga derecho', 47, es_ultimo=False) == 'Siga derecho unos 50 metros'


# --- proveedor de Google ---------------------------------------------------------------------------------------


def test_la_ruta_siempre_se_pide_a_pie():
    visto = {}

    def handler(request: httpx.Request) -> httpx.Response:
        visto['body'] = json.loads(request.content)
        visto['headers'] = request.headers
        return httpx.Response(200, json=google_response())

    run(provider_with(handler).walk_route(LatLng(**ORIGEN), LatLng(**DESTINO)))
    assert visto['body']['travelMode'] == 'WALK'
    # Opciones de tráfico o paradas cambiarían la facturación (y no aplican a pie)
    assert 'routingPreference' not in visto['body']
    assert 'intermediates' not in visto['body']
    assert visto['headers']['X-Goog-Api-Key'] == 'CLAVE-DE-PRUEBA'
    assert 'routes.legs.steps.navigationInstruction' in visto['headers']['X-Goog-FieldMask']


def test_parse_ruta():
    ruta = parse_ruta(google_response(warnings=['Puede faltar andén']))
    assert [p.accion for p in ruta.pasos] == ['siga derecho', 'gire a la derecha', 'gire a la izquierda']
    assert ruta.distancia_m == 210
    assert ruta.duracion_s == 240
    assert ruta.advertencias == ['Puede faltar andén']
    assert ruta.pasos[-1].frase.endswith('hasta llegar a su destino')
    assert ruta.destino == ruta.pasos[-1].fin
    assert ruta.resumen == 'Ruta a pie de unas 2 cuadras. Se tarda unos 4 minutos o más.'


def test_primer_paso_sin_maniobra_es_seguir():
    ruta = parse_ruta(google_response(steps=[_step(None, 80)]))
    assert ruta.pasos[0].accion == 'siga derecho'


def test_sin_ruta_o_sin_pasos_no_se_improvisa():
    with pytest.raises(RouteNotFound):
        parse_ruta({})
    with pytest.raises(RouteNotFound):
        parse_ruta({'routes': [{'distanceMeters': 100, 'legs': [{'steps': []}]}]})


def test_http_de_error_es_error_del_proveedor_sin_filtrar_la_clave():
    def handler(request):
        return httpx.Response(403, json={'error': {'message': 'la clave CLAVE-DE-PRUEBA no sirve'}})

    with pytest.raises(ProviderError) as info:
        run(provider_with(handler).walk_route(LatLng(**ORIGEN), LatLng(**DESTINO)))
    assert 'CLAVE-DE-PRUEBA' not in str(info.value)


def test_error_de_red():
    def handler(request):
        raise httpx.ConnectError('sin red')

    with pytest.raises(ProviderError):
        run(provider_with(handler).walk_route(LatLng(**ORIGEN), LatLng(**DESTINO)))


def test_sin_clave_no_se_construye():
    with pytest.raises(NotConfigured):
        GoogleRoutesProvider('')


def test_geocode_ok_y_sesgo_a_colombia():
    visto = {}

    def handler(request: httpx.Request) -> httpx.Response:
        visto['q'] = dict(request.url.params)
        return httpx.Response(
            200,
            json={
                'status': 'OK',
                'results': [{'formatted_address': 'Cl. 72 #10-34, Bogotá', 'geometry': {'location': {'lat': 4.65, 'lng': -74.06}}}],
            },
        )

    punto, direccion = run(provider_with(handler).geocode('calle 72 con 10', LatLng(**ORIGEN)))
    assert (punto.lat, punto.lng) == (4.65, -74.06)
    assert direccion.startswith('Cl. 72')
    assert visto['q']['components'] == 'country:CO'
    assert visto['q']['region'] == 'co'


def test_geocode_sin_resultados():
    def handler(request):
        return httpx.Response(200, json={'status': 'ZERO_RESULTS', 'results': []})

    with pytest.raises(PlaceNotFound):
        run(provider_with(handler).geocode('xyzxyz', LatLng(**ORIGEN)))


def test_geocode_con_clave_denegada_es_error_del_proveedor():
    def handler(request):
        return httpx.Response(200, json={'status': 'REQUEST_DENIED', 'results': []})

    with pytest.raises(ProviderError):
        run(provider_with(handler).geocode('calle 72', LatLng(**ORIGEN)))


# --- tope diario -------------------------------------------------------------------------------------------------


def test_tope_diario():
    cap = DailyCap(2)
    assert cap.take() and cap.take()
    assert not cap.take()


# --- endpoint ----------------------------------------------------------------------------------------------------


class FakeProvider:
    def __init__(self, ruta=None, geo=None, error=None):
        self.ruta, self.geo, self.error = ruta, geo, error
        self.calls: list[str] = []

    async def walk_route(self, origen, destino):
        self.calls.append('ruta')
        if self.error:
            raise self.error
        return self.ruta.model_copy(deep=True)

    async def reverse(self, punto):
        self.calls.append('reverse')
        if isinstance(self.geo, Exception):
            raise self.geo
        return getattr(self, 'calle', 'Carrera 7')

    async def geocode(self, texto, cerca):
        self.calls.append('geo')
        self.cercas = [*getattr(self, 'cercas', []), cerca]
        geo = self.geo.pop(0) if isinstance(self.geo, list) else self.geo   # una lista: una respuesta por búsqueda
        if isinstance(geo, Exception):
            raise geo
        return geo


def ruta_demo(distancia=200):
    p = lambda lat, lng: LatLng(lat=lat, lng=lng)  # noqa: E731
    paso = Paso(indice=0, maniobra='DEPART', accion='siga derecho', distancia_m=distancia, frase='Siga derecho', inicio=p(4.7, -74), fin=p(4.71, -74.01))
    return Ruta(distancia_m=distancia, duracion_s=180, resumen='Ruta', advertencias=['del proveedor'], pasos=[paso], polilinea='x', destino=p(4.71, -74.01))


@pytest.fixture
def api():
    provider, cap = FakeProvider(ruta=ruta_demo()), DailyCap(100)
    app.dependency_overrides[get_provider] = lambda: provider
    app.dependency_overrides[get_cap] = lambda: cap
    yield TestClient(app), provider, cap
    app.dependency_overrides.clear()


def test_endpoint_con_coordenadas(api):
    client, provider, _ = api
    r = client.post('/v1/rutas', json={'origen': ORIGEN, 'destino': DESTINO})
    assert r.status_code == 200
    body = r.json()
    assert body['advertencias'][0] == ADVERTENCIA_BILI  # la de Bili va primero
    assert 'del proveedor' in body['advertencias']  # y se conserva la del proveedor
    assert body['destino_confirmado'] is None
    assert provider.calls == ['ruta']


def test_endpoint_con_texto_geocodifica_y_devuelve_la_direccion(api):
    client, provider, _ = api
    provider.geo = (LatLng(lat=4.65, lng=-74.06), 'Cl. 72 #10-34, Bogotá')
    r = client.post('/v1/rutas', json={'origen': ORIGEN, 'destino_texto': 'calle 72 con 10'})
    assert r.status_code == 200
    assert r.json()['destino_confirmado'] == 'Cl. 72 #10-34, Bogotá'
    assert provider.calls == ['geo', 'ruta']


def test_sin_gps_el_origen_dicho_se_busca_y_el_destino_se_busca_cerca_de_el(api):
    client, provider, _ = api
    aqui = LatLng(lat=4.657, lng=-74.056)
    provider.geo = [(aqui, 'Cl. 72 & Cra. 7, Bogotá'), (LatLng(lat=4.66, lng=-74.06), 'Museo, Bogotá')]
    r = client.post('/v1/rutas', json={'origen_texto': 'calle 72 con séptima', 'destino_texto': 'el museo'})
    assert r.status_code == 200
    assert r.json()['origen_confirmado'] == 'Cl. 72 & Cra. 7, Bogotá'
    assert provider.calls == ['geo', 'geo', 'ruta']
    assert provider.cercas[1] == aqui   # el destino se busca alrededor de donde la persona dijo que está


def test_origen_dicho_que_no_existe_lo_dice_claro(api):
    client, provider, _ = api
    provider.geo = PlaceNotFound('sin resultados')
    r = client.post('/v1/rutas', json={'origen_texto': 'calle inventada', 'destino_texto': 'el museo'})
    assert r.status_code == 404 and 'donde me dijo que está' in r.json()['detail']


def test_origen_obligatorio_y_unico(api):
    client, _, _ = api
    assert client.post('/v1/rutas', json={'destino': DESTINO}).status_code == 422
    assert client.post('/v1/rutas', json={'origen': ORIGEN, 'origen_texto': 'calle 72', 'destino': DESTINO}).status_code == 422


def test_el_endpoint_no_acepta_modo(api):
    client, _, _ = api
    r = client.post('/v1/rutas', json={'origen': ORIGEN, 'destino': DESTINO, 'modo': 'DRIVE'})
    assert r.status_code == 422


def test_destino_obligatorio_y_unico(api):
    client, _, _ = api
    assert client.post('/v1/rutas', json={'origen': ORIGEN}).status_code == 422
    both = {'origen': ORIGEN, 'destino': DESTINO, 'destino_texto': 'parque'}
    assert client.post('/v1/rutas', json=both).status_code == 422


def test_coordenadas_invalidas(api):
    client, _, _ = api
    r = client.post('/v1/rutas', json={'origen': {'lat': 123, 'lng': 0}, 'destino': DESTINO})
    assert r.status_code == 422


def test_lugar_no_encontrado(api):
    client, provider, _ = api
    provider.geo = PlaceNotFound('x')
    r = client.post('/v1/rutas', json={'origen': ORIGEN, 'destino_texto': 'xyzxyz'})
    assert r.status_code == 404
    assert 'lugar' in r.json()['detail']


def test_sin_ruta_a_pie(api):
    client, provider, _ = api
    provider.error = RouteNotFound('x')
    r = client.post('/v1/rutas', json={'origen': ORIGEN, 'destino': DESTINO})
    assert r.status_code == 404
    assert 'a pie' in r.json()['detail']


def test_fallo_del_proveedor_no_filtra_detalles(api):
    client, provider, _ = api
    provider.error = ProviderError('HTTP 403 con la clave SECRETA')
    r = client.post('/v1/rutas', json={'origen': ORIGEN, 'destino': DESTINO})
    assert r.status_code == 502
    assert 'SECRETA' not in r.text


def test_demasiado_lejos_dice_que_lugar_encontro(api):
    client, provider, _ = api
    provider.ruta = ruta_demo(distancia=45000)
    provider.geo = (LatLng(lat=4.65, lng=-74.06), 'Cl. 72 #10-34, Medellín')
    r = client.post('/v1/rutas', json={'origen': ORIGEN, 'destino_texto': 'calle 72 con 10'})
    assert r.status_code == 422
    detalle = r.json()['detail']
    assert 'Medellín' in detalle and '45 kilómetros' in detalle  # la persona oye qué se encontró y a cuánto queda


def test_una_caminata_larga_pero_posible_si_se_ofrece(api):
    client, provider, _ = api
    provider.ruta = ruta_demo(distancia=12000)  # antes se rechazaba desde 10 km
    r = client.post('/v1/rutas', json={'origen': ORIGEN, 'destino': DESTINO})
    assert r.status_code == 200
    assert r.json()['distancia_m'] == 12000


def test_tope_diario_devuelve_429(api):
    client, _, _ = api
    app.dependency_overrides[get_cap] = lambda: DailyCap(0)
    r = client.post('/v1/rutas', json={'origen': ORIGEN, 'destino': DESTINO})
    assert r.status_code == 429


def test_sin_clave_responde_503(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, 'google_maps_api_key', '')
    app.dependency_overrides.clear()
    get_provider.cache_clear()
    r = TestClient(app).post('/v1/rutas', json={'origen': ORIGEN, 'destino': DESTINO})
    assert r.status_code == 503
    get_provider.cache_clear()


# --- dónde está la persona (como Waze sin destino) ----------------------------------------------------------------


def _reverse(results, status='OK'):
    return lambda request: httpx.Response(200, json={'status': status, 'results': results})


def test_reverse_prefiere_la_esquina():
    results = [
        {'types': ['route'], 'formatted_address': 'Cra. 7, Bogotá', 'address_components': [{'long_name': 'Carrera 7', 'types': ['route']}]},
        {'types': ['intersection'], 'formatted_address': 'Cl 72 & Ak 7, Chapinero, Bogotá', 'address_components': []},
    ]
    assert run(provider_with(_reverse(results)).reverse(LatLng(**ORIGEN))) == 'Cl 72 & Ak 7'


def test_reverse_sin_esquina_usa_la_calle():
    results = [{'types': ['route'], 'formatted_address': 'x', 'address_components': [{'long_name': 'Carrera 7', 'types': ['route']}]}]
    assert run(provider_with(_reverse(results)).reverse(LatLng(**ORIGEN))) == 'Carrera 7'


def test_reverse_sin_resultados_es_none():
    assert run(provider_with(_reverse([], 'ZERO_RESULTS')).reverse(LatLng(**ORIGEN))) is None


def test_reverse_con_error_del_proveedor():
    with pytest.raises(ProviderError):
        run(provider_with(_reverse([], 'REQUEST_DENIED')).reverse(LatLng(**ORIGEN)))


def test_reverse_pide_solo_esquina_o_calle_y_va_con_la_clave():
    visto = {}

    def handler(request):
        visto['q'] = dict(request.url.params)
        return httpx.Response(200, json={'status': 'ZERO_RESULTS', 'results': []})

    run(provider_with(handler).reverse(LatLng(**ORIGEN)))
    assert visto['q']['result_type'] == 'intersection|route'
    assert visto['q']['language'] == 'es'


def test_endpoint_ubicacion(api):
    client, provider, _ = api
    provider.calle = 'Cl 72 & Ak 7'
    r = client.post('/v1/ubicacion', json=ORIGEN)
    assert r.status_code == 200
    assert r.json() == {'calle': 'Cl 72 & Ak 7'}


def test_ubicacion_se_pide_por_post_para_no_dejar_coordenadas_en_la_url(api):
    client, _, _ = api
    assert client.get('/v1/ubicacion', params=ORIGEN).status_code == 405


def test_ubicacion_valida_coordenadas_y_cuenta_para_el_tope(api):
    client, _, _ = api
    assert client.post('/v1/ubicacion', json={'lat': 123, 'lng': 0}).status_code == 422
    app.dependency_overrides[get_cap] = lambda: DailyCap(0)
    assert client.post('/v1/ubicacion', json=ORIGEN).status_code == 429


def test_ubicacion_con_proveedor_caido(api):
    client, provider, _ = api
    provider.geo = ProviderError('caído')
    r = client.post('/v1/ubicacion', json=ORIGEN)
    assert r.status_code == 502
    assert 'caído' not in r.text
