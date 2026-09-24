# Demo video: script and shot list

Target: **90 seconds.** The brief allows two minutes; the judges are watching
many of these, and a tight 90 beats a loose 120.

Two of the four judges work in developer experience at Google DeepMind and will
read the repository. One is from Cline and will look at the engineering. The
organiser has this problem for real, next week, on thirty-plus English sessions.
So the video's job is not to prove that transcription is possible. It is to show
**three things nobody else will show**: text that appears while the speaker is
still talking, two stages at once, and the running cost.

> **Pro-tip from the brief worth taking:** some judges do not speak Spanish.
> Caption the video in English **using Calandria itself** — export the SRT from
> `/api/sessions/<id>/transcript.srt?lang=en` and upload it with the video. It
> is the strongest possible demonstration and it costs nothing.

---

## Before recording

```bash
# Real audio from a past Nerdearla talk in English
./scripts/fetch-talk.sh "<youtube-url>" samples/talk-en.wav 180 420
```

Point `keynote` at `samples/talk-en.wav`, leave `sala-2` on `charla-es.wav`,
and start:

```bash
docker compose up
```

Open four tabs and size them before you hit record:

| | |
|---|---|
| 1 | `localhost:8080/?session=keynote&lang=en` |
| 2 | `localhost:8080/?session=keynote&lang=es` |
| 3 | `localhost:8080/dashboard` |
| 4 | `localhost:8080/overlay?session=keynote&lang=es&plate=on` over a video |

Let it run for two or three minutes before recording so the dashboard has a
real cost figure and real percentiles. A demo that starts at `$0.00000` and
`—ms` wastes the two shots that matter most.

---

## Shot list

### 0:00–0:12 — The problem, in one sentence

Over the Nerdearla schedule showing parallel English tracks:

> "Nerdearla has more than thirty talks in English this year, many at the same
> time. Commercial live captioning is priced per stage, so accessibility ends
> up being a budget decision."

### 0:12–0:32 — The thing itself ⭐ *the most important shot*

Tabs 1 and 2 side by side, speaker audible. Do not cut away. Let the viewer
watch the grey provisional line **write itself word by word** and then settle
into white, with the Spanish following a beat later.

> "Calandria captions a live stage in under a second. The grey text is the
> model's running hypothesis — it appears while the speaker is still talking.
> When the sentence settles it turns white, and the translation follows."

Nothing else in this hackathon is likely to look like this. Chunk-based
approaches cannot: their text arrives in blocks, because it cannot exist before
the chunk is complete. **Hold this shot.**

### 0:32–0:45 — Two stages, two directions

Cut to the dashboard.

> "Two stages here — one English talk captioned in Spanish and Portuguese, one
> Spanish talk captioned in English. Adding a stage is five lines of YAML.
> Adding a language is one word."

Hover the latency meter so the tooltip shows p50 and p95 against the
one-second mark.

### 0:45–1:00 — The number that decides it 💰

Stay on the dashboard, move to the spend figure, and **type into the projection
box**: 10 stages, 10 hours.

> "It also tells you what it is spending, as it spends it. At this measured
> rate, ten stages for ten hours in three languages is about sixty dollars for
> the whole conference."

That is the shot the organiser remembers.

### 1:00–1:12 — It survives a real event

> "Live transcription sessions end after ten minutes. Talks do not, so
> Calandria opens the next session early, overlaps them, and stitches the seam
> — the audience sees nothing. If streaming fails entirely it degrades to
> chunked transcription instead of going silent."

Show the rotations counter, or the stage marked `degraded` if you can force it.

### 1:12–1:22 — Where it goes

Quick cuts: the OBS overlay burned over video · a downloaded `.srt` · the phone
view at a large text size.

> "Captions go to a phone, to an OBS overlay, and to an SRT file so the
> recording is subtitled too."

### 1:22–1:30 — Close

Terminal, clean checkout:

```bash
docker compose up
```

> "Apache 2.0. It runs with no API key at all if you just want to look."

---

## What to leave out

The architecture diagram, the module layout, the config reference. They are in
the README, and judges who care will read it. Ninety seconds spent on
architecture is ninety seconds not spent on captions appearing under a
speaker's voice.

## The one thing to get right

If only one shot survives the edit, make it **0:12–0:32**. Sub-second
provisional captions, growing on screen, are the entire technical argument,
and they are self-evident on video in a way no number is.
