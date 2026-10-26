# Evaluación de modelos (detector y VLM)

Fecha: 2026-10-10 · Equipo: Mac mini/MacBook Apple M4, 16 GB · detector en MPS.

## Detector

Dos mediciones: **precisión** (mAP en COCO val2017, 5000 imágenes, 640 px, MPS) y **comportamiento real**
(`scripts/benchmark.py` sobre los 7 videos de `videostest/`, 300 frames c/u, tracking activado,
profundidad desactivada para aislar al detector).

| Modelo | mAP50-95 | mAP50 | YOLO p50 (ms) | FPS bench | Tracks estables / IDs |
|---|---|---|---|---|---|
| yolo11n (anterior) | 0.381 | 0.534 | 17.0 | 47.4 | 39 / 47 |
| yolo26n | 0.402 | 0.562 | 17.4 | 47.1 | 34 / 41 |
| yolo11s | 0.455 | 0.619 | 25.7 | 34.6 | 56 / 76 |
| yolo12s | 0.474 | 0.643 | — | — | — |
| **yolo26s (elegido)** | **0.480** | **0.651** | 25.3 | 35.2 | 59 / 69 |
| yolo11m | 0.510 | 0.677 | — | — | — |
| rtdetr-l | 0.523 | — | 71.6 | 13.2 | 77 / 93 |
| yolo26m | 0.524 | 0.700 | 34.4 | 26.4 | 79 / 94 |

(— = no se midió en videos; los de mayor mAP ya quedaban descartados por latencia o por superar a yolo26s sin necesidad.)

**Decisión: `yolo26s`.** Frente a yolo11n sube el mAP de 0.381 a 0.480 (+26 % relativo, +9.9 puntos) y detecta más objetos con
tracking estable (59 vs 39 tracks de ≥10 frames), a costa de ~8 ms más por frame. `yolo26m`/`rtdetr-l` ganan algo
más de mAP pero cuestan 34 ms y 72 ms; `rtdetr-l` queda por debajo de 15 FPS, inviable en tiempo real.
`yolo26n` apenas mejora a yolo11n (+2 puntos).

Costo en el sistema completo (detector + profundidad cada 3 frames, 7 videos): **27.9 → 23.4 FPS** efectivos
(YOLO p50 12 → 18 ms en esa corrida). Sigue cerca del tiempo real, pero es un costo real.

Limitaciones: COCO no es una escena de peatón ciego y los videos no tienen etiquetas, así que la mejora de precisión sobre
los videos no se pudo cuantificar con mAP; se infiere de COCO y del número de tracks estables.

## VLM

Se probaron con el prompt real de la app, 512 px, sobre 14 frames de los videos (2 por video) con las detecciones de
los sensores como contexto, y se repitió quitando los ejemplos del prompt. Los dos frames de `16311811` son una
escalera hacia abajo y sirven de prueba de seguridad (también con la pregunta directa "¿hay algún peligro?").
La calidad se juzgó viendo las imágenes y contando defectos objetivos.

| Modelo | Latencia p50 | Memoria pico | Copia ejemplos | Falsa seguridad ante la escalera (pregunta directa) | Observación |
|---|---|---|---|---|---|
| **Qwen2.5-VL-3B-4bit (actual)** | 2.3 s | 3.8 GB | 3/14 | 1/2 | Respuestas casi idénticas entre frames distintos |
| Qwen3-VL-4B-4bit | 2.7 s | 3.8 GB | 0/14 | 2/2 | Dice "camino libre" en 12/14 escenas |
| gemma-4-e2b-4bit | 1.2 s | 4.3 GB | 0/14 | 2/2 | Responde "No hay nada bloqueando su camino" ante la escalera; repite "a unos dos metros" |
| gemma-4-e4b-4bit | 2.3 s | 5.8 GB | 0/14 | 0/2 | Único que nunca da falsa seguridad; casi no da distancias (3/14) e inventó un "pasillo largo" |

Sin ejemplos en el prompt: el modelo actual se vuelve verboso (34 palabras en vez de 14, 4.9 s) y llegó a mezclar chino;
gemma-4-e2b mantiene 1.2 s pero sigue sin detectar el riesgo en la pregunta directa. Ninguna variante mejora.

**Decisión: se mantiene Qwen2.5-VL-3B** y se descartaron los candidatos (modelos borrados del disco). Ninguno mejora de
forma sustancial y clara: Qwen3-VL-4B y gemma-4-e2b son peores en seguridad; gemma-4-e4b es mejor en la escalera pero
cuesta +2 GB de RAM y casi no da distancias. La muestra (14 frames, 2 de escalera) es pequeña. Hallazgo para trabajo
futuro: el modelo actual copia los ejemplos del prompt (`prompts.py`), pero quitarlos empeora el formato.

No evaluados: Qwen3-VL-2B (descarga fallida), Qwen3.5 y Qwen2.5-VL-7B (no cabían bien junto a YOLO + profundidad en 16 GB
o no se completó la prueba).

## Gemini (nube) con clave real

Probado con `gemini-3.6-flash`, el prompt real de la app y los mismos frames (640 px).

- **Calidad:** claramente mejor que cualquier VLM local. En los dos frames de escalera detectó "escaleras hacia abajo,
  a un paso" y la baranda a la izquierda (verificado en la imagen), y a la pregunta directa respondió "Cuidado, justo al
  frente... escaleras hacia abajo" (0/2 falsa seguridad, frente a 1/2 del VLM local actual). No copia los ejemplos del prompt.
- **Latencia:** 4.4 a 7.2 s típica (2x el VLM local), con picos de 41 s por reintentos de cuota.
- **Fiabilidad con la clave gratuita:** de 16 llamadas espaciadas, 5 fallaron (3x 503, 1x 500, 1x 429), y el plan gratuito
  permite solo **20 peticiones por día y por modelo** (`GenerateRequestsPerDayPerProject-FreeTier`). Inviable para uso continuo.
- **Enrutamiento del programa:** con `SCENE_MODE=local` (valor actual en `.env`) Gemini nunca se usa. En `auto` el
  local va primero y Gemini solo entra si falla, salvo `read_text`, que va primero a Gemini. En `gemini` no hay respaldo
  local: si Gemini falla responde la heurística, que ante la escalera dijo "No detecto objetos cercanos, pero avance con precaución".

## Cómo reproducir

```bash
DETECTOR_MODEL=models/yolo11n.pt python scripts/benchmark.py --report /ruta/informes
```

COCO: `YOLO(modelo).val(data=..., imgsz=640, device='mps')`.
