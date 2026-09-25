# Deploying Calandria at a conference

Written for whoever is responsible for the stages on the day. It assumes you
have a production setup already — a sound desk, probably OBS, maybe an encoder
— and that Calandria has to fit into it rather than replace any of it.

The hard part is not running the software. It is **getting audio out of what
you already have**, so that is most of this document.

---

## 1. Getting the audio in

Four ways, in the order you should consider them. The difference between them
is mostly latency, and latency is the whole point.

### A. Push from the stage laptop — recommended

Open `http://your-server:8080/capture` on the machine already plugged into the
sound desk, pick the input, press start, leave the tab open.

```yaml
sessions:
  - id: keynote
    title: "Main stage"
    source: { type: mic }        # the page pushes to /ws/ingest
    source_language: en
    targets: [es, pt]
```

Nothing to install, no encoder, no RTMP server — and **no CDN between the
microphone and the model**, which is what keeps the delay under a second. The
page shows a level meter, because the most common failure at an event is a
perfectly healthy pipeline fed by a muted input.

Its one weakness is that it depends on a tab staying open. Put it on the
machine that is already running the stage, not on somebody's laptop.

### B. Pull from your encoder over RTMP or SRT

If stages already publish to a local media server (MediaMTX, nginx-rtmp),
point Calandria at it:

```yaml
source: { type: stream, url: "rtmp://media.local/live/stage-1" }
```

ffmpeg reconnects on its own if the feed blips. Latency is a little higher
than pushing, and still well inside what the rest of the system is built for.

### C. Pull from the public stream — works, but read this first

```yaml
source: { type: stream, url: "https://.../playlist.m3u8" }
```

This is the easiest to set up and **the worst choice for latency**. A public
HLS stream is 10 to 30 seconds behind the room, because that is what HLS
segmenting and CDN distribution cost. Calandria will add its 700 ms on top and
the audience will read captions half a minute after the speaker.

Use it to caption a recording, or when nothing else is possible. Do not use it
for a room that has people in it, and do not measure the system this way.

### D. A file

For rehearsal and for measuring:

```yaml
source: { type: file, path: ./samples/keynote-en.wav, loop: true }
```

Played back at real time, so it behaves like a stage. `loop: true` starts a
fresh session each pass, which is what makes it useful for a demo that has to
run all day.

---

## 2. Where to run it

One container. `docker compose up`.

| Stages | Shape |
|---|---|
| Up to ~20 | 2 vCPU, 2 GB. Anything, including a laptop under the desk. |
| Up to ~100 | 4 vCPU, 4 GB. Measured: 100 stages on 18.6% of one core, 2.3 GB. |
| Beyond that | `bus: redis://…` and several replicas. [SCALING.md](SCALING.md). |

Put it **on the same network as the stages**, not in another region. Audio
travels to it, and every hop is latency you cannot get back.

For an event where captions are an accessibility commitment rather than a
nice-to-have, run two replicas behind a load balancer so a crash costs a
reconnect instead of a talk.

---

## 3. Before the doors open

```bash
docker compose run --rm calandria -c calandria.yaml --check
```

Validates the config, the credentials and every configured model, and prints
the stage list. Failing at 8am is free.

**Also do these**, in rough order of how much trouble they save:

- [ ] **Attach billing to your API key.** The free tier allows 15 translation
      requests per minute across the whole project, which one stage in two
      languages exceeds. The symptom is misleading: original-language captions
      look perfect while translations arrive with holes.
- [ ] **Write the glossary.** Speaker names, sponsor names, product names, and
      the terms your talks will not stop saying. One file,
      [`glossary.example.yaml`](glossary.example.yaml) shows the shape. It is
      the cheapest quality improvement available.
- [ ] **Rehearse one stage end to end**, with the real audio path, at least a
      day before. Not a file — the actual desk.
- [ ] **Check the level meter** on `/capture`, or the caption flow on
      `/dashboard`, for every stage.
- [ ] **Print the QR codes** for the audience page, one per stage:
      `/?session=<id>`. The page remembers the stage and language.

---

## 4. During the event

Watch `/dashboard`. It is built to be read from across a room.

| What you see | What it means |
|---|---|
| Green dot, latency under the 1 s mark | The room is keeping up with the speaker. |
| **degraded** | Streaming failed; the chunked fallback is carrying it. Captions continue with worse latency. Worth looking at, not worth panicking about. |
| Errors climbing | Usually rate limits. Check the log for `429`. |
| Audio dropped above zero | The transcriber is behind. Every dropped chunk is speech nobody will read. |
| Rotations climbing | Normal. One every eight minutes per stage is expected. |

The spend figure is live, and the projection box extrapolates the rate you are
actually paying to any number of stages and hours.

**If a stage goes quiet:** check the level meter first. A muted input looks
exactly like a broken pipeline from the dashboard, and it is far more common.

---

## 5. Putting captions in front of people

| Where | How |
|---|---|
| Phones in the room | `/?session=<id>` — a QR code per stage |
| The stream | `/overlay?session=<id>&lang=es&plate=on` as an OBS or vMix browser source |
| The recording | `/api/sessions/<id>/transcript.srt?lang=es` when the talk ends |

Transcripts are also written to `transcript_dir` automatically when a session
stops, in every language the stage ran.

---

## 6. After

Collect `transcripts/`. Every talk, every language, as SRT, VTT and plain text.
Upload the SRT with the recording and the archive is accessible too.

---

## Choosing the models and where they run

Transcription and translation can use different providers, and usually should:

```yaml
stt:         { provider: aistudio }   # the streaming model is published here
translation: { provider: vertex }     # quota and Google Cloud credits are here
```

`gemini-3.5-transcribe-live` is available on AI Studio and not on Vertex, in
any region. Translation is on both. AI Studio's free tier caps translation at
15 requests per minute; Vertex does not, and Google Cloud credits apply there
and not to AI Studio.

To use a different vendor entirely, implement `SttBackend` — one method, in
[`calandria/stt/base.py`](calandria/stt/base.py) — and set `stt.backend`. The
`fake` backend is a 40-line worked example. Nothing above that layer knows
which one is loaded.

---

## If you run this at your event

An issue saying how it went would be genuinely useful. Most of what is hard
here only shows up on the day, and the next conference benefits from what
yours found.
