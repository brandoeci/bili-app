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

## Fases

| Fase | Qué | Cómo se sabe que sirvió | Estado |
|---|---|---|---|
| 1 | Detector en el celular: letterbox, decodificación y NMS en JS (`web/bili/deteccion.js`) | mismas detecciones que Python con el mismo ONNX; mismas métricas con el relleno del celular | **hecho en el PC**: 46 de 46 detecciones idénticas en 60 cuadros reales; examen de bordillos igual con el ONNX (v7a recall 0,26) |
| 1b | Medirlo en teléfonos: iPhone 14 Pro y un Android de gama media | ms por cuadro (mediana y p95) con el modelo elegido | pendiente |
| 2 | Motor de decisión en JS: seguimiento, distancia, zonas de cercanía, prioridades y **abstención (QA-3)** | los mismos casos de prueba dan lo mismo en Python y en JS | pendiente |
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
