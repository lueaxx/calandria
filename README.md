# Calandria

**Live transcription and translation for conferences, at conference scale.**

The calandria is a South American songbird that imitates the call of whatever
other bird it hears. This one listens to a stage and repeats it in your language.

Every conference with talks in more than one language has the same problem, and
most solve it by paying per stage for a commercial tool, or by not solving it.
Calandria is the open alternative: one process captions many stages at once, in
as many languages as you configure, and tells you exactly what it is costing
while it does it.

```
docker compose up          →  http://localhost:8080
```

---

## What it does

- **Transcribes live audio** from a stream, a file or a microphone, in the
  speaker's own language, with sub-second latency.
- **Translates each finalized line** into every language you configure, as it
  happens.
- **Runs many stages at once.** Two is the tested minimum; one process
  comfortably carries well over a dozen.
- **Shows the captions** on a phone-friendly page, as a transparent overlay for
  OBS or vMix, or as a downloadable SRT/VTT/TXT file when the talk ends.
- **Tells the production team what is happening** — per-stage latency, errors,
  and a running dollar figure.

Measured on the sample audio in this repository, which you can reproduce:

| | |
|---|---|
| Transcription latency, speech to caption | **p50 ~600 ms · p95 ~790 ms** |
| Translation latency, speech to translated caption | ~1.5–2.5 s |
| Word accuracy, English talk | **92.7%** |
| Word accuracy, Spanish talk | **95.4%** |
| Cost, one stage with two extra languages | **USD 0.60 per hour** |
| Projected cost, 10 stages × 10 hours × 3 languages | **USD ~60** |

```bash
python scripts/measure_accuracy.py
```

Accuracy is a real measurement rather than an impression, because the samples
are synthesised from a written script — so the script *is* ground truth, and
word error rate means something. The glossary is worth about 1.3 points on this
sample (91.4% → 92.7%, two words in 151); it matters more the more product
names and speaker names a talk contains. `--no-glossary` reproduces that
comparison.

Latency comes from `/dashboard`, which measures it rather than estimating it.
How, and why that distinction matters, is in
[Measuring latency honestly](#measuring-latency-honestly).

---

## Try it in 30 seconds, with no API key

Calandria ships a transcription backend that replays a scripted transcript
instead of calling a model. The whole system runs — ingest, fan-out, viewer,
overlay, dashboard, export — so you can see what it does before deciding
whether to create a Google Cloud account.

```bash
git clone https://github.com/lueaxx/calandria
cd calandria
cp calandria.example.yaml calandria.yaml
cp glossary.example.yaml glossary.yaml

CALANDRIA_STT_BACKEND=fake docker compose up
```

Then open:

| | |
|---|---|
| <http://localhost:8080> | the audience view — pick a stage and a language |
| <http://localhost:8080/dashboard> | the production view |
| <http://localhost:8080/overlay?session=keynote&lang=es> | the OBS browser source |

## Then run it for real

1. Get a key at <https://aistudio.google.com/apikey>, then **attach a billing
   account** to it. This is not optional for a real event, and the reason is
   specific: the free tier allows 15 translation requests per minute across the
   whole project, and Calandria translates each sentence as the speaker
   finishes it. One stage in two languages exceeds that on its own.

   Symptom if you skip it: original-language captions look perfect and
   translations arrive with gaps. The dashboard counts the errors and the log
   says `429 RESOURCE_EXHAUSTED`. Attaching billing moves you to Tier 1
   instantly and the problem disappears.

   > **Heads up on credits.** Since 2 March 2026, Gemini API usage through AI
   > Studio is excluded from the USD 300 Google Cloud free trial. Those credits
   > *do* still apply through Vertex AI, so if you want to run this on trial
   > credit, set `provider: vertex` (see [Credentials](#credentials)).

2. Put it in `.env`:

   ```bash
   echo "GEMINI_API_KEY=your-key-here" > .env
   ```

3. Check everything before the doors open:

   ```bash
   docker compose run --rm calandria -c calandria.yaml --check
   ```

   ```
   provider        : aistudio
   stt backend     : gemini (gemini-3.5-transcribe-live)
   translation     : on (gemini-3.5-flash-lite)
   sessions        : 2
     - keynote          file    -> en, es, pt
     - track-2          file    -> en, es
   glossary        : 24 terms

   OK - credentials valid and every configured model is reachable.
   ```

4. `docker compose up`.

### Without Docker

```bash
python -m venv .venv && . .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -e .
python -m calandria -c calandria.yaml
```

You will need **ffmpeg** on `PATH`; it decodes every audio source Calandria
accepts. The Docker image already has it.

---

## How it works

```
  ┌── ingest ─────────────────────────────────────────────┐
  │  RTMP · HLS · file · microphone   →  ffmpeg           │
  │  everything becomes 16 kHz mono PCM, 100 ms chunks    │
  └───────────────────────┬───────────────────────────────┘
                          │
              ┌───────────▼────────────┐
              │  SessionWorker         │   one per stage
              │  · Gemini Live (WS)    │
              │  · rotates every 8 min │
              │  · glossary biasing    │
              │  · falls back to       │
              │    chunked on failure  │
              └───────────┬────────────┘
                          │  interim + final captions
              ┌───────────▼────────────┐
              │  bus: memory │ redis   │   one node, or fifty
              └───────────┬────────────┘
             ┌────────────┴─────────────┐
   ┌─────────▼────────┐      ┌──────────▼─────────┐
   │ translator ×lang │      │  websocket fan-out │
   │ flash-lite       │      │                    │
   └─────────┬────────┘      └──────────┬─────────┘
             └───────────┬──────────────┘
     ┌───────────┬───────┴────┬──────────────┬─────────────┐
     ▼           ▼            ▼              ▼             ▼
  viewer     overlay      transcript      dashboard     REST API
  (phone)    (OBS)        .srt .vtt .txt  (latency,     (integrate
                                           cost)         anything)
```

### The idea that makes it scale

Audio is the expensive input. Text is nearly free.

Most approaches send the audio to a model once **per output language**, or send
it in short chunks and ask for transcript-plus-translations in one response.
Calandria transcribes the audio **once**, then translates the resulting text N
times. Transcription runs about USD 0.54 an hour; each additional language adds
about USD 0.04.

That ratio is the whole argument. Adding Portuguese across ten stages for a
two-day conference costs about the price of a coffee, which is the difference
between "we support three languages" and "we support the one we could afford".

### Latency, in two tiers

The audience gets text in two stages, because the two are not equally urgent:

```
t=0.0s  🎤  "...so the key thing about Kubernetes operators is..."
t=0.4s  📺  so the key thing about kubernetes oper          (provisional, dim)
t=0.9s  📺  so the key thing about Kubernetes operators is  (provisional, dim)
t=1.6s  📺  So the key thing about Kubernetes operators is… (settled)
t=2.4s  📺  Entonces, lo clave de los operadores de Kubernetes es…
```

Someone who understands the speaker reads along in well under a second. Someone
reading the translation is about two seconds behind — better than a human
interpreter, who typically runs three to six seconds back.

### Translation cannot wait for the speaker to breathe

The transcription model finalises a segment when it detects end of speech, and
translation runs on finalised text. That couples the translated captions to
something Calandria does not control: how often the speaker pauses.

Measured on a real talk, finalised segments arrived **15 to 20 seconds apart**.
On continuous speech they did not arrive at all until the stream closed — one
segment containing the entire talk. Tuning the voice detector does not help;
every silence threshold and sensitivity setting produced byte-identical results.

So Calandria commits sentences itself. When the running hypothesis contains a
completed sentence *followed by more text*, the model has moved past that
sentence and is no longer revising it, so it can be treated as settled and sent
to be translated. The wait drops from tens of seconds to about two.

The trailing fragment is never committed on sentence grounds — it is the part
still being revised. A run-on with no punctuation is released on word count
instead, because a reader should not be held hostage to a speaker who never
reaches a full stop. `calandria/stt/commit.py`, and the property test in
`tests/test_commit.py` that streams a talk word by word and asserts every word
is delivered exactly once.

### The ten-minute problem

A Gemini live transcription session ends after ten minutes. Conference talks do
not. Naively reconnecting drops the words spoken during the handover, and since
demos are short, it is easy to ship this bug without noticing.

Calandria opens the replacement session **early**, feeds both the same audio for
a few seconds, then retires the old one and removes the duplicated text at the
seam (`calandria/stt/dedup.py`). The audience sees nothing; the dashboard counts
a rotation.

The matching is on normalised words and requires at least a two-word overlap
before it cuts anything, because the two sessions punctuate the same audio
differently. Showing a repeated word is a blemish; silently deleting a sentence
the speaker said is a failure of the thing being built.

### It degrades instead of going dark

A live event has no maintenance window. If the streaming session cannot be kept
alive, Calandria falls back to chunked transcription: latency goes from under a
second to roughly the buffer length, the dashboard marks the stage
**degraded**, and the captions keep coming. Set `stt.fallback_enabled: false` if
you would rather it stop.

---

## Credentials

| | |
|---|---|
| **AI Studio** (default) | `GEMINI_API_KEY`. Simplest. |
| **Vertex AI** | `provider: vertex` plus `GOOGLE_CLOUD_PROJECT` and `GOOGLE_CLOUD_LOCATION`. Use this to spend Google Cloud credits. |

Models used, all configurable:

| Role | Default | Why |
|---|---|---|
| Streaming transcription | `gemini-3.5-transcribe-live` | interim + final captions over a websocket |
| Fallback transcription | `gemini-3.5-transcribe` | request/response, used only when streaming fails |
| Translation | `gemini-3.5-flash-lite` | cheap and fast enough to keep up with speech |

Swapping in a different provider means implementing `SttBackend` — one method,
`transcribe(frames) -> AsyncIterator[SttEvent]`, defined in
`calandria/stt/base.py` — and setting `stt.backend`. The `fake` backend is a
40-line worked example. A local Whisper or Gemma backend fits the same shape;
nothing above that layer knows which one is loaded.

---

## Configuration

One file describes the whole conference. Everything is optional; the shortest
useful config is a single stage.

```yaml
sessions:
  - id: keynote
    title: "Main stage"
    source: { type: stream, url: "rtmp://encoder.local/live/keynote" }
    source_language: en
    targets: [es, pt]
```

The full set, with defaults, is in [`calandria.example.yaml`](calandria.example.yaml).
Notable knobs:

| Key | Default | |
|---|---|---|
| `stt.backend` | `gemini` | `fake` runs everything with no credentials |
| `stt.mode` | `SMART` | removes filler words; `VERBATIM` keeps them |
| `stt.rotate_after_seconds` | `480` | must stay under the API's 600 s session cap |
| `stt.language_hint` | `true` | materially faster lock-on than auto-detect |
| `stt.commit_sentences` | `true` | translate per sentence instead of per pause |
| `stt.fallback_enabled` | `true` | degrade rather than go silent |
| `translation.retry_budget_seconds` | `6` | how long a rate-limited line is worth retrying |
| `translation.context_segments` | `3` | previous lines sent for continuity |
| `features.*` | all on | every feature can be switched off |
| `features.catchup_buffer` | `200` | lines a late joiner can scroll back through |

### The glossary earns its keep

`glossary.yaml` feeds two things from one list: the transcriber's vocabulary
bias, and the translator's rules.

```yaml
terms: [Nerdearla, Kubernetes, PostgreSQL, nullplatform]
keep_untranslated: [deployment, pipeline, commit, open source]
speakers: [Eduardo Casarero, Omar Sanseviero]
```

Without it, "Kubernetes" comes back as "cooper netties" and a talk whose slides
all say *deployment* gets captions that say *despliegue*. Keep it under about
150 entries — a longer list dilutes the bias and makes recognition worse.

---

## The three surfaces

**Audience** — `/`. Picks a stage and a language, remembers both. Text size and
light/dark are adjustable and persist. Scroll back to re-read what you missed;
"Original + translation" shows both stacked.

**Overlay** — `/overlay`, configured entirely by query string because an
operator sets it up inside OBS's browser-source dialog, where there is nowhere
to click but a URL bar:

```
/overlay?session=keynote&lang=es&lines=2&size=3.2vw&position=bottom&plate=on
```

Transparent background, self-contained text contrast (outline *and* shadow — an
outline alone fails over busy footage, a shadow alone fails over bright slides),
and it clears itself after a silence so a paused stream does not look frozen.

**Production** — `/dashboard`. Per-stage state, latency against a one-second
budget, rotations, errors, and what the event has spent so far. The projection
box extrapolates the *measured* rate to any number of stages and hours.

**API** — `/api/docs`. Sessions can be created and destroyed at runtime, so a
schedule change does not need a restart.

---

## Measuring latency honestly

It is easy to publish a latency number that flatters the system. Measuring how
fast the server pushed bytes to a browser will report single-digit
milliseconds, and it tells the audience nothing about how far behind the speaker
they are reading.

Calandria reports the only number that describes the audience's experience:
**the wall-clock time between audio being handed to the model and the caption
for it existing.** It is measured against the server's own `audio_offset`
markers, which say where in the talk a thing happened, cross-referenced with
when Calandria fed that exact position.

Getting this right required care, twice.

The end-of-speech marker arrives *after* the transcript it belongs to, so timing
a caption against the most recent marker measures the length of the sentence
instead of the delay. That bug reported a confident **14 020 ms** where the real
figure was **520 ms**. Finals are now held until their own marker arrives.

The second problem was that the marker only exists when the speaker pauses. A
stage whose speaker talks straight through produced captions and no
measurements, so a healthy stage was indistinguishable from a stalled one on the
dashboard. Time-to-first-caption is now sampled at the *start* of each speech
burst as well, which is well defined for every stage.

Both live in `calandria/stt/gemini.py`.

---

## Scaling

One process, in-memory bus, is the default and carries well over a dozen stages
— pushing audio into a live session costs well under 1% of a core per stage.

Beyond that, set `bus: redis://host:6379` and run several replicas. Captions
are published to Redis, so any replica can serve any viewer and a reconnecting
phone can land anywhere. Nothing else changes.

[SCALING.md](SCALING.md) has the measurements, the failure modes, and a worked
example for a ten-stage event.

---

## Development

```bash
pip install -e ".[dev]"
pytest
```

The tests that matter cover the parts that fail silently: the rotation seam, the
cost arithmetic, subtitle timing, and config validation. The `fake` backend
means the pipeline is testable end to end without credentials or spend.

---

## Sample audio

`samples/` holds an English talk and a Spanish one, each with the script it was
read from. They are **synthesised, not borrowed** — a conference recording is
rarely licensed in a way that allows redistributing it inside an Apache-2.0
repository, and a sample file that quietly creates a licensing problem for
everyone who forks the project is a bad sample file.

Synthesising also buys something a borrowed recording cannot: the transcript is
ground truth, so accuracy is measurable. Regenerate them with
`python scripts/make_samples.py`.

To caption a real talk instead:

```bash
./scripts/fetch-talk.sh "https://www.youtube.com/watch?v=..." samples/talk.wav 120 300
```

---

## License

Apache 2.0. See [LICENSE](LICENSE).

Use it, fork it, run it at your event. If you do run it at a conference, an
issue saying how it went would be genuinely useful — most of what is hard here
only shows up on the day.
