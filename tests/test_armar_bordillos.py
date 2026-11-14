import importlib.util
import sys
from pathlib import Path

RAIZ = Path(__file__).parent.parent
sys.path.insert(0, str(RAIZ / 'scripts' / 'stride'))
sys.path.insert(0, str(RAIZ / 'scripts' / 'dataset'))
spec = importlib.util.spec_from_file_location('armar_bordillos', RAIZ / 'scripts' / 'dataset' / 'armar_bordillos.py')
ab = importlib.util.module_from_spec(spec)
sys.modules['armar_bordillos'] = ab
spec.loader.exec_module(ab)


def test_convierte_a_pixeles_y_recorta_a_la_imagen():
    c = ab.cajas_px(['0 0.5 0.5 0.2 0.1', '0 0.99 0.5 0.1 0.1'], 1000, 2000)
    assert c[0] == [400.0, 900.0, 600.0, 1100.0]
    assert c[1][2] == 1000.0            # la caja que se salía queda recortada


def test_descarta_los_clics_sin_arrastrar_y_las_lineas_rotas():
    c = ab.cajas_px(['0 0.2 0.4 0.001648 0.000000', '0 0.877 0.889 0.000000 0.000660', '0 0.5', '0 0.5 0.5 0.3 0.1'], 720, 1280)
    assert len(c) == 1


def test_las_lineas_salen_con_la_clase_del_bordillo():
    lineas = ab.lineas_curb([[100.0, 200.0, 300.0, 400.0]], 1000, 2000)
    assert lineas == ['2 0.200000 0.150000 0.200000 0.100000']


def test_ida_y_vuelta_de_una_caja():
    px = ab.cajas_px(ab.lineas_curb([[100.0, 200.0, 300.0, 400.0]], 1000, 2000), 1000, 2000)
    assert all(abs(a - b) < 1e-3 for a, b in zip(px[0], [100.0, 200.0, 300.0, 400.0]))
