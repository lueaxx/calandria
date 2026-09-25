## Inspiration

Nerdearla tiene charlas en español y en inglés, y público que no comparte ninguno
de los dos por completo. Interpretación humana simultánea cuesta caro, no escala
a diez salas en paralelo, y no deja transcripción para después.

La pregunta que me hice no fue si se puede traducir en vivo, porque eso ya se
puede. Fue por qué cuesta tanto que una conferencia lo tenga. La respuesta
resultó ser arquitectónica: casi todas las soluciones decodifican el audio una
vez por cada idioma. Seis idiomas, seis veces el trabajo caro. Calandria
decodifica una vez y reparte texto.

## What it does

Toma el audio de una sala y devuelve subtítulos en el idioma original y
traducidos a cuantos idiomas quiera el evento, en vivo. El público entra desde el
navegador, elige sala e idioma, y lee con 693 ms de atraso (p50) sobre lo que se
está diciendo.

El audio entra de cuatro formas: un archivo, un stream con URL (RTMP/HLS/SRT), el
micrófono de la consola desde el navegador, o el audio de otra pestaña del
navegador. Esto último es lo que permite subtitular una transmisión que sólo se
puede mirar: una plataforma detrás de login, un webinar, un reproductor cuyo
stream no es tuyo. No se toca el stream, así que la cookie de sesión, el embebido
propietario o el DRM dan igual. Lo que la pestaña suena es lo que se subtitula.

Una sala puede además no declarar su idioma, con `source_language: auto`. El
modelo lo detecta por enunciado, así que una mesa bilingüe o una pregunta del
público se traducen en vez de romperse.

Hay cuatro superficies: la vista de audiencia, un overlay transparente para
OBS/vMix, un panel de monitoreo con latencia y costo en vivo, y la página de
captura. Al terminar, la transcripción se exporta en SRT, VTT, TXT o JSON por
idioma.

## How we built it

El audio se decodifica una vez y el texto se reparte. Transcribir es lo caro;
traducir texto es barato. Una sala con cinco idiomas paga una transcripción y
cinco traducciones de texto, no seis decodificaciones de audio. De ahí sale que
el costo por idioma extra sea casi plano: USD 0.65 por sala-hora, y diez salas
por diez horas con tres idiomas salgan alrededor de USD 60.

Streaming, no troceado. `gemini-3.5-transcribe-live` por WebSocket, con hipótesis
parciales que se corrigen solas. Trocear el audio en pedazos de cuatro segundos
da cuatro segundos de latencia como piso; el streaming no tiene ese piso.

Las oraciones se liberan por cuenta propia. El modelo marca fin de habla cuando
el orador hace una pausa, y un orador en pleno vuelo puede no pausar en veinte
segundos. Calandria libera una oración cuando el modelo deja de revisarla, sin
esperar esa marca. Eso desata la latencia de cuándo el orador decide respirar.

Python, FastAPI, asyncio, WebSockets. El bus es intercambiable, en memoria o
Redis, así que un evento chico corre en un proceso y uno grande reparte salas
entre réplicas sin cambiar código.

## Challenges we ran into

Lo difícil fue decidir qué texto ya vio el público. Cuatro diseños fallaron antes
de dar con el correcto. La hipótesis del modelo se reescribe constantemente, y
una sesión que rota trae de vuelta texto ya mostrado.

El error estaba en la pregunta. Yo preguntaba si algo ya se había mostrado, un
booleano. La pregunta correcta es cuánto ya se mostró: una longitud. Un enunciado
que vuelve casi siempre trae un poco de habla nueva al final, así que "¿ya lo
vieron?" no tiene buena respuesta: suprimir pierde lo nuevo, mostrar repite lo
viejo.

Después apareció algo que no está documentado en ningún lado: una sesión de Live
se deteriora con la edad, y no da error. Midiendo con micrófono en vivo, la misma
frase corta salió subtitulada en 1,5 s al empezar la sesión y en 19,5 s un minuto
después, con las hipótesis parciales llegando cada 9 s en vez de cada 1,3 s.

La rotación de sesión ya existía, dimensionada contra el límite de 10 minutos de
la API. Ése es el límite que la documentación menciona, y es el equivocado.
Rotando cada 75 segundos el atraso se mantiene plano: medido sobre 6 minutos de
charla real cruzando 4 rotaciones, entre −0,4 s y 1,1 s en el idioma original y
entre 0,7 s y 2,1 s traducido, sin crecimiento acumulado.

También perdí un día midiendo en la capa equivocada. El reporte era "tarda"; yo
medía el WebSocket de subtítulos y obtenía menos de un segundo. Mis números eran
correctos y respondían una pregunta que nadie había hecho. La demora estaba en la
página, que descartaba toda hipótesis parcial y sólo pintaba frases cerradas. La
única vista que luce la traducción era la única que se veía rota.

Lo peor son las fallas que ningún contador reporta. Dos pestañas de captura
abiertas sobre la misma sala mezclan dos copias del ambiente en un solo audio. La
latencia se fue de 1 s a 8 s y después los subtítulos pararon, con el panel
marcando sala corriendo, cero descartes y cero errores. La única huella eran dos
líneas `[accepted]` en el log. Ahora sólo se acepta una fuente por sala, y gana
la conexión más nueva: rechazar al que llega parece más seguro pero falla el caso
que pasa de verdad, que es el operador al que se le cae el WiFi y reconecta.

## Accomplishments that we're proud of

Todos los números están medidos, ninguno estimado, y cada uno se reproduce con un
comando que está en el repo:

| | |
|---|---|
| Latencia habla → subtítulo | p50 693 ms en audio real de Nerdearla |
| Costo | USD 0.65 por sala-hora con un idioma extra |
| Escala | 100 salas y 400 espectadores en 18.6% de un núcleo |
| Precisión de palabra | 92.7% inglés, 95.4% castellano |
| Tests | 143, todos corren sin credenciales |

La latencia y el costo salen de seis minutos de una charla real, con público,
risas y un orador con acento, no de audio de laboratorio. La precisión sale de
muestras sintéticas donde el guion es la referencia exacta, así que el porcentaje
significa algo en vez de ser una impresión.

Lo que más me importa: cualquiera puede clonar el repo y correr los 143 tests sin
una sola credencial, porque hay un backend `fake` que ejercita el sistema entero
sin red. Lo verifiqué clonando desde GitHub, no desde mi carpeta de trabajo.

## What we learned

Cosas que aparecieron probando y no están en la documentación de Google:

- `mode=SMART` y `word_timestamp` son incompatibles. El servidor cierra el socket
  con código 1007. La config lo rechaza al arrancar, en vez de a los cuarenta
  minutos de una keynote.
- El marcador de fin de habla llega después del texto que le corresponde. Medir
  contra el marcador más reciente da la duración de la oración, no la latencia.
  Ese bug reportaba 14.020 ms donde la verdad eran 520 ms.
- Los `audio_offset` son relativos a la sesión, no a la charla. Al rotar, el
  reloj vuelve a cero y la charla no.
- Ajustar el VAD no sirve para que un orador sin pausas produzca finales: todos
  los valores de silencio y sensibilidad dan resultados idénticos.
- `gemini-3.5-transcribe-live` no existe en Vertex AI, en ninguna región. Sólo en
  AI Studio. La traducción sí está en ambos, lo que llevó a usar un proveedor
  distinto por rol.
- En Vertex, `gemini-3.5-flash-lite` no está en `us-central1` sino en el endpoint
  `global`, y el 404 habla del modelo de una forma que manda a revisar permisos
  que están bien.
- `gemini-3.5-flash` tarda el doble que `flash-lite` y devolvió la traducción
  idéntica: 3,35 s contra 1,84 s. En subtítulos en vivo la latencia es el
  producto, así que subir de modelo empeora el resultado.
- Las sesiones Live concurrentes están limitadas por proyecto, y pasarse no
  encola: cierra sesiones con 1008, en las salas que estén hablando y no en la
  que pidió de más. El síntoma es salas sin relación fallando juntas.

La lección de método costó más que todas las anteriores. Los tests unitarios
prueban que un componente es correcto, no que alguien lo llame bien. Dos bugs de
este proyecto fueron exactamente eso: un committer impecable que nada invocaba a
tiempo, y después un latido cuyo test pasaba mientras duplicaba cada subtítulo
diez veces por segundo en producción.

## What's next for Calandria

- Traducir también las hipótesis parciales, para que la columna traducida se
  pinte mientras el orador habla y no al cerrar la frase. Hoy no se hace porque
  cada revisión costaría una llamada; con un umbral de estabilidad se podría.
- Que la reconexión recupere el contexto perdido. Hoy una sesión que cae vuelve
  sin memoria de lo dicho, y la primera frase después pierde continuidad.
- Diarización, para saber quién habla en un panel con varios oradores.
- Alineado palabra por palabra en los SRT exportados, que hoy son por oración.
- Un detector de deriva que avise en el panel cuando una sala se está atrasando,
  en vez de esperar a que alguien lo note desde la butaca.
