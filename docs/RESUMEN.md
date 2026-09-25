# Calandria — resumen en castellano

Para entender qué se construyó, por qué, y qué falta. El resto de la
documentación está en inglés porque dos de los cuatro jurados no hablan
castellano.

---

## Qué es

Un sistema open source que toma el audio de un escenario, lo transcribe en vivo
y lo traduce a los idiomas que configures. Muchas salas a la vez, en un solo
proceso.

```
docker compose up   →   http://localhost:8080
```

Tres pantallas: la **audiencia** abre una página, elige sala e idioma y lee; el
**stream** usa un overlay transparente en OBS; el **equipo de producción** ve
latencia, errores y cuánta plata lleva gastada el evento.

---

## Los números (todos medidos, no estimados)

| | |
|---|---|
| Latencia habla → subtítulo | **p50 693 ms** en audio real de Nerdearla |
| Costo | **USD 0.65** por sala-hora con un idioma extra |
| 10 salas × 10 horas × 3 idiomas | **≈ USD 60** |
| Precisión de palabra | **92.7%** inglés · **95.4%** castellano |
| Tests | 134 |

La latencia y el costo salen de 6 minutos de una charla real de Nerdearla —con
público, risas y un orador con acento—, no de audio de laboratorio. La
precisión sale de muestras sintéticas donde el guion **es** la referencia
exacta, así que el porcentaje significa algo en vez de ser una impresión.

---

## Las cinco decisiones que definen el proyecto

**1. El audio se decodifica una vez; el texto se reparte.**
Casi todos mandan el audio al modelo una vez por idioma de salida. Acá se
transcribe una sola vez y se traduce el texto resultante. Transcribir cuesta
$0.54/hora; cada idioma adicional agrega $0.04. Esa proporción es la diferencia
entre "soportamos tres idiomas" y "soportamos el que nos alcanzaba".

**2. Streaming, no troceado.**
El texto provisional aparece **mientras la persona sigue hablando** y se asienta
cuando el modelo cierra la oración. Un enfoque por chunks no puede: su texto no
existe hasta que el trozo termina. Eso es lo que se ve en el video sin
explicarlo.

**3. La sesión rota cada 75 segundos, y esa cifra es el hallazgo.**
La API corta una sesión de transcripción a los 10 minutos, así que Calandria abre
la siguiente antes, le manda el mismo audio unos segundos y cose la costura.
Eso explica *que* rote; no explica *cada cuánto*.

Midiendo con micrófono en vivo apareció la razon real: **una sesión responde en
tiempo real cuando es nueva y se va atrasando con la edad.** La misma frase corta
salió subtitulada en 1,5 s al empezar y en **19,5 s un minuto después**, con las
hipótesis parciales llegando cada 9 s en vez de cada 1,3 s.

Dimensionar el intervalo contra el límite de 10 minutos —la lectura obvia, y la que
tenía este proyecto hasta hoy— deja al público leyendo veinte segundos atrasado
durante nueve de cada diez minutos. Rotando antes de que el deterioro aparezca, el
atraso se mantiene plano: medido sobre 6 minutos de charla real cruzando **4
rotaciones**, entre −0,4 s y 1,1 s en el idioma original y entre 0,7 s y 2,1 s
traducido, sin crecimiento acumulado, sin huecos, sin duplicados y sin audio
descartado.

Cuesta el solape: dos sesiones escuchan los mismos 3 s en cada rotación, o sea
≈4% de audio facturado de más en vez de 0,6%. Menos de tres centavos sobre los
USD 0,65 por sala-hora.

**4. Entra audio de donde sea, sin instalar nada.**
Un archivo, un stream con URL, el micrófono de la consola —y también **otra
pestaña del navegador**. Eso último es lo que permite subtitular una transmisión
que soló podés mirar: una plataforma detrás de login, un webinar, un reproductor
cuyo stream no es tuyo. No se toca el stream, así que la cookie de sesión, el
embebido propietario o el DRM dan igual: lo que la pestaña suena es lo que se
subtitula. Medido sobre una plataforma de conferencias en vivo: **1,1 a 2,0 s**
hasta el subtítulo traducido.

Una sola fuente por sala, y gana la conexión más nueva. Dos pestañas empujando a
la misma sala mezclan dos copias del ambiente en un solo audio, y eso **ningún
contador lo reporta**: simplemente empeora. Pasó en vivo —la latencia se fue de
1 s a 8 s y después los subtítulos pararon— con el panel marcando sala corriendo,
cero descartes, cero errores.

**5. Degrada en vez de apagarse.**
Si el streaming falla, cae a transcripción por trozos: peor latencia, subtítulos
igual, y la sala queda marcada como degradada en el panel. Un evento en vivo no
tiene ventana de mantenimiento.

---

## Lo que costó de verdad

No fue transcribir ni traducir —eso funcionó en las primeras horas—. Fue
**decidir qué mostrar**.

El modelo entrega dos vistas del mismo habla que no van sincronizadas: la
hipótesis en curso (que repite la intervención entera en cada actualización) y
sus propios finales (que reescriben el texto, expanden contracciones,
repuntúan). Cuatro implementaciones fallaron, cada una con un caso real
distinto: oraciones soltadas dos veces, 137 captions de 136 palabras cada una,
recapitulaciones colándose al cerrar el stream.

El error común a todas fue **una sola estructura para dos preguntas**: *¿dónde
corto esta intervención?* y *¿la audiencia ya leyó esto?*. Tienen vidas
distintas —la primera se reinicia con cada intervención, la segunda tiene que
sobrevivirlas— y forzarlas en la misma variable hacía que reiniciar una
destruyera la otra.

Cada test en `tests/test_commit.py` nombra el input real del que salió.

---

## Cosas que aprendí probando, que no están en la documentación de Google

- **`mode=SMART` y `word_timestamp` son incompatibles.** El servidor cierra el
  socket con código 1007. `config.py` lo rechaza al arrancar.
- **El marcador de fin de habla llega *después* del texto que le corresponde.**
  Medir contra el marcador más reciente da la duración de la oración, no la
  latencia. Ese bug reportaba 14.020 ms donde la verdad eran 520 ms.
- **Los `audio_offset` son relativos a la sesión, no a la charla.** Al rotar, el
  reloj del servidor vuelve a cero y la charla no. Desincroniza los subtítulos
  exportados a partir del minuto 8.
- **Ajustar el VAD no sirve** para que un orador sin pausas produzca finales:
  todos los valores de silencio y sensibilidad dan resultados idénticos.
- **`gemini-3.5-transcribe-live` no existe en Vertex AI**, en ninguna región.
  Solo en AI Studio. La traducción sí está en ambos.
- **El tier gratuito permite 15 traducciones por minuto por proyecto**, que una
  sola sala con dos idiomas ya supera.
- **Una sesión de Live se deteriora con la edad.** No está documentado en ningún
  lado y no aparece como error. La misma frase: 1,5 s al empezar la sesión,
  19,5 s un minuto después. Es la razón por la que Calandria rota cada 75
  segundos y no cada 8 minutos.
- **En Vertex, `gemini-3.5-flash-lite` no está en `us-central1`:** está en el
  endpoint `global`. Apuntar a una región devuelve 404 para el modelo, no para
  el proyecto, así que el mensaje de error manda a revisar permisos que están
  bien.
- **`gemini-3.5-flash` tarda el doble que `flash-lite` y devolvió la traducción
  idéntica** (3,35 s contra 1,84 s, medido). En subtítulos en vivo la latencia
  *es* el producto: subir de modelo empeora el resultado.
- **Dos sockets de audio en una misma sala no dan error: dan un sistema peor.**
  El modelo recibe dos copias del ambiente intercaladas, la latencia se va de
  1 s a 8 s y después los subtítulos paran — con estado `running`, cero
  descartes y cero errores en el panel. La única huella eran dos líneas
  `[accepted]` en el log.

---

## Sobre proveedores y plata

Transcripción y traducción pueden usar proveedores distintos, y normalmente
conviene:

```yaml
stt:         { provider: aistudio }   # donde vive el modelo de streaming
translation: { provider: vertex }     # donde hay cuota y créditos
```

Los créditos de Google Cloud **no aplican** a Gemini vía AI Studio desde marzo
2026, pero **sí** vía Vertex. Y Vertex no tiene el techo de 15/minuto.

---

## Qué falta

1. **El video** (1-2 min). Guion y plan de tomas en [DEMO.md](DEMO.md), con los
   tiempos y qué decir en cada uno.
2. **Pasar el repo a público** antes de enviarlo — lo pide el reglamento.
3. **Enviarlo en Devpost** antes del 25/9 a las 15:00 UTC (12:00 Argentina).

## Artefacto conocido

Al cerrar un stream el modelo a veces recapitula el último tramo reescrito, y
una línea repetida se escapa. Sobre audio real quedó en **6% de los pares de
captions**, desde 20% antes de los últimos arreglos. Está documentado en vez de
escondido.
