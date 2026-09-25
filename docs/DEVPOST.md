# Texto para el envío en Devpost

Para copiar y pegar. Cada número que aparece acá está medido y se puede
reproducir con los comandos de [REQUISITOS.md](REQUISITOS.md).

---

## Nombre

**Calandria**

## Frase corta (tagline)

Subtítulos y traducción simultánea para conferencias, en menos de un segundo,
con el audio decodificado una sola vez por escenario.

## Enlaces

- **Repositorio:** https://github.com/lueaxx/calandria
- **Licencia:** Apache 2.0 (aprobada por la OSI)
- **Video:** *(pegar el link de YouTube)*

---

## Qué hace

Toma el audio de un escenario y lo devuelve como subtítulos en el idioma
original y traducidos a cuantos idiomas quiera el evento, en vivo. La audiencia
entra desde el navegador, elige sala e idioma, y lee con **p50 693 ms** de
atraso sobre lo que se está diciendo.

El audio entra de cuatro formas: un archivo, un stream con URL (RTMP/HLS/SRT),
el micrófono de la consola desde el navegador, o **otra pestaña del navegador**
— que es como se subtitula una transmisión que sólo podés mirar: una plataforma
detrás de login, un webinar, un reproductor cuyo stream no es tuyo.

## La inspiración

Nerdearla tiene charlas en español y en inglés, y público que no comparte
ninguno de los dos por completo. La traducción humana simultánea es cara, no
escala a diez salas en paralelo, y no deja transcripción para después.

## Cómo está construido

**El audio se decodifica una vez; el texto se reparte.** Transcribir es lo caro;
traducir texto es barato. Una sala con cinco idiomas paga una transcripción y
cinco traducciones de texto, no seis decodificaciones de audio. Por eso el costo
por idioma extra es casi plano: **USD 0.65 por sala-hora**, y diez salas por
diez horas con tres idiomas salen ≈ **USD 60**.

**Streaming, no troceado.** `gemini-3.5-transcribe-live` por WebSocket, con
hipótesis parciales que se van corrigiendo. Trocear el audio en pedazos de
cuatro segundos da latencia de cuatro segundos como piso; el streaming no tiene
ese piso.

**Las oraciones se liberan por cuenta propia.** El modelo marca fin de habla
cuando el orador hace una pausa, y un orador en pleno vuelo puede no pausar en
veinte segundos. Calandria libera una oración cuando el modelo deja de
revisarla, sin esperar esa marca. Eso desata la latencia de cuándo el orador
decide respirar.

## El problema más difícil

Decidir **qué texto ya vio el público**. La hipótesis del modelo se reescribe
constantemente, y una sesión que rota trae de vuelta texto ya mostrado. Cuatro
diseños fallaron antes de dar con el correcto, y el error estaba en la pregunta:
preguntaba *si* algo ya se había mostrado, un booleano. La pregunta correcta es
*cuánto* ya se mostró — una longitud. Un enunciado que vuelve casi siempre trae
un poco de habla nueva al final, así que "¿ya lo vieron?" no tiene buena
respuesta: suprimir pierde lo nuevo, mostrar repite lo viejo.

## Lo que encontré midiendo, que no está documentado

**Una sesión de Live se deteriora con la edad.** No da error, no aparece en
ningún contador. La misma frase corta salió subtitulada en **1,5 s** al empezar
la sesión y en **19,5 s** un minuto después, con las hipótesis parciales
llegando cada 9 s en vez de cada 1,3 s.

La rotación de sesión ya existía en el proyecto, dimensionada contra el límite
de 10 minutos de la API — el límite que la documentación menciona, y el
equivocado. Rotando cada 75 segundos el atraso se mantiene plano: medido sobre
6 minutos de charla real cruzando **4 rotaciones**, entre −0,4 s y 1,1 s en el
idioma original y entre 0,7 s y 2,1 s traducido, sin crecimiento acumulado.

Otras dos que costaron tiempo: en Vertex, `gemini-3.5-flash-lite` no está en
`us-central1` sino en el endpoint `global`, y el 404 habla del modelo de una
forma que manda a revisar permisos que están bien. Y `gemini-3.5-flash` tarda el
doble que `flash-lite` para devolver la traducción idéntica — en subtítulos en
vivo, subir de modelo empeora el producto.

## Los números

| | |
|---|---|
| Latencia habla → subtítulo | **p50 693 ms** en audio real de Nerdearla |
| Costo | **USD 0.65** por sala-hora con un idioma extra |
| Escala | **100 salas y 400 espectadores en 18.6% de un núcleo** |
| Precisión de palabra | **92.7%** inglés · **95.4%** castellano |
| Tests | **134**, todos corren sin credenciales |

## Lo que no está cubierto, dicho de frente

El respaldo degradado queda unos 12 segundos atrás del orador: existe para que
un fallo del streaming no deje la sala sin subtítulos, no para competir en
latencia. Al cerrar un stream el modelo a veces recapitula reformulado y se
escapa una línea repetida — 6% de los pares sobre audio real. Y las cien salas
miden el proceso: la concurrencia del modelo es cuota de API y ata mucho antes
que la máquina.

## Construido con

Python · FastAPI · asyncio · WebSockets · Gemini Live API
(`gemini-3.5-transcribe-live`) · `gemini-3.5-flash-lite` · Vertex AI · ffmpeg ·
AudioWorklet · Redis (opcional) · Docker

## Cómo probarlo sin credenciales

```bash
git clone https://github.com/lueaxx/calandria && cd calandria
docker compose --profile demo up demo-offline
```
