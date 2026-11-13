import importlib.util
import sys
from pathlib import Path

spec = importlib.util.spec_from_file_location('v5_logica', Path(__file__).parent.parent / 'scripts' / 'stride' / 'v5_logica.py')
v5 = importlib.util.module_from_spec(spec)
sys.modules['v5_logica'] = v5
spec.loader.exec_module(v5)

TEXTO = """Real: 366 367 371
109 111  114

Falso:363 365 368  369
 004 006

Dudoso: 399 403
Mal: 237
"""


def test_parsear_listas_tolera_saltos_de_linea_espacios_y_ceros_a_la_izquierda():
    r = v5.parsear_listas(TEXTO)
    assert r['real'] == [366, 367, 371, 109, 111, 114]
    assert r['falso'] == [363, 365, 368, 369, 4, 6]
    assert r['dudoso'] == [399, 403] and r['mal'] == [237]


def test_comprobar_listas_detecta_faltantes_repetidos_y_fuera_de_rango():
    c = v5.comprobar_listas({'real': [1, 2, 2], 'falso': [4, 9]}, total=5)
    assert c == {'faltan': [3, 5], 'repetidos': [2], 'fuera': [9]}
    assert v5.comprobar_listas({'real': [1, 2], 'falso': [3]}, 3) == {'faltan': [], 'repetidos': [], 'fuera': []}


def test_iou():
    a = (0.9, 0.5, 0.5, 0.2, 0.2)
    assert abs(v5.iou_xywh(a, a) - 1.0) < 1e-9
    assert v5.iou_xywh(a, (0.9, 0.9, 0.9, 0.1, 0.1)) == 0.0


def test_dos_modelos_que_coinciden_son_un_solo_grupo_con_los_dos_modelos():
    g = v5.agrupar([(0.60, 0.50, 0.50, 0.20, 0.20)], [(0.80, 0.51, 0.50, 0.20, 0.20)])
    assert len(g) == 1 and g[0]['modelos'] == ['v2', 'v4'] and g[0]['conf'] == 0.80
    cx = g[0]['caja'][0]
    assert 0.50 < cx < 0.51 and abs(cx - (0.6 * 0.50 + 0.8 * 0.51) / 1.4) < 1e-9   # promedio ponderado por confianza


def test_cajas_que_no_se_tocan_son_grupos_distintos():
    g = v5.agrupar([(0.60, 0.20, 0.20, 0.10, 0.10)], [(0.70, 0.80, 0.80, 0.10, 0.10)])
    assert len(g) == 2 and {tuple(x['modelos']) for x in g} == {('v2',), ('v4',)}


def test_una_vista_real_con_una_sola_caja_es_positivo_sin_duda():
    g = v5.agrupar([], [(0.5, 0.5, 0.5, 0.2, 0.2)])
    tipo, grupos = v5.clasificar_real(g)
    assert tipo == 'positivo' and len(grupos) == 1


def test_una_vista_real_con_cajas_distintas_es_ambigua_y_no_se_adivina():
    g = v5.agrupar([(0.5, 0.2, 0.2, 0.1, 0.1)], [(0.9, 0.8, 0.8, 0.1, 0.1)])
    tipo, _ = v5.clasificar_real(g)
    assert tipo == 'ambigua'   # aunque el v4 tenga más confianza, no se sabe cuál cae sobre la escalera


def test_vista_real_sin_cajas_no_es_positivo():
    assert v5.clasificar_real([])[0] == 'ambigua'


def test_negativo_limpio_solo_si_no_hay_otras_clases():
    assert v5.negativo_limpio({}) is True
    assert v5.negativo_limpio({'pole': 0.20}) is True            # débil: no cuenta
    assert v5.negativo_limpio({'pole': 0.35}) is False           # justo en el umbral
    assert v5.negativo_limpio({'curb': 0.1, 'obstacle': 0.7}) is False


def test_linea_yolo_recorta_a_la_imagen():
    assert v5.linea_yolo(3, (0.5, 0.5, 0.2, 1.3)) == '3 0.500000 0.500000 0.200000 1.000000'
    assert v5.linea_yolo(3, (-0.1, 0.5, 0.2, 0.2)).startswith('3 0.000000')
