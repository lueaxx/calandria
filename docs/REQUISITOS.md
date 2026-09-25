# Requisitos del brief, contra evidencia

Cada línea apunta al archivo o al comando que la demuestra. Para revisar antes
de enviar, y para responder si un jurado pregunta.

---

## El desafío

| | Dónde |
|---|---|
| Audio en vivo de un escenario | `calandria/audio/` — archivo, stream (RTMP/HLS/SRT), micrófono, y **otra pestaña del navegador** para transmisiones detrás de login |
| Subtítulos en tiempo real, idioma original | `calandria/stt/gemini.py` — **p50 693 ms** sobre una charla real de Nerdearla; atraso plano cruzando 4 rotaciones |
| Traducción en tiempo real al español | `calandria/translate/gemini.py` |
| *(opcional del desafío)* español → inglés | `demo/offline.yaml`, sala `sala-2` — corre en el video |
| Varias sesiones en paralelo (5, 10 o más) | **100 salas medidas** con `scripts/loadtest.py`, 18.6% de un núcleo |
| Licencia aprobada por OSI | Apache 2.0 — `LICENSE`, `NOTICE` |
| Documentación para desplegar | `README.md`, `DEPLOYING.md`, `SCALING.md`, `demo/README.md` |
| Vista de audiencia con elección de sala e idioma | `calandria/web/viewer.html` — <http://localhost:8080> |
| Construido sobre capacidades de audio de Gemini | `gemini-3.5-transcribe-live` vía Live API |

## Opcionales — los cinco

| | Dónde |
|---|---|
| Integración OBS / vMix | `calandria/web/overlay.html` — fondo transparente, configurado por query string |
| Más idiomas de entrada y salida | Portugués incluido; cualquier BCP-47 en `targets` |
| Glosario de términos y nombres propios | `glossary.example.yaml` — alimenta el sesgo del STT **y** las reglas del traductor |
| Exportar la transcripción al final | `calandria/export.py` — SRT, VTT, TXT, JSON, por idioma |
| Panel de monitoreo para producción | `calandria/web/dashboard.html` — estado, latencia p50/p95, errores, rotaciones **y costo en vivo** |

## Requisitos mínimos (MVP)

| | Dónde |
|---|---|
| Audio en vivo de al menos una fuente | Cuatro: `file`, `stream`, micrófono, y pestaña compartida — las dos últimas por `/ws/ingest` |
| Audios de prueba en el repo + forma simple de probarlos | `samples/` + `docker compose --profile demo up demo-offline` |
| Transcripción en tiempo real del idioma original | ✅ |
| Traducción en tiempo real inglés → español | ✅ |
| Mostrar los subtítulos | Cuatro superficies: `/`, `/overlay`, `/dashboard`, `/capture` |
| Al menos dos sesiones simultáneas + cómo escalar | Dos en el video; `SCALING.md` documenta hasta cien |

## Entrega

| | Estado |
|---|---|
| Construido durante el 24 y 25 de septiembre | `git log` — todos los commits caen en esas dos fechas |
| Video demo de 1–2 minutos con audio real de una charla | `video/calandria-demo.mp4` (90 s) + `video/GUION.md` |
| Repositorio público con licencia open source | <https://github.com/lueaxx/calandria> — Apache 2.0 |
| README con cómo levantarlo y qué credenciales necesita | `README.md` |
| Enviado por Devpost antes del 25/9 17:00 UTC *(prorrogado desde las 15:00)* | **pendiente** |

---

## Cómo verificar cualquier número de este repo

```bash
pytest                              # 134 tests
python scripts/measure_accuracy.py  # precisión contra transcripción de referencia
python scripts/loadtest.py --stages 100 --viewers 400
docker compose --profile demo up demo-offline   # sin credenciales
```

## Lo que no está cubierto, dicho de frente

- El respaldo degradado queda unos **12 segundos** atrás del orador, no menos de
  uno. Es la peor latencia del sistema y existe para que un fallo no deje la
  sala sin subtítulos.
- Al cerrar un stream, el modelo a veces recapitula reformulado y se escapa una
  línea repetida. Sobre audio real quedó en **6% de los pares de captions**.
- Las cien salas miden **el proceso**: decodificación, bus y sockets. La
  concurrencia del modelo es cuota de API y ata mucho antes que la máquina.
- Rotar cada 75 segundos en vez de cada 8 minutos multiplica por ocho las
  costuras. Cada una se cose con 3 s de solape y deduplicación, y las cuatro
  medidas no dejaron huecos ni duplicados — pero son cuatro, no cuarenta.
