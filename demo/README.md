# Demos

Three of them, in the order that makes sense if you have never seen this before.
Each is one command.

---

## 1. No credentials at all — 30 seconds

See the whole system work before deciding whether to create a Google account.

```bash
docker compose --profile demo up demo-offline
```

Then open <http://localhost:8080>. Two stages are running, captions are
flowing, the dashboard is live. Transcription is replayed from a script rather
than a model, so the words are fixed — everything else is real: the fan-out,
the WebSockets, the exports, the cost tracking (correctly reporting zero).

**What to look at:** pick a stage and a language at the top. Then open
<http://localhost:8080/dashboard> in a second tab.

---

## 2. Real conference audio — the one that matters

Six minutes of an actual Nerdearla talk, in English, captioned live and
translated to Spanish.

```bash
./scripts/fetch-talk.sh "https://www.youtube.com/watch?v=GkVjMxYi5gA" \
    samples/talk-real-en.wav 420 360

GEMINI_API_KEY=... docker compose --profile demo up demo-real
```

The talk is not shipped in this repository — a conference recording's licence
does not permit that — so the first command fetches it. It is
*Building Multilingual Conversational AI Agents*, which is a fitting thing to
caption.

**What to look at:** the grey provisional line at the bottom of
<http://localhost:8080>. It appears while the speaker is still talking and
firms up into white when the model settles the sentence. That gap — text
existing before the sentence is finished — is what streaming buys, and it is
visible without any explanation.

Measured on this exact clip: **p50 693 ms**, 80 captions, 80 translations,
**USD 0.065** for the six minutes.

---

## 3. Several stages at once — the scaling claim

Four stages, five language pairs, one process.

```bash
GEMINI_API_KEY=... docker compose --profile demo up demo-scale
```

**What to look at:** <http://localhost:8080/dashboard>. Every stage has its own
latency and its own running cost. Type `10` and `10` into the projection box to
see what a ten-stage, ten-hour conference would cost at the rate being measured
right now.

Four stages is not the limit — it is what fits on screen. Pushing audio into a
live session costs under one percent of a core, so the ceiling on one process
is in the low hundreds. [SCALING.md](../SCALING.md) has the measurements.

---

## Spending credits rather than a card

Transcription must go through AI Studio: the streaming model is published there
and not on Vertex. Translation can go through either, and Vertex is where
Google Cloud credits apply and where there is no 15-request-per-minute cap.

```yaml
stt:         { provider: aistudio }
translation: { provider: vertex }
```

```bash
export GEMINI_API_KEY=...                       # transcription
export GOOGLE_APPLICATION_CREDENTIALS=./sa.json # translation
export GOOGLE_CLOUD_PROJECT=your-project
export GOOGLE_CLOUD_LOCATION=global             # where the newer models live
```

---

## If something is wrong

```bash
docker compose run --rm calandria -c calandria.yaml --check
```

Validates the config, the credentials and every configured model, and prints
the stage list. Run it before an event rather than during one.
