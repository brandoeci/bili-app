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
    # El resto de las 80 clases de COCO: sin traducción se decían en inglés ("Keyboard al frente").
    'airplane': 'avión', 'train': 'tren', 'boat': 'bote', 'bird': 'pájaro', 'sheep': 'oveja', 'cow': 'vaca',
    'elephant': 'elefante', 'bear': 'oso', 'zebra': 'cebra', 'giraffe': 'jirafa', 'handbag': 'bolso', 'tie': 'corbata',
    'frisbee': 'frisbi', 'skis': 'esquís', 'snowboard': 'tabla de nieve', 'sports ball': 'balón', 'kite': 'cometa',
    'baseball bat': 'bate', 'baseball glove': 'guante de béisbol', 'surfboard': 'tabla de surf', 'tennis racket': 'raqueta',
    'wine glass': 'copa', 'cup': 'taza', 'fork': 'tenedor', 'knife': 'cuchillo', 'spoon': 'cuchara', 'bowl': 'tazón',
    'banana': 'banano', 'apple': 'manzana', 'sandwich': 'sándwich', 'orange': 'naranja', 'broccoli': 'brócoli',
    'carrot': 'zanahoria', 'hot dog': 'perro caliente', 'pizza': 'pizza', 'donut': 'dona', 'cake': 'torta', 'mouse': 'mouse',
    'remote': 'control remoto', 'keyboard': 'teclado', 'microwave': 'microondas', 'oven': 'horno', 'toaster': 'tostadora',
    'book': 'libro', 'clock': 'reloj', 'vase': 'florero', 'scissors': 'tijeras', 'teddy bear': 'peluche',
    'hair drier': 'secador', 'toothbrush': 'cepillo de dientes',
}

# Altura real aproximada (m) para estimar distancia monocular desde el bbox.
REAL_HEIGHT_M: dict[str, float] = {
    'person': 1.7, 'car': 1.5, 'truck': 3.0, 'bus': 3.0, 'motorcycle': 1.2,
    'bicycle': 1.0, 'chair': 0.9, 'bench': 0.8, 'couch': 0.9, 'bed': 0.6,
    'dining table': 0.75, 'potted plant': 0.6, 'dog': 0.5, 'cat': 0.3,
    'horse': 1.6, 'traffic light': 0.9, 'stop sign': 0.75, 'fire hydrant': 0.7,
    'suitcase': 0.6, 'backpack': 0.45, 'door': 2.0, 'tv': 0.5,
    'refrigerator': 1.7, 'umbrella': 0.9, 'skateboard': 0.12,
    # Objetos pequeños: sin altura propia se medían como de 0,7 m y salían mucho más lejos de lo real.
    # Dependen de cómo estén puestos (abierto/cerrado, de pie/acostado): son estimaciones gruesas.
    'laptop': 0.28, 'cell phone': 0.15, 'bottle': 0.25, 'parking meter': 1.3, 'toilet': 0.7, 'sink': 0.3,
    # Medido 15/11/2026: un mouse junto al computador salía "a dos metros" con los 0,7 m por defecto.
    'mouse': 0.05, 'keyboard': 0.12, 'remote': 0.15, 'cup': 0.1, 'wine glass': 0.2, 'bowl': 0.08, 'book': 0.22,
    'clock': 0.3, 'vase': 0.3, 'scissors': 0.18, 'teddy bear': 0.35, 'handbag': 0.3, 'sports ball': 0.22,
    'microwave': 0.3, 'toaster': 0.2, 'oven': 0.9, 'bird': 0.2, 'sheep': 0.9, 'cow': 1.4, 'train': 3.5,
}

VEHICLES = {'car', 'truck', 'bus', 'motorcycle', 'bicycle'}
MOVING = VEHICLES | {'person', 'dog', 'cat', 'horse', 'skateboard'}
HAZARDS = {'obstacle', 'drop', 'stairs', 'stairs_up', 'stairs_down', 'step_up', 'wall', 'pothole', 'curb'}
# Cosas que apoyan en el suelo y no tienen una altura fija (un hueco es plano, un poste mide de 4 a 8 m y casi
# siempre sale cortado por arriba): se miden por dónde tocan el suelo en la imagen, no por su altura.
GROUND = {'pothole', 'manhole', 'curb', 'pole', 'obstacle', 'drop', 'wall', 'stairs', 'stairs_up', 'stairs_down', 'step_up'}


def label_es(label: str) -> str:
    key = label.lower()
    return LABELS_ES.get(key) or LABELS_ES.get(key.replace('_', ' '), key.replace('_', ' '))


def gender_article(label: str) -> str:
    """Artículo indefinido para frases naturales ('una persona', 'un carro')."""
    feminine = {'persona', 'silla', 'banca', 'cama', 'mesa', 'matera', 'señal de pare',
                'mochila', 'maleta', 'botella', 'puerta', 'nevera', 'patineta', 'bicicleta',
                'motocicleta', 'camioneta', 'escaleras', 'pared', 'escaleras que suben', 'escaleras que bajan',
                'tapa de alcantarilla', 'oveja', 'vaca', 'cebra', 'jirafa', 'corbata', 'tabla de nieve', 'cometa',
                'tabla de surf', 'raqueta', 'copa', 'taza', 'cuchara', 'manzana', 'naranja', 'zanahoria', 'pizza', 'dona',
                'torta', 'tostadora', 'tijeras'}
    es = label_es(label)
    return 'una' if es in feminine else 'un'

# Ancho real aproximado (m) de la silueta; sirve cuando el bbox está recortado
# por el borde y la altura deja de ser fiable (objeto muy cerca).
REAL_WIDTH_M: dict[str, float] = {
    'person': 0.5, 'car': 1.8, 'truck': 2.4, 'bus': 2.5, 'motorcycle': 0.8,
    'bicycle': 0.6, 'chair': 0.5, 'bench': 1.5, 'couch': 1.8, 'dog': 0.35,
}
