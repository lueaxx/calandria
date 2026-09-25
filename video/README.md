# Video del demo

`calandria-demo.mp4` — 90 segundos, 1280×720, sin audio. Se graba encima.

El archivo **no está versionado**: contiene metraje de una charla de Nerdearla.
Las bases autorizan usar esas charlas para el video de la propuesta, pero eso
no alcanza para redistribuirlas dentro de un repositorio Apache-2.0.

[`GUION.md`](GUION.md) tiene la narración cronometrada a estos tiempos:

| | |
|---|---|
| 0:00 – 0:33 | Vista de audiencia, inglés y español emparejados |
| 0:33 – 1:00 | Panel de operación y proyección de costo |
| 1:00 – 1:22 | Overlay de OBS sobre el video real de la charla |
| 1:22 – 1:30 | Página para enviar el audio de un escenario |

## Volver a grabarlo

```bash
./scripts/fetch-talk.sh "https://www.youtube.com/watch?v=GkVjMxYi5gA" \
    samples/talk-real-en.wav 420 360

python -m calandria -c .scratch/video/demo.yaml    # dejarlo calentar ~80 s
python .scratch/record.py                          # graba las cuatro tomas
```

Las tomas salen como webm por separado y se unen con ffmpeg. Todo lo que se ve
es salida real: una charla de Nerdearla entrando a una instancia corriendo, en
las mismas páginas que abriría una audiencia, un equipo de producción y un
operador de OBS.
