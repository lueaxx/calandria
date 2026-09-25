# Demo video: script and shot list

Target: **90 seconds.** The brief allows two minutes; judges watch many of these,
and a tight 90 beats a loose 120.

Two of the four judges do developer experience at Google DeepMind and will read
the repository. One is from Cline and will look at the engineering. The
organiser has this problem for real, next week, across thirty-plus English
sessions.

So the video's job is not to prove transcription is possible. It is to show
**three things nobody else will show**: text appearing while the speaker is
still talking, several stages at once, and the running cost.

> **Worth taking from the brief:** some judges do not speak Spanish. Caption the
> video in English **using Calandria itself** — export the SRT from
> `/api/sessions/<id>/transcript.srt?lang=en` and upload it with the video. It
> is the strongest possible demonstration and costs nothing.

---

## Before recording

```bash
# The real Nerdearla talk used for the measurements below.
./scripts/fetch-talk.sh "https://www.youtube.com/watch?v=GkVjMxYi5gA" \
    samples/talk-real-en.wav 420 360

GEMINI_API_KEY=... docker compose --profile demo up demo-scale
```

Four tabs, sized before recording starts:

| | |
|---|---|
| 1 | `localhost:8080/?session=keynote&lang=en` |
| 2 | `localhost:8080/?session=keynote&lang=es` |
| 3 | `localhost:8080/dashboard` |
| 4 | `localhost:8080/overlay?session=keynote&lang=es&plate=on` over a video |

**Let it run three or four minutes before you hit record.** The dashboard needs
a real cost figure and real percentiles; a demo that opens on `$0.00000` and
`—ms` wastes the two shots that matter most.

---

## Shot list

### 0:00–0:12 — The problem, in one sentence

Over the Nerdearla schedule showing parallel English tracks:

> "Nerdearla has more than thirty talks in English this year, many at the same
> time. Commercial live captioning is priced per stage, so accessibility ends
> up being a budget decision."

### 0:12–0:32 — The thing itself ⭐ *the shot that matters*

Tabs 1 and 2 side by side, speaker audible. **Do not cut away.** Let the viewer
watch the grey provisional line write itself word by word, firm up into white,
and the Spanish follow a beat later.

> "Calandria captions a live stage in under a second. The grey text is the
> model's running hypothesis — it exists before the sentence is finished. When
> it settles it turns white, and the translation follows."

Nothing else in this hackathon is likely to look like this. Chunk-based
approaches cannot: their text arrives in blocks, because it cannot exist before
the chunk is complete. **Hold this shot.**

### 0:32–0:45 — Several stages, both directions

Cut to the dashboard.

> "Four stages here. English talks captioned in Spanish and Portuguese, Spanish
> talks captioned in English. Adding a stage is five lines of YAML. Adding a
> language is one word. We measured a hundred stages on one process, at under a
> fifth of a single core."

Hover a latency meter so the tooltip shows p50 and p95 against the one-second
mark.

### 0:45–1:00 — The number that decides it 💰

Stay on the dashboard, move to the spend figure, and **type into the projection
box**: 10 stages, 10 hours.

> "It also tells you what it is spending, while it spends it. At the rate being
> measured right now, ten stages for ten hours in three languages is about sixty
> dollars for the whole conference."

That is the shot the organiser remembers.

### 1:00–1:12 — It survives a real event

> "A transcription session ends after ten minutes. Talks run forty, so
> Calandria opens the next session early, overlaps them, and stitches the seam
> — the audience sees nothing. If streaming fails entirely it degrades to
> chunked transcription instead of going quiet."

Show the rotations counter, or a stage marked `degraded` if you can force one.

### 1:12–1:22 — Where the captions go

Quick cuts: the OBS overlay burned over video · a downloaded `.srt` · the phone
view at a large text size.

> "Captions go to a phone, to an OBS overlay, and to an SRT file so the
> recording is subtitled too."

### 1:22–1:30 — Close

Terminal, clean checkout:

```bash
docker compose --profile demo up demo-offline
```

> "Apache 2.0. And it runs with no API key at all if you just want to look."

---

## Numbers you can state on camera

All measured, all reproducible from the repository.

| | |
|---|---|
| Latency, speech to caption | **p50 693 ms** on real Nerdearla audio |
| Cost | **USD 0.65** per stage-hour with one extra language |
| Ten stages, ten hours, three languages | **≈ USD 60** |
| Word accuracy | **92.7%** English · **95.4%** Spanish |
| Stages on one process | **100**, with 400 viewers, on 18.6% of one core |
| Tests | 114 |

The accuracy figures come from synthetic samples where the script is ground
truth; say so if you quote them. Latency and cost come from six minutes of a
real talk with an audience, laughter and an accented speaker.

---

## What to leave out

The architecture diagram, the module layout, the config reference. They are in
the README and judges who care will read it. Ninety seconds spent on
architecture is ninety seconds not spent on captions appearing under a
speaker's voice.

## If only one shot survives the edit

Make it **0:12–0:32**. Sub-second provisional captions growing on screen are
the entire technical argument, and they are self-evident on video in a way no
number is.
