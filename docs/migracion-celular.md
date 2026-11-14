# Migración: del servidor en el PC al celular

Rama `migracion-celular`. La versión que corre en el PC queda congelada en la rama `version-servidor-pc`.

## Por qué

El documento de arquitectura (entrega 2, `Bili-entrega2-final.tex`) fija una regla: *lo que afecta la seguridad corre en el
dispositivo; lo que aporta contexto, en la nube*. Hoy el celular manda cada cuadro por Wi-Fi al PC, que detecta, decide y devuelve
el texto del aviso. Eso incumple, por construcción, varios escenarios de calidad:

| Escenario | Qué exige | Hoy (servidor en el PC) |
|---|---|---|
| QA-1 Latencia | captura → inicio de la voz < 500 ms en el 95 % de los avisos, medido en el teléfono | sin medir; la red Wi-Fi está en el camino crítico |
| QA-2 Sin red | detección y aviso siguen sin conexión | sin el PC no hay aviso |
| QA-3 Abstención | confianza en banda intermedia → "deténgase", sin nombrar la clase, en el 100 % de los casos | **no existe** |
| QA-5 Privacidad | cero imágenes transmitidas | se transmiten todos los cuadros al PC |
| QA-7 Rendimiento sostenido | gama media; latencia del minuto 30 ≤ 1,2 × la del minuto 1; ≥ 1 h de batería | sin medir; solo hay un iPhone 14 Pro (gama alta) |
| QA-8 Observabilidad | cada aviso registrado con clase, confianza, conducta y latencia | no se registra la conducta ni la latencia de punta a punta |

## Decisiones tomadas

- **Prototipo en el navegador primero** (ONNX Runtime Web, WebGPU con WASM de respaldo). El paper prevé una app Android con
  TensorFlow Lite u ONNX Runtime; el navegador permite medir QA-1 y QA-7 sin construir la app. Límites conocidos en iOS: el bloqueo
  de pantalla en apps instaladas no funcionaba antes de iOS 18.4 y el audio en segundo plano no es fiable; la página debe quedar en
  primer plano con la pantalla encendida. Si eso no alcanza, la app nativa es el paso siguiente.
- **Entrada de 640 × 480 (vertical)**, la resolución de entrenamiento. Bajar a 416 queda solo como respaldo adaptativo en
  teléfonos lentos; su costo está medido (v6b: recall de poste 0,29 → 0,21, de bordillo 0,40 → 0,31 en la prueba general).
- **El modelo se elige con los exámenes**, no por versión.

## Motor de decisión y abstención (QA-3)

`app/core/decision.py` (y su copia `web/bili/decision.js`) convierte cada detección en una conducta. Primero la relevancia y después la
confianza: lo irrelevante (P3) se calla; por encima del umbral ALTO se avisa nombrando la clase; entre el BAJO y el ALTO, si está cerca o
en el camino (P0/P1), se dice "Deténgase: hay algo al frente y no estoy seguro de qué es" con prioridad máxima de voz; por debajo, silencio.
Si luego se confirma, se nombra.

Umbrales medidos con el v7a en el conjunto de prueba (`scripts/movil/umbrales_abstencion.py`): ALTO donde la franja acierta más de la mitad
de las veces, BAJO donde acierta 1 de cada 4 o menos. Fracción de objetos reales que reciben algún aviso: escaleras 0,47 -> 0,58, huecos
0,49 -> 0,62, bordillos 0,36 -> 0,46, postes 0,26 -> 0,36. Son del conjunto de prueba general, no de la vista del celular, y de un solo
modelo: se ajustan con `DECISION_UMBRALES` sin tocar código.

**Cuánto habla caminando** (`scripts/movil/avisos_por_minuto.py`, v7a, un cuadro por segundo, sin el detector de COCO; mide molestia,
no exactitud):

| Regla | Recorrido propio (11,8 min): "deténgase" / con clase | Video de Diego (14,8 min) |
|---|---|---|
| Sin abstención (como antes) | 0 / 5,5 por min | 0 / 3,7 por min |
| Con abstención, tal como está | **3,6** / 3,6 por min | 1,0 / 3,2 por min |
| A: "deténgase" solo si está en el camino | 1,4 / 3,8 | 0,5 / 3,1 |
| B: bordillo sin banda dudosa | 1,4 / 4,0 | 0,5 / 3,3 |
| A + B | 0,7 / 4,0 | 0,2 / 3,2 |

Tal como está pediría detenerse cada ~17 s en el recorrido propio; 28 de esos 43 "deténgase" son bordillos dudosos, casi siempre a un
lado. **Pendiente de decidir** entre A, B o A + B.

## Fases

| Fase | Qué | Cómo se sabe que sirvió | Estado |
|---|---|---|---|
| 1 | Detector en el celular: letterbox, decodificación y NMS en JS (`web/bili/deteccion.js`) | mismas detecciones que Python con el mismo ONNX; mismas métricas con el relleno del celular | **hecho en el PC**: 46 de 46 detecciones idénticas en 60 cuadros reales; examen de bordillos igual con el ONNX (v7a recall 0,26) |
| 1b | Medirlo en teléfonos: iPhone 14 Pro y un Android de gama media | ms por cuadro (mediana y p95) con el modelo elegido | pendiente |
| 2 | Motor de decisión en JS: distancia, zonas de cercanía, prioridades, **abstención (QA-3)** y alertas (`web/bili/{fusion,decision,alertas,cercania,etiquetas}.js`) | los mismos casos dan lo mismo en Python y en JS | **hecho**: 200 escenarios, 9 025 cuadros, 776 alertas (77 de "deténgase"), 0 diferencias; la prueba corre en `pytest` |
| 2b | Seguimiento (IDs entre cuadros) en JS: en el servidor lo da Ultralytics (`model.track`); en el celular no existe | IDs estables en los videos, comparados con Python | pendiente |
| 3 | App: cámara, Worker, voz, pantalla encendida, modelo en caché para uso sin red (QA-2, QA-5) | funciona en modo avión; ningún cuadro sale del teléfono | pendiente |
| 4 | Instrumentación: latencia captura → `onstart` de la voz (QA-1) y registro local de cada aviso (QA-8) | p95 < 500 ms; 100 % de avisos con los cuatro campos | pendiente |
| 5 | Sostenido (QA-7): 30 min caminando, latencia y batería, en gama media | minuto 30 ≤ 1,2 × minuto 1; ≥ 1 h | pendiente |
| 6 | Validación (E4): exámenes, video de otra persona, prueba en campo acompañada | regla de decisión del paper | pendiente |

## Riesgos abiertos

- **Dos modelos.** El de peligros no tiene personas ni vehículos ("vehículo entrando al cruce" es una clase del paper). Con dos
  modelos tipo "s" el iPhone 14 Pro tardó 305 ms por cuadro solo en inferencia; en gama media no cabría en 500 ms. Opciones: un
  solo modelo que incluya persona y vehículos (hay que reentrenar) o un modelo COCO tipo "n" (140 ms los dos en el iPhone).
- **Regla de decisión del paper:** exige exhaustividad ≥ 0,80 en obstáculos críticos. Hoy ningún modelo la cumple en la vista del
  celular (bordillo 0,26 en el examen propio; escaleras alrededor de 0,6). Eso no lo resuelve la migración: es trabajo de datos.
- **Voz sin red:** en Android las voces de `speechSynthesis` dependen del motor del sistema; hay que comprobar que la voz en español
  esté descargada para uso sin conexión.
- **Licencia AGPL-3.0** de los pesos derivados de Ultralytics: los pesos quedan en el teléfono de quien use la app.

## Cómo probar lo hecho

```
node --test tests/js/deteccion.test.mjs
python -I scripts/movil/paridad_deteccion.py --modelo models/onnx/bili-hazards-v6b_640x480.onnx --salida CARPETA --cuadros a.jpg b.jpg ...
node scripts/movil/paridad_deteccion.mjs CARPETA      # sale con código 0 solo si todo coincide
```
