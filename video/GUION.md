# Guion de narración — `calandria-demo.mp4`

90 segundos, cronometrado al video que está en esta carpeta. Grabá la voz
encima; no hace falta editar la imagen.

**Cómo leerlo.** El texto en **negrita** es lo que decís. Lo de abajo es qué se
ve en pantalla en ese momento, para que no te pierdas. Los tiempos son
aproximados — si te atrasás unos segundos no pasa nada, el video no tiene
cortes bruscos.

Todo lo que afirma este guion es medido y reproducible desde el repo. Si un
jurado te pregunta de dónde sale un número, la respuesta está en el README.

---

## 0:00 – 0:33 · La vista de la audiencia

> *En pantalla: subtítulos en inglés y español apareciendo bajo una charla real
> de Nerdearla. El texto gris crece palabra por palabra y después se asienta.*

**"Esto es Calandria. Está transcribiendo una charla real de Nerdearla, en
vivo, y traduciéndola al español mientras la persona todavía está hablando."**

*(pausá dos segundos, dejá que se vea el texto creciendo)*

**"Mirá el texto gris: esa es la hipótesis del modelo, y aparece antes de que
la oración termine. Cuando el modelo la cierra, se pone en blanco, y la
traducción llega un segundo después."**

**"Medido sobre este audio: seiscientos noventa y tres milisegundos desde que
la persona habla hasta que el subtítulo existe."**

**"Esa diferencia no es de ajuste fino, es de arquitectura. Si trocearas el
audio en bloques de segundos, el texto no podría existir antes de que el bloque
termine. Acá va en streaming, por eso se ve escribirse."**

> 💡 *Si te sobra tiempo:* **"Arriba elegís sala e idioma. Cada persona en la
> sala elige el suyo."**

---

## 0:33 – 1:00 · El panel de operación

> *En pantalla: el panel. Dos salas, latencias, costo. Cerca del final alguien
> tipea 10 y 10 en la caja de proyección y aparece $64.*

**"Este es el panel para el equipo de producción. Dos salas en simultáneo: una
charla en inglés subtitulada al español, y una en español subtitulada al
inglés. Las dos direcciones."**

**"Cada sala muestra su latencia contra una marca de un segundo. Verde quiere
decir que la sala le sigue el ritmo al orador."**

*(cuando aparezca el número tecleado)*

**"Y muestra lo que está gastando, mientras lo gasta. Al ritmo que está
midiendo ahora mismo, diez escenarios durante diez horas cuestan sesenta y
cuatro dólares para toda la conferencia."**

**"Ese es el punto. El problema de Nerdearla no es tecnológico, es de
presupuesto: hoy la accesibilidad se decide por lo que sale, no por quién la
necesita."**

> 💡 *Si te sobra tiempo:* **"Medimos cien salas en un solo proceso, con
> cuatrocientos espectadores conectados, usando el diecinueve por ciento de un
> núcleo."**

---

## 1:00 – 1:22 · El overlay sobre el stream

> *En pantalla: el video real de la charla con los subtítulos quemados encima.*

**"Los mismos subtítulos se queman en el stream. Es una URL que se pega como
browser source en OBS o vMix, con fondo transparente, y se configura entera
desde la barra de direcciones — porque un operador la carga en un diálogo donde
no hay otra cosa donde hacer clic."**

**"Y cuando la charla termina, sale el SRT. El video grabado queda subtitulado
también, en todos los idiomas en que corrió el evento."**

---

## 1:22 – 1:30 · Cierre

> *En pantalla: la página para enviar audio desde la laptop del escenario.*

**"Para conectar un escenario no hace falta encoder ni servidor de streaming:
abrís esta página en la máquina que ya está enchufada a la consola, elegís la
entrada y listo."**

**"Es Apache dos punto cero, corre con un solo comando, y arranca sin ninguna
API key si solo querés mirarlo. Está todo en GitHub."**

---

# Si te preguntan (respuestas cortas y honestas)

**¿Qué pasa con las charlas de cuarenta minutos?**
La API corta la sesión de transcripción a los diez minutos. Calandria abre la
siguiente antes de tiempo, le manda el mismo audio unos segundos y cose la
costura. Verificado: dos rotaciones, cero huecos, cero palabras duplicadas,
cero saltos de tiempo.

**¿Y si se cae la conexión con el modelo?**
Degrada en vez de apagarse: pasa a transcripción por bloques. Medido, queda
unos doce segundos atrás del orador en vez de menos de uno. Es un número malo y
sobrevivible, que es el canje que ese camino existe para hacer. El panel marca
la sala como degradada.

**¿Cómo maneja los términos técnicos?**
Un archivo de glosario que alimenta dos cosas a la vez: el sesgo de vocabulario
del transcriptor y las reglas del traductor. En el video se ve: "deployment" y
"container" quedan sin traducir porque las diapositivas los dicen en inglés.

**¿Cuánto sale de verdad?**
Sesenta y cinco centavos de dólar por sala-hora con un idioma extra. El audio
se decodifica una sola vez y el texto se reparte, así que sumar un cuarto
idioma cuesta casi nada. Ese es el motivo por el que diez salas es una línea de
presupuesto y no una propuesta.

**¿Escala de verdad?**
Cien salas y cuatrocientos espectadores en un proceso, con diecinueve por
ciento de un núcleo. Está medido con un script que viene en el repo, no
extrapolado. El límite real no es la máquina, es la cuota de la API.

**¿Por qué Gemini y no Whisper?**
Por el modelo de streaming, que es lo que permite el texto provisional. Pero la
capa de transcripción es una interfaz de un método: quien quiera Whisper o
Gemma implementa esa interfaz y cambia una línea de configuración.

---

# Antes de subirlo

- [ ] **Subtítulos en inglés hechos con Calandria.** El brief lo sugiere y es la
      demostración más fuerte posible: exportá el SRT desde
      `/api/sessions/<id>/transcript.srt?lang=en` y subilo con el video.
- [ ] Título sugerido: **Calandria — subtítulos en vivo para conferencias, open
      source**
- [ ] En la descripción: el link al repo y la frase *"medido sobre una charla
      real de Nerdearla: 693 ms de latencia, USD 0.65 por sala-hora"*.
