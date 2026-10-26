# Bili

Sistema de visión asistiva basado en FastAPI. Expone detección, streaming
MJPEG, eventos por WebSocket, alertas de audio y descripción de escena local o
mediante Gemini.

> **Aviso de seguridad:** este sistema es una ayuda complementaria. No
> reemplaza el bastón, un perro guía ni la orientación y movilidad entrenada.
> Los modelos pueden fallar, especialmente con poca luz, oclusiones, reflejos,
> desniveles y objetos fuera de sus datos de entrenamiento. Debe validarse con
> personas invidentes y especialistas antes de cualquier uso real.

## 1. Explicación general

La aplicación está organizada en tres niveles:

1. **L0, reflejo:** procesa frames, detecta objetos, estima distancia, calcula
   prioridades y genera alertas rápidas. No debe depender de Gemini ni de un
   modelo de lenguaje para advertir un peligro.
2. **L1, escena local:** describe la imagen sin enviarla a Internet. Está
   preparada para integrar un VLM local.
3. **L2, nube:** usa Gemini cuando se configura una clave y se solicita el modo
   `gemini` o `auto`. Es útil para descripciones ricas y lectura de texto, pero
   depende de la red y tiene implicaciones de privacidad.

El flujo principal es:

```text
cámara o imagen
        ↓
captura latest-frame-wins
        ↓
detección + profundidad + fusión
        ↓
alertas, overlay y eventos WebSocket
        ↓
MJPEG, interfaz web y audio
```

`latest-frame-wins` conserva solo el frame más reciente. Si el procesamiento se
retrasa, descarta frames antiguos en vez de acumular latencia.

El servidor debe ejecutarse con **un solo worker** porque la cámara, el
pipeline, los modelos y los WebSockets viven en memoria compartida.

La especificación técnica completa está en
[ARQUITECTURE.md](./ARQUITECTURE.md).

## 2. Requisitos

### Para ejecución local

- Python 3.11 o 3.12.
- macOS, Linux o Windows.
- macOS es el entorno recomendado para acceder a la cámara integrada y al
  comando `say`.
- Opcional: una API key de Gemini.
- Opcional: modelos reales en `models/`.

### Para Docker

- Docker Desktop actualizado, con Docker Compose incluido.
- Opcional: una API key de Gemini.
- Opcional: modelos reales en `models/`.

Comprueba Docker únicamente si utilizarás contenedores:

```bash
docker --version
docker compose version
```

## 3. Guía completa sin Docker

Esta es la forma recomendada en un MacBook, especialmente si se necesita usar
la cámara integrada, el audio `say` y capacidades nativas de Apple.

### 3.1 Instalar Python

En macOS con Homebrew:

```bash
brew install python@3.12
python3.12 --version
```

En Linux instala Python 3.11 o 3.12 mediante el gestor de paquetes de la
distribución. En Windows puedes usar Python desde
<https://www.python.org/downloads/>.

### 3.2 Crear y activar el entorno virtual

```bash
cd /ruta/al/proyecto/VisionEureka
python3.12 -m venv .venv
source .venv/bin/activate
```

En Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

El entorno virtual evita mezclar las dependencias del proyecto con las del
sistema operativo.

### 3.3 Instalar dependencias

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Dependencias principales:

- `fastapi` y `uvicorn`: API HTTP y servidor ASGI.
- `opencv-python-headless` y `numpy`: procesamiento de imágenes.
- `pydantic-settings`: configuración por variables de entorno.
- `google-genai`: integración opcional con Gemini.
- `pytest`: pruebas automatizadas.

En macOS, comprueba el audio:

```bash
command -v say
say -v '?'
```

La configuración recomendada es `AUDIO_VOICE=Mónica`, una voz española
disponible en macOS. Después de modificar `.env`, reinicia el servidor para
que la voz y el resto de opciones se carguen.

La voz utiliza una cola FIFO y un único proceso `say`: si Gemini produce una
descripción extensa mientras otra frase se está reproduciendo, la nueva frase
espera su turno. El sistema no mata ni solapa el audio que ya está hablando.

### 3.4 Crear la configuración local

```bash
cp .env.example .env
```

Edita `.env` según tu entorno:

```ini
HOST=127.0.0.1
PORT=8000
WORKERS=1
CAMERA_INDEX=0
DEPTH_ENABLED=true
GEMINI_API_KEY=
GEMINI_MODEL=gemini-3.6-flash
GEMINI_TIMEOUT_S=20
SCENE_MODE=local
SCENE_VLM_ENABLED=true
SCENE_VLM_MODEL=mlx-community/Qwen2.5-VL-3B-Instruct-4bit
```

Deja `GEMINI_API_KEY` vacío para trabajar sin nube. No compartas ni subas
`.env`. El servidor busca `.env` en la raíz del proyecto, incluso si ejecutas
Uvicorn desde otra carpeta.

Gemini puede tardar varios segundos en responder porque se envía una imagen.
El cliente usa un timeout de 20 segundos y realiza un reintento controlado
cuando la primera solicitud falla. Si ambas solicitudes fallan, el sistema
mantiene la descripción local y muestra el motivo en `/health`.

Después de cambiar `.env`, reinicia Uvicorn: la configuración se carga al
iniciar el proceso, no en cada petición.

### 3.5 Preparar los modelos

```bash
mkdir -p models
```

Los nombres previstos por la arquitectura son:

```text
models/yolo11n.mlpackage
models/depth_anything_v2_small.mlpackage
```

El detector por defecto es `models/yolo26s.pt` (YOLO26 small). Se eligió tras comparar
8 modelos en COCO val2017 y sobre los videos de prueba; ver [docs/evaluacion-modelos.md](docs/evaluacion-modelos.md).
`models/yolo11n.pt` queda como alternativa más ligera. El modelo activo se configura con
`DETECTOR_MODEL`; por defecto es `models/yolo26s.pt`.

Para descargar ambos pesos:

```bash
python scripts/export_models.py
```

El script no exporta automáticamente a CoreML: esa conversión requiere
`coremltools`, macOS y los pesos descargados. El MVP puede arrancar sin el
modelo, pero devolverá `detector_error` en `/health` y no hará detecciones
reales.

El VLM local se carga en un proceso separado. En un Mac Apple Silicon,
instálalo con:

```bash
python -m pip install mlx-vlm
```

La primera carga descarga el modelo desde Hugging Face y puede tardar varios
minutos. Su estado aparece en `models_loaded.vlm_local` y
`models_loaded.vlm_local_error` de `/health`. Mientras descarga o carga los
pesos, `models_loaded.vlm_local_loading` será `true`; no es un error. Cuando
termine, `models_loaded.vlm_local` debe ser `true`.

Para que el monitor periódico use exclusivamente el VLM local:

```ini
SCENE_MODE=local
```

Con `SCENE_MODE=auto`, el sistema intenta el VLM local y, si Gemini está
configurado, usa después Gemini como descripción principal. Si Gemini no está
disponible, conserva la respuesta del VLM local.

### 3.6 Iniciar el servidor

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
```

También puedes iniciar con:

```bash
python -m app.main
```

Mantén la terminal abierta. Detén el servidor con `Ctrl+C`.

### 3.7 Verificar la aplicación

Abre <http://127.0.0.1:8000/> en el navegador y consulta:

```bash
curl http://127.0.0.1:8000/health
```

Una respuesta saludable contiene `status: "ok"`. `camera_open` indica si
OpenCV pudo abrir la cámara; que sea `false` no impide probar
`POST /v1/detect` enviando una imagen.

En macOS concede permiso de cámara a Terminal, iTerm o al IDE desde:
`Ajustes del Sistema > Privacidad y seguridad > Cámara`.

### 3.8 Ejecutar pruebas

Con el entorno virtual activo:

```bash
python -m compileall -q app scripts
pytest -q
```

### 3.9 Probar con videos y generar informes

Los videos de prueba van en `videostest/` (cualquier `.mp4`). Con el entorno virtual activo:

```bash
python scripts/benchmark.py --report
```

Procesa todos los `.mp4` de `videostest/` y escribe en `videostest/informes/`:

| Archivo | Contenido |
|---|---|
| `resumen.md` | Tabla comparativa de todos los videos, latencias totales, tracking y peligros |
| `<video>.md` | Informe por video: resolución, FPS efectivo, p50/p95 de YOLO, profundidad y navegación, estabilidad del tracking, objetos y peligros detectados |
| `<video>.jpg` | Frame con más objetos, con las detecciones dibujadas |

Opciones útiles:

```bash
python scripts/benchmark.py --report                       # videostest/*.mp4 -> videostest/informes/
python scripts/benchmark.py --report /ruta/salida          # otra carpeta de salida
python scripts/benchmark.py videostest/a.mp4 --report      # solo ciertos videos
python scripts/benchmark.py --report --max-frames 600      # más frames por video (por defecto 300)
python scripts/benchmark.py --report --annotations distancias.csv   # añade error de distancia (CSV video,t,label,meters)
```

Notas:

- Sin `--report` el script solo imprime las estadísticas en consola.
- Los FPS incluyen decodificar el video; con videos 4K salen menores que en cámara en vivo.
- Los primeros 5 frames de cada video (`--warmup`) se excluyen de las latencias.
- Cada informe se sobrescribe en cada ejecución. La configuración usada (modelos, `depth_input_px`,
  `depth_every_n_frames`) queda registrada en `resumen.md`.

Para salir del entorno virtual:

```bash
deactivate
```

## 4. Operación local y API

Con el servidor funcionando, estos son los comandos principales:

```bash
# Estado
curl http://127.0.0.1:8000/health

# Métricas de latencia y FPS
curl http://127.0.0.1:8000/metrics

# Descripción local, sin audio
curl -X POST http://127.0.0.1:8000/v1/describe \
  -H 'Content-Type: application/json' \
  -d '{"mode":"local","task":"scene","speak":false}'

# Descripción automática; usa Gemini si está configurado
curl -X POST http://127.0.0.1:8000/v1/describe \
  -H 'Content-Type: application/json' \
  -d '{"mode":"auto","task":"scene","speak":false}'

# Gemini explícitamente
curl -X POST http://127.0.0.1:8000/v1/describe \
  -H 'Content-Type: application/json' \
  -d '{"mode":"gemini","task":"scene","speak":false}'

# Detección sobre una imagen
curl -X POST http://127.0.0.1:8000/v1/detect \
  -F 'file=@./ruta/imagen.jpg'

# Prueba de voz en macOS
curl -X POST \
  'http://127.0.0.1:8000/v1/speak?text=Sistema%20listo&priority=P3'
```

Para confirmar que Gemini está configurado:

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/v1/config
```

Debes ver `models_loaded.gemini: true`, `gemini_configured: true` y el modelo
configurado. `mode: "local"` no llama a Gemini; usa la descripción local.
`mode: "gemini"` fuerza la consulta y `mode: "auto"` intenta Gemini y vuelve
al resultado local si hay timeout o error.

La interfaz web muestra el stream con overlay. Los canales adicionales son:

- `/stream.mjpg`: stream de imágenes JPEG.
- `/ws/events`: eventos JSON de frames y alertas.
- `/ws/frames`: entrada para frames enviados desde un navegador, móvil o cámara
  externa.

Al pulsar **Gemini** o **Describir escena**, se envía el frame actual completo,
no solamente las cajas detectadas por YOLO. Gemini puede describir elementos
que no pertenezcan a las clases COCO del detector, como relojes, pizarras,
carteles, muebles o detalles del entorno. El overlay y el panel inferior
muestran todas las detecciones que YOLO devuelve en el último frame.

Al abrir `/stream.mjpg` se inicia automáticamente un monitor de escena. Este
monitor hace una consulta inmediata al modelo configurado y repite la consulta
según `scene_auto_interval_s` mientras el proceso esté activo. La descripción se muestra en la
interfaz, se publica por `/ws/events` y se lee mediante la voz configurada.
Abrir varias pestañas no crea monitores duplicados.

El monitor solo lee y publica una descripción si es diferente de la última
descripción leída. Las respuestas que solo cambian en espacios, saltos de línea
o mayúsculas se consideran iguales. La primera descripción siempre se lee.
La descripción heurística está desactivada mientras el modelo responde; solo se
usa como respaldo si el modelo no responde o devuelve texto vacío. Para evitar
repeticiones, la heurística puede producir como máximo una respuesta cada 60
segundos (`scene_heuristic_interval_s`). Si no se detectan obstáculos, responde
explícitamente que puede seguir adelante. Las alertas o salidas heurísticas
tienen además un límite de una locución cada 5 segundos.
Una escena sin cambios o una respuesta idéntica no vuelve a hablar.

Configuración en caliente:

```bash
curl http://127.0.0.1:8000/v1/config

curl -X PUT http://127.0.0.1:8000/v1/config \
  -H 'Content-Type: application/json' \
  -d '{"scene_mode":"local","detector_conf":0.4,"audio_voice":"Soledad"}'
```

Control de sesión:

```bash
curl -X POST http://127.0.0.1:8000/v1/session/start
curl -X POST http://127.0.0.1:8000/v1/session/stop
```

## 5. Inicio con Docker Compose

### 5.1 Preparar el entorno

```bash
cd /ruta/al/proyecto/VisionEureka
cp .env.example .env
mkdir -p models
```

Edita `.env` y agrega `GEMINI_API_KEY` únicamente si utilizarás Gemini. Compose
también puede arrancar sin `.env`, usando valores por defecto.

### 5.2 Construir y arrancar

```bash
docker compose up --build
```

URLs disponibles:

- UI: <http://127.0.0.1:8000/>
- Health: <http://127.0.0.1:8000/health>
- Métricas: <http://127.0.0.1:8000/metrics>
- Stream: <http://127.0.0.1:8000/stream.mjpg>

En segundo plano:

```bash
docker compose up --build -d
docker compose logs -f vision-asistiva
```

Detener:

```bash
docker compose down
```

Reconstrucción limpia:

```bash
docker compose build --no-cache
docker compose up
```

## 6. Diferencias entre Docker y ejecución local

La ejecución local es preferible en macOS porque puede acceder a la cámara y
al audio del sistema. Docker aporta aislamiento y reproducibilidad, pero tiene
limitaciones:

- Docker Desktop en macOS no expone automáticamente la cámara integrada al
  contenedor.
- La imagen Linux no tiene la voz `say` de macOS.
- CoreML, MLX y Neural Engine de Apple no están disponibles de forma nativa
  dentro de una imagen Linux estándar.
- En Docker se recomienda probar con `POST /v1/detect` o enviando frames por
  `/ws/frames`.
- En Linux se puede adaptar el Compose para pasar explícitamente
  `/dev/video0`.

El archivo [compose.yaml](./compose.yaml) mantiene un solo worker y monta
`models/` como solo lectura.

## 7. Variables principales

Las variables corresponden a la configuración de
[app/config.py](./app/config.py):

| Variable | Uso | Valor por defecto |
|---|---|---|
| `HOST` | Interfaz de escucha | `127.0.0.1` |
| `PORT` | Puerto HTTP | `8000` |
| `WORKERS` | Workers Uvicorn | `1` |
| `CAMERA_INDEX` | Índice de cámara | `0` |
| `PROCESS_SIZE` | Tamaño de inferencia | `640` |
| `DETECTOR_MODEL` | Peso YOLO activo | `models/yolo26s.pt` |
| `DEPTH_ENABLED` | Habilitar profundidad | `true` |
| `GEMINI_API_KEY` | Clave opcional de Gemini | vacío |
| `GEMINI_MODEL` | Modelo Gemini | `gemini-3.6-flash` |
| `GEMINI_TIMEOUT_S` | Timeout Gemini | `20` |
| `SCENE_MODE` | Estrategia del monitor | `auto` |
| `SCENE_VLM_ENABLED` | Activar VLM local | `true` |
| `SCENE_VLM_MODEL` | Modelo MLX-VLM | `mlx-community/Qwen2.5-VL-3B-Instruct-4bit` |
| `AUDIO_VOICE` | Voz española de macOS | `Mónica` |
| `AUDIO_RATE_WPM` | Velocidad de voz | `190` |

## 8. Solución de problemas

### `ModuleNotFoundError`

Activa el entorno e instala dependencias:

```bash
source .venv/bin/activate
python -m pip install -r requirements.txt
```

### La cámara no abre

Comprueba permisos de cámara, que ninguna otra aplicación la esté usando y el
valor de `CAMERA_INDEX`. En macOS concede permiso a Terminal, iTerm o al IDE.

### El puerto 8000 está ocupado

Usa otro puerto:

```bash
PORT=8001 uvicorn app.main:app --host 127.0.0.1 --port 8001 --workers 1
```

### Gemini no responde

Comprueba:

```bash
grep '^GEMINI_' .env
curl http://127.0.0.1:8000/health
```

No compartas el valor de `GEMINI_API_KEY`. Si `models_loaded.gemini` es
`false`, la clave no se cargó: revisa que `.env` esté en la raíz y reinicia el
servidor. Si es `true` pero la consulta falla, revisa `GEMINI_MODEL`, la
conectividad y los permisos de la clave. La respuesta de `/v1/describe`
incluye el motivo del fallback local cuando Gemini devuelve un error.
Para desarrollo sin Internet usa `mode: "local"`.

### La interfaz no muestra la cámara

Comprueba primero:

```bash
curl http://127.0.0.1:8000/health
curl --max-time 3 http://127.0.0.1:8000/stream.mjpg -o /tmp/vision-stream.mjpg
```

En `health` deben aparecer `camera.open: true` y `camera.has_frame: true`.
También concede permiso de cámara a la terminal o IDE en los ajustes de
privacidad de macOS. Abre la interfaz en
`http://127.0.0.1:8000/`, no mediante `file://`.

Si la cámara está abierta pero el navegador no muestra el stream, prueba
`/stream.mjpg` directamente en una pestaña y verifica que ningún otro programa
esté usando la cámara. El stream es MJPEG y debe mostrarse mediante una etiqueta
`<img>`.

### La descripción no dice nada útil

`/v1/describe` toma el frame actual de la cámara y las detecciones fusionadas.
Si no hay cámara disponible, procesa un frame de sustitución y solo puede
describir las detecciones disponibles. Usa `mode: "local"` para validar la
respuesta sin red y `mode: "gemini"` para validar la consulta multimodal con la
imagen real.

### No se escucha la voz

En macOS prueba primero:

```bash
say "Sistema listo"
```

Si el comando funciona fuera de la aplicación, revisa `AUDIO_VOICE` y que otra
alerta no esté interrumpiendo la reproducción.

## 9. Estado y límites actuales

El repositorio contiene el pipeline base y sustituciones para poder validar la
integración, pero todavía deben completarse para producción:

- Integrar YOLO/CoreML y Depth Anything reales.
- Conectar el proceso separado al VLM local MLX y sus pesos.
- Validar el cliente Gemini con imágenes reales y fallback local.
- Medir FPS, latencia, recall, falsos positivos y falsos negativos.
- Validar frases, carga cognitiva y volumen con usuarios y especialistas.

Los modelos reales no se incluyen en el repositorio. Antes de cualquier uso
real deben ejecutarse pruebas controladas de seguridad, especialmente con
obstáculos, huecos, escaleras, vehículos, poca luz y reflejos.

## Cambios de comportamiento (anti-repetición y VLM)

- **Alertas (`app/core/alerts.py`):** un objeto se anuncia una vez y solo se
  repite si se acerca a una banda más cercana, cambia de lado, su tiempo de
  impacto baja de 3 s o, si es crítico (P0), como recordatorio cada
  `ALERTS_REMINDER_S` segundos. Frases en español con distancia hablada
  ("Cuidado: persona a su izquierda, a dos metros, se acerca").
- **Voz (`app/audio/tts.py`):** cola con prioridad. P0 interrumpe y descarta lo
  pendiente de menor prioridad, la descripción de escena reemplaza a otra
  pendiente, y se omiten mensajes repetidos o caducados.
- **Descripción de escena (`app/scene/`):** cadena de proveedores
  (VLM local → Gemini → resumen del detector) con circuit breaker. Solo se
  consulta al modelo cuando la escena cambia (`NarrationGate`), se le pasa la
  descripción anterior para que diga únicamente lo nuevo (`SIN_CAMBIOS`) y no se
  habla un texto casi idéntico a uno reciente. La heurística ya no afirma
  "camino libre": solo reporta lo medido y se marca `degraded`.
- **Latencia:** imagen reducida a `SCENE_VLM_MAX_SIDE_PX`, salida limitada a
  ~90 tokens, temperatura 0, calentamiento del VLM al arrancar, fallo rápido si
  el VLM está cargando u ocupado.
- **Profundidad:** `DepthModel` ya no inventa un mapa sintético; hasta integrar
  un modelo real la distancia sale de la altura del bbox por clase.

## Profundidad, paredes y cambios en el camino

`DepthModel` carga Depth Anything V2 **métrico** (metros; ~40 ms en MPS) en un
hilo al arrancar; `DEPTH_MODEL=depth-anything/Depth-Anything-V2-Metric-Outdoor-Small-hf`
para exteriores. `PathAnalyzer` (`app/core/navigation.py`) ajusta el plano del
suelo y detecta paredes, obstáculos sin clase (incluso muy cerca, donde YOLO
falla) y cambios del suelo (escalón, escaleras, desnivel), e indica por dónde se
puede o no pasar ("Cuidado: pared al frente, a un metro. Libre hacia la derecha.").

- `GET /v1/navigation` estado por sector; `GET /v1/depth.jpg` mapa de profundidad
  (rojo = cerca) para depurar.
- `POST /v1/calibrate?distance_m=2` sigue calibrando la geometría por bbox.
- **Experimental:** umbrales (`_RAISED`, `_SUNKEN`, persistencia) validados solo con
  mapas sintéticos. Hay que ajustarlos con grabaciones reales (pasillos, escaleras,
  bordillos) antes de confiar en ellos.

## Usabilidad y operación

- **Estados hablados:** al iniciar dice "Sistema listo" o qué falta (cámara, detector,
  profundidad, descripción). Si la cámara se tapa o hay muy poca luz avisa con prioridad P0.
- **Repetir:** `POST /v1/repeat?n=1` o tecla R en la web; `GET /v1/history` lista los
  últimos 5 mensajes.
- **Modo silencioso:** `AUDIO_VERBOSITY=quiet` (o `PUT /v1/config`) solo habla peligros P0.
  `audio_rate_wpm` también se ajusta en caliente.
- **TTS:** `say` en macOS; `espeak-ng`/`espeak` en Linux si están instalados.
- **Depuración:** `DEBUG_ENDPOINTS=false` desactiva `/v1/depth.jpg`.
- **Benchmark:** `python scripts/benchmark.py clips/*.mp4 --annotations distancias.csv`
  (CSV `video,t,label,meters`) mide p50/p95 por etapa y error de distancia.
  Para pruebas con los videos de `videostest/` y su informe, ver [3.9](#39-probar-con-videos-y-generar-informes).
- **Calidad:** `ruff check app tests scripts` y `pytest`; el CI está en `.github/workflows/ci.yml`.
