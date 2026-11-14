import importlib.util
import sys
from pathlib import Path

spec = importlib.util.spec_from_file_location('v6_logica', Path(__file__).parent.parent / 'scripts' / 'stride' / 'v6_logica.py')
v6 = importlib.util.module_from_spec(spec)
sys.modules['v6_logica'] = v6
spec.loader.exec_module(v6)

POSTE = [100, 50, 120, 250]          # alargado: 20 x 200
OTRO = [300, 60, 322, 260]


def test_unir_veredictos_marca_conflicto_solo_si_los_dos_vieron_la_caja_y_difieren():
    r = v6.unir_veredictos({1: 'R', 2: 'F', 3: 'R'}, {2: 'F', 3: 'D', 4: 'MAL'})
    assert r == {1: 'R', 2: 'F', 3: 'CONFLICTO', 4: 'MAL'}


def test_iou_y_cubierto():
    assert abs(v6.iou_xyxy(POSTE, POSTE) - 1.0) < 1e-9
    assert v6.iou_xyxy(POSTE, OTRO) == 0.0
    assert v6.cubierto([0, 0, 10, 10], [0, 0, 5, 10]) == 0.5


def test_cajas_extra_ignora_las_ya_revisadas_las_bajas_y_las_no_alargadas():
    cand = [POSTE + [0.9], OTRO + [0.30], [500, 100, 600, 150, 0.9], [700, 10, 712, 200, 0.10]]
    # POSTE ya revisada; OTRO nueva con score 0,30; la ancha no es un poste; la última es muy débil
    assert v6.cajas_extra(cand, [POSTE]) == [OTRO]


def test_una_caja_dentro_de_otra_revisada_no_cuenta_como_extra():
    dentro = [102, 60, 118, 240, 0.4]
    assert v6.cajas_extra([dentro], [POSTE]) == []


def test_vista_con_caja_mal_o_conflicto_o_varios_postes_marcados_queda_fuera():
    assert v6.plan_vista([(POSTE, 'R'), (OTRO, 'MAL')], [])['accion'] == 'fuera'
    assert v6.plan_vista([(POSTE, 'CONFLICTO')], [])['accion'] == 'fuera'
    assert v6.plan_vista([(POSTE, 'R')], [], marcada_varios=True)['accion'] == 'fuera'


def test_vista_con_real_es_positiva_y_tapa_los_dudosos_y_extras():
    p = v6.plan_vista([(POSTE, 'R'), (OTRO, 'D')], [[500, 60, 520, 260]])
    assert p['accion'] == 'positivo' and p['positivas'] == [POSTE]
    assert OTRO in p['tapar'] and [500, 60, 520, 260] in p['tapar']


def test_no_se_tapa_lo_que_pisa_un_poste_bueno():
    p = v6.plan_vista([(POSTE, 'R')], [[105, 60, 125, 250]])      # casi encima del poste bueno
    assert p['tapar'] == []


def test_vista_solo_con_falsos_es_negativa_y_sin_nada_revisable_queda_fuera():
    assert v6.plan_vista([(POSTE, 'F')], [])['accion'] == 'negativo'
    assert v6.plan_vista([(POSTE, 'D')], [])['accion'] == 'fuera'
