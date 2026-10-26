from __future__ import annotations

# Fuente única de etiquetas en español (antes duplicadas en alerts, scheduler y web).
LABELS_ES: dict[str, str] = {
    'person': 'persona',
    'car': 'carro',
    'truck': 'camión',
    'bus': 'bus',
    'motorcycle': 'motocicleta',
    'bicycle': 'bicicleta',
    'chair': 'silla',
    'bench': 'banca',
    'couch': 'sofá',
    'bed': 'cama',
    'dining table': 'mesa',
    'potted plant': 'matera',
    'dog': 'perro',
    'cat': 'gato',
    'horse': 'caballo',
    'traffic light': 'semáforo',
    'stop sign': 'señal de pare',
    'fire hydrant': 'hidrante',
    'parking meter': 'parquímetro',
    'backpack': 'mochila',
    'suitcase': 'maleta',
    'umbrella': 'paraguas',
    'bottle': 'botella',
    'cell phone': 'teléfono',
    'laptop': 'computador',
    'tv': 'televisor',
    'toilet': 'inodoro',
    'sink': 'lavamanos',
    'refrigerator': 'nevera',
    'skateboard': 'patineta',
    'obstacle': 'obstáculo',
    'drop': 'desnivel hacia abajo',
    'stairs': 'escaleras',
    'stairs_up': 'escaleras que suben',
    'stairs_down': 'escaleras que bajan',
    'step_up': 'escalón hacia arriba',
    'wall': 'pared',
    'door': 'puerta',
    'pothole': 'hueco',
    'manhole': 'tapa de alcantarilla',
    'curb': 'bordillo',
    'pole': 'poste',
}

# Altura real aproximada (m) para estimar distancia monocular desde el bbox.
REAL_HEIGHT_M: dict[str, float] = {
    'person': 1.7, 'car': 1.5, 'truck': 3.0, 'bus': 3.0, 'motorcycle': 1.2,
    'bicycle': 1.0, 'chair': 0.9, 'bench': 0.8, 'couch': 0.9, 'bed': 0.6,
    'dining table': 0.75, 'potted plant': 0.6, 'dog': 0.5, 'cat': 0.3,
    'horse': 1.6, 'traffic light': 0.9, 'stop sign': 0.75, 'fire hydrant': 0.7,
    'suitcase': 0.6, 'backpack': 0.45, 'door': 2.0, 'stairs': 1.0, 'tv': 0.5,
    'refrigerator': 1.7, 'umbrella': 0.9, 'skateboard': 0.12,
}

VEHICLES = {'car', 'truck', 'bus', 'motorcycle', 'bicycle'}
MOVING = VEHICLES | {'person', 'dog', 'cat', 'horse', 'skateboard'}
HAZARDS = {'obstacle', 'drop', 'stairs', 'stairs_up', 'stairs_down', 'step_up', 'wall', 'pothole', 'curb'}
# Cosas que están sobre el suelo: su altura en la imagen no sirve para medir distancia (un hueco es plano).
GROUND = {'pothole', 'manhole', 'curb'}


def label_es(label: str) -> str:
    key = label.lower()
    return LABELS_ES.get(key) or LABELS_ES.get(key.replace('_', ' '), key.replace('_', ' '))


def gender_article(label: str) -> str:
    """Artículo indefinido para frases naturales ('una persona', 'un carro')."""
    feminine = {'persona', 'silla', 'banca', 'cama', 'mesa', 'matera', 'señal de pare',
                'mochila', 'maleta', 'botella', 'puerta', 'nevera', 'patineta', 'bicicleta',
                'motocicleta', 'camioneta', 'escaleras', 'pared', 'escaleras que suben', 'escaleras que bajan',
                'tapa de alcantarilla'}
    es = label_es(label)
    return 'una' if es in feminine else 'un'

# Ancho real aproximado (m) de la silueta; sirve cuando el bbox está recortado
# por el borde y la altura deja de ser fiable (objeto muy cerca).
REAL_WIDTH_M: dict[str, float] = {
    'person': 0.5, 'car': 1.8, 'truck': 2.4, 'bus': 2.5, 'motorcycle': 0.8,
    'bicycle': 0.6, 'chair': 0.5, 'bench': 1.5, 'couch': 1.8, 'dog': 0.35,
}
