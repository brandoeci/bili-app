from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.api.routes_routing import get_cap, get_cruces, get_provider
from app.main import app
from app.routing.base import ProviderError
from app.routing.limiter import DailyCap
from app.routing.models import LatLng
from app.routing.osm import CrucesLocales, clasificar, fusionar
from app.routing.polyline import decode_polyline, distancia_m
from tests.test_routing import DESTINO, ORIGEN, FakeProvider, ruta_demo


def test_decodifica_polilinea_de_ejemplo_de_google():
    pts = decode_polyline('_p~iF~ps|U_ulLnnqC_mqNvxq`@')
    assert [(p.lat, p.lng) for p in pts] == [(38.5, -120.2), (40.7, -120.95), (43.252, -126.453)]


def test_polilinea_truncada_es_error():
    with pytest.raises(ValueError):
        decode_polyline('_p~iF~ps|U_ulLnnq')


def test_distancia():
    a, b = LatLng(lat=4.65, lng=-74.06), LatLng(lat=4.651, lng=-74.06)
    assert 108 < distancia_m(a, b) < 114


@pytest.mark.parametrize(
    'tags,esperado',
    [
        ({'highway': 'traffic_signals'}, 'semaforo'),
        ({'highway': 'crossing', 'crossing': 'traffic_signals'}, 'semaforo'),
        ({'highway': 'crossing', 'crossing': 'zebra'}, 'cebra'),
        ({'highway': 'crossing', 'crossing': 'uncontrolled'}, 'cebra'),
        ({'highway': 'crossing'}, 'cruce'),
    ],
)
def test_clasificar(tags, esperado):
    assert clasificar(tags) == esperado


def test_fusion_une_nodos_cercanos_y_gana_el_semaforo():
    base = 4.65
    elementos = [
        {'lat': base, 'lon': -74.06, 'tags': {'highway': 'crossing'}},
        {'lat': base + 0.00004, 'lon': -74.06, 'tags': {'highway': 'traffic_signals'}},  # ~4 m
        {'lat': base + 0.001, 'lon': -74.06, 'tags': {'highway': 'crossing', 'crossing': 'zebra'}},  # ~111 m
    ]
    cruces = fusionar(elementos)
    assert sorted(c.tipo for c in cruces) == ['cebra', 'semaforo']


def nodo(norte_m, este_m, **tags):
    return {'lat': 4.65 + norte_m / 111195, 'lon': -74.06 + este_m / (111195 * 0.9971), 'tags': tags}


RUTA_NORTE = [LatLng(lat=4.65, lng=-74.06), LatLng(lat=4.65 + 500 / 111195, lng=-74.06)]  # 500 m al norte


def test_indice_local_encuentra_solo_cruces_pegados_a_la_ruta():
    idx = CrucesLocales(
        [
            nodo(200, 3, highway='crossing', crossing='traffic_signals'),  # sobre la ruta
            nodo(300, 40, highway='crossing'),  # a 40 m: es de otra calle
            nodo(900, 0, highway='crossing'),  # más allá del final
        ]
    )
    cruces = idx.cruces_cerca(RUTA_NORTE)
    assert [c.tipo for c in cruces] == ['semaforo']


def test_indice_local_une_los_dos_lados_del_mismo_cruce():
    idx = CrucesLocales([nodo(200, 4, highway='crossing'), nodo(206, -4, highway='crossing', crossing='zebra')])
    cruces = idx.cruces_cerca(RUTA_NORTE)
    assert len(cruces) == 1 and cruces[0].tipo == 'cebra'


def test_indice_local_con_celdas_vecinas():
    # La ruta cruza el límite entre celdas del índice: no se debe perder ningún cruce
    idx = CrucesLocales([nodo(m, 1, highway='crossing') for m in (50, 150, 250, 350, 450)])
    assert len(idx.cruces_cerca(RUTA_NORTE)) == 5


def test_archivo_de_cruces(tmp_path):
    f = tmp_path / 'c.json'
    f.write_text(json.dumps({'nodos': [nodo(100, 0, highway='crossing')]}), encoding='utf-8')
    assert CrucesLocales.desde_archivo(f).total == 1
    with pytest.raises(ProviderError):
        CrucesLocales.desde_archivo(tmp_path / 'no_existe.json')
    (tmp_path / 'roto.json').write_text('{no es json', encoding='utf-8')
    with pytest.raises(ProviderError):
        CrucesLocales.desde_archivo(tmp_path / 'roto.json')


# --- endpoint ------------------------------------------------------------------------------------------------------


class FakeOsm:
    def __init__(self, cruces=None, error=None):
        self.cruces, self.error = cruces or [], error

    def cruces_cerca(self, puntos):
        if self.error:
            raise self.error
        return self.cruces


@pytest.fixture
def api():
    from app.routing.models import Cruce

    ruta = ruta_demo()
    ruta.polilinea = '_p~iF~ps|U_ulLnnqC'  # polilínea válida para decodificar
    osm = FakeOsm([Cruce(lat=4.65, lng=-74.06, tipo='semaforo')])
    app.dependency_overrides[get_provider] = lambda: FakeProvider(ruta=ruta)
    app.dependency_overrides[get_cap] = lambda: DailyCap(100)
    app.dependency_overrides[get_cruces] = lambda: osm
    yield TestClient(app), osm
    app.dependency_overrides.clear()


def test_la_ruta_incluye_los_cruces(api):
    client, _ = api
    r = client.post('/v1/rutas', json={'origen': ORIGEN, 'destino': DESTINO})
    assert r.status_code == 200
    body = r.json()
    assert body['cruces_consultados'] is True
    assert body['cruces'] == [{'lat': 4.65, 'lng': -74.06, 'tipo': 'semaforo'}]


def test_si_osm_falla_la_ruta_sigue_y_el_cliente_lo_sabe(api):
    client, osm = api
    osm.error = ProviderError('caído')
    r = client.post('/v1/rutas', json={'origen': ORIGEN, 'destino': DESTINO})
    assert r.status_code == 200
    body = r.json()
    assert body['cruces_consultados'] is False  # no se debe interpretar como "no hay cruces"
    assert body['cruces'] == []
    assert any('cruces de calle' in a for a in body['advertencias'])


def test_sin_archivo_de_cruces_la_ruta_sigue_y_avisa(api):
    client, _ = api
    app.dependency_overrides[get_cruces] = lambda: None
    r = client.post('/v1/rutas', json={'origen': ORIGEN, 'destino': DESTINO})
    assert r.status_code == 200
    assert r.json()['cruces_consultados'] is False
    assert any('cruces de calle' in a for a in r.json()['advertencias'])


def test_solo_se_sirven_los_scripts_del_telefono():
    c = TestClient(app)
    assert c.get('/v1/voice.js').status_code == 200
    assert c.get('/v1/conexion.js').status_code == 200
    assert c.get('/v1/voz.js').status_code == 200
    assert c.get('/v1/secreto.js').status_code == 404
    assert c.get('/v1/..%2Fconfig.js').status_code in {404, 422}


def test_se_sirve_nav_js():
    r = TestClient(app).get('/v1/nav.js')
    assert r.status_code == 200
    assert 'javascript' in r.headers['content-type']
    assert 'Navigator' in r.text
