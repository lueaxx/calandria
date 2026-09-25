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

[**Three demos, each one command**](demo/README.md) — the first needs no
credentials at all. [Deploying at an event](DEPLOYING.md) ·
[Resumen en castellano](docs/RESUMEN.md) ·
[Requisitos del brief contra evidencia](docs/REQUISITOS.md).

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

Measured on a **real Nerdearla talk** — six minutes of conference audio with a
live audience, laughter, an accented speaker and the usual disfluencies:

| | |
|---|---|
| Transcription latency, speech to caption | **p50 693 ms** |
| Cost | **USD 0.65 per stage-hour**, one extra language |
| Captions repeating the previous one | 6% |
| Audio dropped · errors | 0 · 0 |

And on the synthetic samples in this repository, where the script is ground
truth so accuracy is measurable rather than impressionistic:

| | |
|---|---|
| Word accuracy, English | **92.7%** |
| Word accuracy, Spanish | **95.4%** |
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

### Showing each sentence exactly once

Deciding what to release turned out to be the hardest part of this project, and
the reason is worth stating: the model's hypothesis stream and its own finalised
segments are two views of the same speech that do not stay in step. The
hypothesis restates the utterance from its beginning on every update; a final
arrives for a segment that may already have been shown sentence by sentence; and
when a stream closes the model replays the whole segment, sometimes reworded.

Four implementations failed here, each on a different real input: sentences
released twice, utterances released *in full* on every update (137 captions
averaging 136 words), closing restatements slipping through. The mistake common
to all of them was keeping one piece of state for two questions. There are two:

- **Where to cut this utterance.** Answered by the words released so far, with
  an exact prefix comparison. Exact, because it can be — an utterance is a few
  thousand words at most, and bounding that memory was what forced the earlier
  versions into heuristics.
- **Has the audience read this before?** Answered by a short rolling history
  that survives utterance boundaries, because the interims between two repeated
  closing finals clear the cut point just before the second repeat needs it.

Exact matching handles the general case. One similarity threshold, applied only
to blocks of 25 words or more, covers the closing restatement that comes back
with a word changed. `calandria/stt/commit.py`, and 30 tests that each name the
input they came from.

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

Verified by forcing an 18-second rotation interval across a 59-second talk:

| | |
|---|---|
| rotations | 2 |
| errors | 0 |
| audio dropped | 0 |
| backward timestamps | 0 |
| duplicated word runs | 0 |
| of the reference transcript captured | **97%** |
| latency p50 | 705 ms |

Every one of those columns started out wrong. The server's audio offsets are
relative to the *session*, so after the first rotation its clock restarts while
the talk does not — which desynchronises exported subtitles and, once again,
corrupted the latency figure. Each fix is in the commit history with the
measurement that caught it.

### It degrades instead of going dark

A live event has no maintenance window. If the streaming session cannot be kept
alive, Calandria falls back to chunked transcription: the dashboard marks the
stage **degraded** and the captions keep coming. Measured on the fallback path,
end to end: **~12 s** behind the speaker with a 10 s window. That is a bad
number and a survivable one, which is the trade this path exists to make. Set
`stt.fallback_enabled: false` if you would rather it stop.

The fallback deliberately runs a general multimodal model rather than the
dedicated transcriber. For a recovery path availability beats accuracy, and
`gemini-3.5-transcribe` allows 25 requests a day on the free tier and is not
published on Vertex at all — the worst-provisioned model in the system to
depend on at the moment something else has already broken.

---

## Credentials

| | |
|---|---|
| **AI Studio** (default) | `GEMINI_API_KEY`. Simplest. |
| **Vertex AI** | `provider: vertex` plus `GOOGLE_CLOUD_PROJECT` and a service account. Use this to spend Google Cloud credits. |

**The two roles can use different providers**, and usually should:

```yaml
stt:         { provider: aistudio }   # where the streaming model lives
translation: { provider: vertex }     # where the quota and the credits are
```

This is not a hypothetical. The streaming transcription model
`gemini-3.5-transcribe-live` is published on AI Studio and **not** on Vertex, in
any region. Meanwhile AI Studio's free tier allows 15 translation requests per
minute — which one stage in two languages exceeds — while Vertex has no such
cap and is where Google Cloud credits apply. Splitting the roles is what makes
both halves work at once.

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
| `stt.rotate_after_seconds` | `75` | sized against session drift, not the API cap — see below |
| `stt.language_hint` | `true` | materially faster lock-on than auto-detect |
| `stt.commit_sentences` | `true` | translate per sentence instead of per pause |
| `source.loop` | `false` | replay a file forever; each pass starts a fresh session |
| `stt.fallback_enabled` | `true` | degrade rather than go silent |
| `translation.retry_budget_seconds` | `6` | how long a rate-limited line is worth retrying |
| `translation.context_segments` | `3` | previous lines sent for continuity |
| `features.*` | all on | every feature can be switched off |
| `features.catchup_buffer` | `200` | lines a late joiner can scroll back through |

### Why sessions rotate every 75 seconds

The Live API caps a transcription session at 10 minutes, so a talk has to span
several of them. Calandria opens the replacement early and lets both hear the
same three seconds, then stitches the seam, so the audience sees no gap.

The *interval* is set by a different problem. A session answers in real time
when it is young and drifts as it ages. Measured on a live microphone, by the
end of the first minute interim updates were arriving 9 s apart instead of
1.3 s, and captions landed **19.5 s** behind the speaker — on the same phrase
that had been captioned in 1.5 s a minute earlier. Rotating before that sets in
holds the lag flat:

| | rotation 0 | rotation 1 | rotation 2 |
|---|---|---|---|
| source language | 0.1 s | −0.2 to −0.6 s | −0.4 to −0.7 s |
| translated | 1.2 s | 0.4 to 1.0 s | 0.6 to 1.6 s |

Negative means the caption reaches the audience before the audio clock reaches
that point, which is what `commit_sentences` buys: a sentence is released when
the model stops revising it, not when the speaker finally pauses.

Sizing the interval to the API cap instead — the obvious reading, and what an
earlier version did — leaves an audience reading twenty seconds behind the
stage for nine of every ten minutes. The cost of rotating often is the overlap:
two sessions hear the same 3 s each time, so STT audio bills about 4% over the
wall-clock duration rather than 0.6%. On the measured USD 0.65 per stage-hour
that is under three cents.

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

**Stage** — `/capture`. Sends a stage's audio from the browser on the machine
already connected to the sound desk: pick the input, press start, leave the tab
open. A level meter included, because a muted input and a broken pipeline look
identical from anywhere else.

It also captures **another browser tab**, which is how you caption a broadcast
you can only watch rather than pull: a platform behind a login, a webinar, a
player whose stream URL is not yours to have. Share the tab with its audio and
what it plays is what gets captioned — the stream itself is never touched, so a
session cookie, a proprietary embed or DRM make no difference. Measured on a
live conference platform: 1.1–2.0 s to a translated caption.

Only one audio source feeds a stage at a time, and the newest connection wins.
Two tabs pushing into the same stage would mix two copies of the room into one
transcript, which no counter reports — it just quietly gets worse. Newest-wins
rather than refusing the newcomer, because the case that happens at an event is
an operator's laptop dropping its WiFi and coming back.

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

## Running it at your event

[DEPLOYING.md](DEPLOYING.md) is written for whoever owns the stages on the day.
It covers the part that is actually hard — getting audio out of a production
setup you already have — plus a pre-event checklist, what the dashboard is
telling you during a talk, and what to collect afterwards.

The short version: open `/capture` on the laptop already plugged into the sound
desk and press start. No encoder, no RTMP server, nothing to install, and no
CDN between the microphone and the model. For a stage you can only watch in a
browser, share that tab instead — same page, same button.

## Scaling

One process, in-memory bus, is the default. Measured with
`scripts/loadtest.py`: **100 stages and 400 viewer sockets on 18.6% of one
core**, 23 MB per stage, captions reaching a real client 0.8 ms after
publication. The cost per stage stays flat from 20 to 100.

That measures the process. The model's own concurrency is a quota question and
binds long before the machine does.

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

**Apache License 2.0** — [OSI-approved](https://opensource.org/license/apache-2-0),
with an explicit patent grant, which is the reason infrastructure projects tend
to pick it over MIT. Full text in [LICENSE](LICENSE), copyright and third-party
notes in [NOTICE](NOTICE).

Use it, fork it, run it at your event. If you do run it at a conference, an
issue saying how it went would be genuinely useful — most of what is hard here
only shows up on the day.
