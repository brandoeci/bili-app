from __future__ import annotations

from app.config import Settings
from app.core.alerts import AlertManager
from app.core.fusion import FusionEngine
from app.core.proximity import ProximityConfig, Thresholds, spoken_for_zone
from app.schemas import Detection

CFG = ProximityConfig()


# --- zonas -------------------------------------------------------------------------------------------------------------------------------

def test_las_zonas_siguen_el_orden_de_cercania_para_cada_familia():
    assert [CFG.zone('chair', d) for d in (1.0, 1.7, 3.0, 6.0)] == ['muy_cerca', 'urgente', 'aviso', 'lejos']
    assert [CFG.zone('pole', d) for d in (1.8, 2.6, 4.0, 8.0)] == ['muy_cerca', 'urgente', 'aviso', 'lejos']


def test_los_objetos_del_suelo_usan_umbrales_mas_altos_que_los_de_tamano():
    # misma estimación, otra familia: a 2,5 m una silla es 'aviso' pero un poste es 'urgente'
    assert CFG.zone('chair', 2.5) == 'aviso' and CFG.zone('pole', 2.5) == 'urgente'


def test_los_valores_de_las_fotos_reales_caen_en_la_zona_correcta():
    # silla a 0,3 / 1 / 2 m medidos con metro -> la app estimó 0,98 / 1,43 / 2,09
    assert [CFG.zone('chair', d) for d in (0.98, 1.43, 2.09)] == ['muy_cerca', 'muy_cerca', 'aviso']
    # poste: 0,3 / 1 / 2 m -> 1,84 / 2,01 / 2,63: el de 1 m queda 'muy_cerca' y el de 2 m, no
    assert [CFG.zone('pole', d) for d in (1.84, 2.01, 2.63)] == ['muy_cerca', 'muy_cerca', 'urgente']


def test_histeresis_no_deja_parpadear_en_el_borde():
    z = CFG.zone('chair', 1.4)
    assert z == 'muy_cerca'
    assert CFG.zone('chair', 1.55, previous=z) == 'muy_cerca'      # apenas pasó el límite de 1,5: sigue 'muy_cerca'
    assert CFG.zone('chair', 1.8, previous=z) == 'urgente'         # ya se alejó claramente
    assert CFG.zone('chair', 1.55) == 'urgente'                    # sin historial no hay histéresis


def test_acercarse_cambia_de_zona_sin_demora():
    assert CFG.zone('chair', 1.4, previous='aviso') == 'muy_cerca'


def test_umbrales_personalizados():
    cfg = ProximityConfig(size=Thresholds(1.0, 1.5, 2.0))
    assert cfg.zone('chair', 1.2) == 'urgente' and cfg.zone('chair', 5.0) == 'lejos'


def test_los_umbrales_se_leen_de_la_configuracion():
    s = Settings(prox_size_near_m=1.1, prox_ground_warn_m=7.0, _env_file=None)
    cfg = s.proximity_config()
    assert cfg.size.near == 1.1 and cfg.ground.warn == 7.0 and cfg.size.urgent == 2.0


def test_el_orden_de_los_umbrales_por_defecto_es_creciente():
    for t in (CFG.size, CFG.ground):
        assert 0 < t.near < t.urgent < t.warn


# --- prioridad con piso por zona ---------------------------------------------------------------------------------------------------------

def test_un_obstaculo_muy_cerca_y_al_frente_es_p0_aunque_la_distancia_diga_otra_cosa():
    # una silla al frente con estimación de 1,4 m daba P1 (<1,5 m); 'muy cerca' no la deja en algo menor que P1, y los peligros del suelo suben a P0
    assert FusionEngine.priority('chair', 1.4, 'center', None, 'muy_cerca') == 'P1'
    assert FusionEngine.priority('pole', 2.0, 'center', None, 'muy_cerca') == 'P0'
    assert FusionEngine.priority('obstacle', 2.0, 'left', None, 'muy_cerca') == 'P0'


def test_el_piso_nunca_baja_una_prioridad_y_la_tapa_sigue_sin_avisar():
    assert FusionEngine.priority('car', 1.0, 'center', None, 'muy_cerca') == 'P0'
    assert FusionEngine.priority('person', 0.5, 'center', None, 'aviso') == FusionEngine.priority('person', 0.5, 'center')
    assert FusionEngine.priority('manhole', 1.0, 'center', None, 'muy_cerca') == 'P3'


def test_urgente_al_frente_es_al_menos_p1_y_a_un_lado_no_cambia():
    assert FusionEngine.priority('chair', 2.9, 'center', None, 'urgente') == 'P1'
    assert FusionEngine.priority('chair', 2.9, 'left', None, 'urgente') == FusionEngine.priority('chair', 2.9, 'left')


def test_sin_zona_la_prioridad_es_la_de_siempre():
    assert FusionEngine.priority('person', 1.0, 'center') == 'P0'
    assert FusionEngine.priority('chair', 10, 'center') == 'P3'


# --- fusión y alertas --------------------------------------------------------------------------------------------------------------------

def test_la_fusion_pone_zona_en_las_detecciones():
    out = FusionEngine().update([Detection(label='person', bbox=(300, 20, 360, 470), conf=0.9)], None, (480, 640, 3))[0]
    assert out.zone in {'muy_cerca', 'urgente', 'aviso', 'lejos'}


def test_una_caja_que_llena_el_cuadro_es_muy_cerca():
    out = FusionEngine().update([Detection(label='chair', bbox=(100, 40, 540, 470), conf=0.9)], None, (480, 640, 3))[0]
    assert out.zone == 'muy_cerca' and out.priority in {'P0', 'P1'}


def _det(zone=None, distance=1.4, priority='P1', track=1, label='chair'):
    return Detection(track_id=track, label=label, conf=0.9, bbox=(0, 0, 10, 10), direction='center', distance_m=distance, priority=priority, zone=zone)


def test_en_muy_cerca_no_se_dice_un_numero_que_no_es_fiable():
    text = AlertManager(min_frames=1).evaluate([_det(zone='muy_cerca', priority='P0')], now=0.0)[0].text
    assert text == 'Cuidado: silla al frente, muy cerca'
    assert spoken_for_zone('urgente') == 'a menos de dos metros' and spoken_for_zone('aviso') is None


def test_entrar_a_una_zona_mas_cercana_vuelve_a_avisar_y_quedarse_no_repite():
    # los tiempos van a menos de 3 s entre sí: el gestor olvida un objeto que lleva 3 s sin verse
    m = AlertManager(min_frames=1)
    assert len(m.evaluate([_det(zone='aviso', distance=3.0)], now=0.0)) == 1
    assert m.evaluate([_det(zone='aviso', distance=3.0)], now=2.0) == []
    cerca = m.evaluate([_det(zone='muy_cerca', distance=1.2)], now=4.0)
    assert len(cerca) == 1 and 'ahora muy cerca' in cerca[0].text
    assert m.evaluate([_det(zone='muy_cerca', distance=1.2)], now=6.0) == []
    assert m.evaluate([_det(zone='muy_cerca', distance=1.2)], now=8.0) == []


def test_si_se_aleja_de_zona_se_rearma_y_avisa_al_volver():
    m = AlertManager(min_frames=1)
    assert len(m.evaluate([_det(zone='muy_cerca', distance=1.2)], now=0.0)) == 1
    assert m.evaluate([_det(zone='aviso', distance=3.0)], now=2.0) == []          # se alejó: no habla, pero se re-arma la zona
    assert len(m.evaluate([_det(zone='muy_cerca', distance=1.2)], now=4.0)) == 1  # al volver a acercarse, avisa otra vez


def test_sin_zona_las_frases_siguen_igual_que_antes():
    d = Detection(track_id=1, label='person', conf=0.9, bbox=(0, 0, 10, 10), direction='left', distance_m=1.0, priority='P0')
    assert AlertManager(min_frames=1).evaluate([d], now=0.0)[0].text.startswith('Cuidado: persona a su izquierda, a un metro')
