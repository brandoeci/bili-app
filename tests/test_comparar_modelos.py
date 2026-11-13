import importlib.util
import sys
from pathlib import Path

spec = importlib.util.spec_from_file_location('comparar_modelos', Path(__file__).parent.parent / 'scripts' / 'dataset' / 'comparar_modelos.py')
cm = importlib.util.module_from_spec(spec)
sys.modules['comparar_modelos'] = cm
spec.loader.exec_module(cm)

CLASES = ['pothole', 'manhole', 'curb', 'stairs', 'pole', 'obstacle']


def test_las_tres_escaleras_del_v2_cuentan_como_una():
    for n in ('stairs', 'stairs_up', 'stairs_down'):
        assert cm.a_clase_del_examen(n, CLASES) == 'stairs'
    assert cm.a_clase_del_examen('pothole', CLASES) == 'pothole'
    assert cm.a_clase_del_examen('person', CLASES) is None            # no es una clase del examen
    assert cm.a_clase_del_examen('stairs_up', ['pothole', 'stairs_up']) == 'stairs_up'   # si el examen sí las separa, se respetan


def test_iou():
    assert cm.iou((0, 0, 1, 1), (0, 0, 1, 1)) == 1.0
    assert cm.iou((0, 0, 1, 1), (2, 2, 3, 3)) == 0.0
    assert abs(cm.iou((0, 0, 2, 1), (1, 0, 3, 1)) - 1 / 3) < 1e-9


def test_emparejar_aciertos_falsas_y_escapadas():
    gt = [(0.1, 0.1, 0.3, 0.3), (0.6, 0.6, 0.9, 0.9)]
    # un acierto, una falsa lejos, y la segunda caja del examen se escapa
    pred = [(0.9, (0.1, 0.1, 0.3, 0.3)), (0.8, (0.4, 0.0, 0.5, 0.1))]
    assert cm.emparejar(gt, pred) == (1, 1, 1)


def test_dos_predicciones_sobre_una_caja_cuentan_una_acierto_y_una_falsa():
    gt = [(0.2, 0.2, 0.6, 0.6)]
    pred = [(0.9, (0.2, 0.2, 0.6, 0.6)), (0.5, (0.21, 0.21, 0.61, 0.61))]
    assert cm.emparejar(gt, pred) == (1, 1, 0)


def test_sin_cajas_ni_predicciones():
    assert cm.emparejar([], []) == (0, 0, 0)
    assert cm.emparejar([], [(0.9, (0, 0, 1, 1))]) == (0, 1, 0)
    assert cm.emparejar([(0, 0, 1, 1)], []) == (0, 0, 1)
