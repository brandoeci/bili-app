import numpy as np

from app.config import Settings
from app.core.detector import YoloDetector


class _Escalar:
    def __init__(self, v): self.v = v
    def item(self): return self.v
    def tolist(self): return self.v


class _Cajas:
    """Imita las cajas de un resultado de Ultralytics: solo lo que usa YoloDetector.track."""
    def __init__(self, filas):
        self.cls = [_Escalar(c) for c, _, _ in filas]
        self.conf = [_Escalar(s) for _, s, _ in filas]
        self.xyxy = [_Escalar(b) for _, _, b in filas]
        self.id = None
    def __len__(self): return len(self.cls)


class _Resultado:
    names = {0: 'pothole', 1: 'stairs', 2: 'stairs_up', 3: 'pole'}
    def __init__(self, filas): self.boxes = _Cajas(filas)


class _Modelo:
    def __init__(self, filas): self.filas = filas
    def track(self, **kwargs): return [_Resultado(self.filas)]


def _detector(filas, class_conf=None):
    d = YoloDetector(model_path='no-existe.pt', conf=0.35, class_conf=class_conf)
    d.model = _Modelo(filas)   # modelo de mentira: la prueba pasa por el código real de track()
    return d


FRAME = np.zeros((480, 640, 3), np.uint8)
CAJA = [10, 10, 100, 100]
FILAS = [(1, 0.40, CAJA), (1, 0.55, CAJA), (2, 0.49, CAJA), (2, 0.50, CAJA), (0, 0.40, CAJA), (3, 0.36, CAJA)]


def test_sin_umbrales_por_clase_se_conserva_todo_lo_que_pasa_el_umbral_general():
    assert len(_detector(FILAS).track(FRAME)) == 6


def test_el_umbral_de_escaleras_quita_las_alarmas_flojas_y_deja_las_demas_clases_igual():
    out = _detector(FILAS, {'stairs': 0.5, 'stairs_up': 0.5}).track(FRAME)
    dejadas = sorted((d.label, round(d.conf, 2)) for d in out)
    assert dejadas == [('pole', 0.36), ('pothole', 0.4), ('stairs', 0.55), ('stairs_up', 0.5)]   # 0.50 justo sí pasa; 0.49 no


def test_el_umbral_no_distingue_mayusculas_y_no_afecta_clases_no_listadas():
    out = _detector(FILAS, {'STAIRS': 0.9}).track(FRAME)
    assert {d.label for d in out} == {'pole', 'pothole', 'stairs_up'}   # stairs (0.40, 0.55) quedan fuera; stairs_up no estaba listada


def test_un_umbral_por_clase_mas_bajo_que_el_general_no_deja_pasar_lo_que_el_modelo_ya_descarto():
    # El modelo ya filtra por conf=0.35 antes de entregar nada: class_conf solo puede endurecer
    d = _detector([(1, 0.20, CAJA)], {'stairs': 0.1})
    d.model = _Modelo([])   # el modelo real no habría devuelto la caja de 0.20
    assert d.track(FRAME) == []


def test_por_defecto_las_escaleras_tienen_umbral_mas_estricto_que_el_general():
    s = Settings()
    assert s.hazard_class_conf['stairs'] >= 0.5
    assert all(v > s.hazard_conf for v in s.hazard_class_conf.values())
    assert {'stairs', 'stairs_up', 'stairs_down'} <= set(s.hazard_class_conf)
