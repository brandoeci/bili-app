from __future__ import annotations

from app.config import Settings
from app.core.alerts import AlertManager
from app.core.decision import UMBRALES, conducta, confianza_minima, umbrales
from app.core.fusion import FusionEngine
from app.core.labels import label_es
from app.schemas import Detection

W, H = 480, 640


def test_las_tres_conductas_por_confianza():
    assert conducta('stairs', 0.70, 'P0') == 'avisar'
    assert conducta('stairs', 0.50, 'P0') == 'avisar'          # el borde alto ya avisa
    assert conducta('stairs', 0.30, 'P0') == 'incertidumbre'
    assert conducta('stairs', 0.20, 'P0') == 'callar'


def test_lo_irrelevante_se_calla_aunque_la_confianza_sea_alta():
    assert conducta('stairs', 0.95, 'P3') == 'callar'


def test_la_incertidumbre_solo_se_declara_cerca_o_en_el_camino():
    assert conducta('pothole', 0.30, 'P1') == 'incertidumbre'
    assert conducta('pothole', 0.30, 'P2') == 'callar'          # dudoso y lejos: no se pide detenerse


def test_a_lo_dudoso_a_un_lado_no_pide_detenerse():
    assert conducta('pothole', 0.30, 'P0', direction='center') == 'incertidumbre'
    assert conducta('pothole', 0.30, 'P0', direction='left') == 'callar'
    assert conducta('pothole', 0.80, 'P0', direction='left') == 'avisar'   # lo seguro sí se avisa a un lado


def test_b_el_bordillo_no_tiene_banda_dudosa():
    assert umbrales('curb') == (0.50, 0.50)
    assert conducta('curb', 0.40, 'P0') == 'callar' and conducta('curb', 0.55, 'P0') == 'avisar'


def test_en_la_fusion_lo_dudoso_a_un_lado_se_calla():
    d = FusionEngine(decidir_conducta=True).update([_cruda('pothole', 0.3, (10, 400, 90, 630))], None, (H, W, 3), now=0.0)[0]
    assert d.direction == 'left' and d.conducta == 'callar'


def test_las_clases_sin_tabla_no_tienen_banda_intermedia():
    assert umbrales('person') == (0.35, 0.35)
    assert conducta('person', 0.36, 'P1') == 'avisar' and conducta('person', 0.30, 'P1') == 'callar'


def test_escaleras_con_direccion_comparten_umbrales():
    assert umbrales('stairs_down') == umbrales('stairs') == UMBRALES['stairs']


def test_los_umbrales_son_coherentes():
    for bajo, alto in UMBRALES.values():
        assert 0 < bajo <= alto < 1
    assert confianza_minima() == min(b for b, _ in UMBRALES.values())


def test_los_umbrales_se_cambian_en_la_config():
    tabla = Settings(decision_umbrales={'stairs': [0.3, 0.6]}, _env_file=None).tabla_decision()
    assert tabla['stairs'] == (0.3, 0.6) and tabla['pothole'] == UMBRALES['pothole']


def _cruda(label, conf, bbox, track=1):
    return Detection(track_id=track, label=label, conf=conf, bbox=bbox)


def test_qa3_toda_deteccion_relevante_en_la_banda_intermedia_sale_como_incertidumbre():
    """QA-3 del paper, al pie de la letra: ninguna detección relevante con confianza en la banda intermedia se afirma como clase."""
    casos = 0
    for label, (bajo, alto) in UMBRALES.items():
        if bajo == alto:
            continue
        for conf in (bajo, (bajo + alto) / 2, alto - 0.001):
            # al frente y con la base cerca del borde inferior: muy cerca
            d = FusionEngine(decidir_conducta=True).update([_cruda(label, conf, (200, 300, 280, 630))], None, (H, W, 3), now=0.0)[0]
            if d.priority in ('P0', 'P1'):
                casos += 1
                assert d.conducta == 'incertidumbre', (label, conf, d)
                texto = AlertManager(min_frames=1).evaluate([d], now=0.0)[0].text
                assert label_es(label) not in texto.lower() and texto.startswith('Deténgase')
    assert casos >= 10


def test_la_incertidumbre_tiene_prioridad_maxima_de_voz():
    d = FusionEngine(decidir_conducta=True).update([_cruda('pothole', 0.3, (200, 400, 280, 630))], None, (H, W, 3), now=0.0)[0]
    alerta = AlertManager(min_frames=1).evaluate([d], now=0.0)[0]
    assert alerta.priority == 'P0'


def test_si_se_confirma_despues_se_nombra_la_clase():
    fusion, m = FusionEngine(decidir_conducta=True), AlertManager(min_frames=1)
    dudoso = fusion.update([_cruda('stairs', 0.30, (180, 300, 300, 630))], None, (H, W, 3), now=0.0)[0]
    assert m.evaluate([dudoso], now=0.0)[0].text.startswith('Deténgase')
    seguro = fusion.update([_cruda('stairs', 0.80, (180, 300, 300, 630))], None, (H, W, 3), now=1.5)[0]
    alerta = m.evaluate([seguro], now=1.5)
    assert len(alerta) == 1 and 'escaleras' in alerta[0].text


def test_sin_motor_de_decision_todo_sigue_como_antes():
    d = FusionEngine().update([_cruda('stairs', 0.30, (180, 300, 300, 630))], None, (H, W, 3), now=0.0)[0]
    assert d.conducta is None
    assert 'escaleras' in AlertManager(min_frames=1).evaluate([d], now=0.0)[0].text
