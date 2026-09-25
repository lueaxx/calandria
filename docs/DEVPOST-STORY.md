## Inspiration

Nerdearla tiene charlas en español y en inglés, y público que no comparte ninguno
de los dos por completo. Interpretación humana simultánea cuesta caro, no escala
a diez salas en paralelo y no deja transcripción para después.

La pregunta no era si se puede traducir en vivo. Era por qué cuesta tanto que una
conferencia lo tenga. La respuesta resultó arquitectónica: casi todo decodifica
el audio una vez por cada idioma. Seis idiomas, seis veces el trabajo caro.

## What it does

Toma el audio de una sala y devuelve subtítulos en el idioma original y
traducidos a cuantos idiomas quiera el evento. El público entra desde el
navegador, elige sala e idioma, y lee con 693 ms de atraso (p50).

El audio entra de cuatro formas: un archivo, un stream con URL, el micrófono de
la consola, o el audio de otra pestaña del navegador. Esto último permite
subtitular una transmisión que sólo se puede mirar, como una plataforma detrás de
login. No se toca el stream: lo que la pestaña suena es lo que se subtitula.

Una sala puede no declarar su idioma. El modelo lo detecta por enunciado, así que
una mesa bilingüe o una pregunta del público se traducen en vez de romperse.

## How we built it

El audio se decodifica una vez y el texto se reparte. Transcribir es lo caro;
traducir texto es barato. Una sala con cinco idiomas paga una transcripción y
cinco traducciones, no seis decodificaciones. De ahí que el costo por idioma
extra sea casi plano: USD 0.65 por sala-hora.

Streaming, no troceado. `gemini-3.5-transcribe-live` por WebSocket. Trocear en
pedazos de cuatro segundos da cuatro segundos de latencia como piso.

Y las oraciones se liberan solas: el modelo marca fin de habla cuando el orador
pausa, y un orador en pleno vuelo puede no pausar en veinte segundos. Calandria
libera una oración cuando el modelo deja de revisarla, sin esperar esa marca.

Python, FastAPI, asyncio, WebSockets. El bus es intercambiable, en memoria o
Redis, así que un evento grande reparte salas entre réplicas sin cambiar código.

## Challenges we ran into

Lo difícil fue decidir qué texto ya vio el público. Cuatro diseños fallaron. El
error estaba en la pregunta: yo preguntaba si algo ya se había mostrado, un
booleano, cuando lo correcto es cuánto ya se mostró, una longitud. Un enunciado
que vuelve casi siempre trae habla nueva al final, así que "¿ya lo vieron?" no
tiene buena respuesta: suprimir pierde lo nuevo, mostrar repite lo viejo.

Después apareció algo que no está documentado: una sesión de Live se deteriora
con la edad y no da error. La misma frase corta salió subtitulada en 1,5 s al
empezar la sesión y en 19,5 s un minuto después. La rotación existía, pero
dimensionada contra el límite de 10 minutos de la API, que es el límite que la
documentación menciona y el equivocado. Rotando cada 75 segundos el atraso se
mantiene entre −0,4 s y 2,1 s a lo largo de cuatro rotaciones.

También perdí un día midiendo en la capa equivocada. El reporte era "tarda"; yo
medía el WebSocket y obtenía menos de un segundo. Mis números eran correctos y
respondían una pregunta que nadie había hecho: la demora estaba en la página, que
sólo pintaba frases cerradas.

Lo peor son las fallas que ningún contador reporta. Dos pestañas de captura sobre
la misma sala mezclan dos copias del ambiente en un solo audio. La latencia se
fue de 1 s a 8 s y después los subtítulos pararon, con el panel marcando sala
corriendo, cero descartes y cero errores.

## Accomplishments that we're proud of

Todos los números están medidos, ninguno estimado, y cada uno se reproduce con un
comando del repo:

| | |
|---|---|
| Latencia habla → subtítulo | p50 693 ms en audio real de Nerdearla |
| Costo | USD 0.65 por sala-hora con un idioma extra |
| Escala | 100 salas y 400 espectadores en 18.6% de un núcleo |
| Precisión de palabra | 92.7% inglés, 95.4% castellano |
| Tests | 143, todos corren sin credenciales |

La latencia sale de seis minutos de una charla real, con público, risas y un
orador con acento, no de audio de laboratorio.

Y cualquiera puede clonar el repo y correr los 143 tests sin una sola credencial,
porque hay un backend `fake` que ejercita el sistema entero sin red.

## What we learned

Cosas que aparecieron probando y no están en la documentación de Google:

- `mode=SMART` y `word_timestamp` son incompatibles; el servidor cierra el socket
  con código 1007.
- El marcador de fin de habla llega después del texto que le corresponde. Medir
  contra el más reciente da la duración de la oración, no la latencia: ese bug
  reportaba 14.020 ms donde la verdad eran 520 ms.
- Ajustar el VAD no sirve para que un orador sin pausas produzca finales.
- `gemini-3.5-transcribe-live` no existe en Vertex AI, en ninguna región. La
  traducción sí está en ambos, así que terminé usando un proveedor por rol.
- `gemini-3.5-flash` tarda el doble que `flash-lite` y devolvió la traducción
  idéntica. En subtítulos en vivo la latencia es el producto: subir de modelo
  empeora el resultado.
- Las sesiones Live concurrentes están limitadas por proyecto, y pasarse no
  encola: cierra con 1008 en las salas que estén hablando, no en la que pidió de
  más. El síntoma es salas sin relación fallando juntas.

La lección de método costó más que todas: los tests unitarios prueban que un
componente es correcto, no que alguien lo llame bien. Dos bugs de este proyecto
fueron eso exactamente.

## What's next for Calandria

- Traducir también las hipótesis parciales, con un umbral de estabilidad para no
  gastar una llamada por cada revisión.
- Que la reconexión recupere el contexto perdido; hoy la primera frase después de
  una caída pierde continuidad.
- Diarización, para saber quién habla en un panel.
- Alineado palabra por palabra en los SRT, que hoy son por oración.
- Un detector de deriva que avise cuando una sala se atrasa, en vez de esperar a
  que alguien lo note desde la butaca.
