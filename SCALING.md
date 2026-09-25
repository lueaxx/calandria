# Scaling Calandria

Short version: **one process handles more stages than most conferences have.**
Reach for Redis when you need redundancy or more audience than one box can hold
sockets for, not because you added a stage.

## Measured: 100 stages and 400 viewers, one process

```
python scripts/loadtest.py --stages 100 --viewers 400
```

| | |
|---|---|
| stages | **100** |
| viewer WebSockets | **400** (37,196 captions delivered) |
| CPU | **18.6% of one core** — 0.8% of a 24-core machine |
| memory, whole tree | 2.3 GB |
| publish → viewer | **p50 0.8 ms · p95 2.3 ms** |
| per stage | **0.19% of a core · 23 MB** |

The cost per stage holds steady as the count rises, which is the property that
matters:

| stages | CPU per stage | memory per stage |
|---|---|---|
| 20 | 0.23% | 26 MB |
| 50 | 0.29% | 24 MB |
| 100 | 0.19% | 23 MB |

**What this measures, and what it does not.** The load test runs the `fake`
transcription backend, so it costs nothing and needs no credentials, and it
measures *the process*: decoding audio, moving captions through the bus, and
serving sockets. It does not measure the model's own concurrency — that is a
quota question, answered by your API tier, and in practice it binds long before
this machine does. Plan for the quota; the process is not your problem.

## What a stage actually costs a process

Measured against the live API, pushing audio into a transcription session:

| Chunk size | Serialize | Send | CPU to push 1 s of audio |
|---|---|---|---|
| 100 ms | 0.01 ms | 0.77 ms | **0.8%** |
| 200 ms | 0.04 ms | 0.64 ms | 0.3% |
| 500 ms | 0.09 ms | 1.22 ms | 0.3% |

At the 100 ms default a stage occupies under one percent of a core for ingest.
Decoding in ffmpeg runs in its own process, and the model does the work that
matters. The practical ceiling on one event loop is in the low hundreds of
stages, which is well past the point where you want redundancy for other reasons.

Real-time pacing holds under load. Replaying files through the deadline-based
pacer drifts **+0.00 s over 20 s with ten concurrent sessions**, even though
individual `asyncio.sleep` calls on the test machine overshoot by 9–15 ms —
each sleep is computed against the session start, so an overshoot is absorbed by
the next one instead of accumulating.

## Where the real limits are

**API quota, not CPU.** Free-tier keys throttle concurrent live sessions hard.
Attach a billing account for Tier 1 before an event, and run `--check` on the
day.

**Audience sockets.** Each viewer holds one websocket. A single uvicorn process
serves thousands, but that is the number that grows with attendance rather than
with the schedule, and it is the usual reason to add replicas.

**Redundancy.** One process is one failure domain. For an event where captions
are an accessibility commitment rather than a nice-to-have, run at least two
replicas so a crash costs a reconnect rather than the talk.

## Scaling out

```yaml
bus: redis://redis:6379
```

or `CALANDRIA_BUS=redis://redis:6379`. Then:

```bash
docker compose --profile scale up
```

What changes: captions and status are published to Redis instead of an in-process
registry, and the catch-up history lives in a capped Redis list per topic. Any
replica can serve any viewer, so a phone that reconnects through a load balancer
does not care where it lands.

What does not change: a single line of application code. The bus is one
interface with two implementations (`calandria/bus/`).

### Splitting stages across replicas

Each replica runs the stages in *its* config. The simplest arrangement is to
give each replica a different `sessions:` list and put every replica behind one
load balancer — viewers reach any of them, because captions travel over Redis.

```yaml
# replica-a.yaml
bus: redis://redis:6379
sessions: [{ id: keynote, ... }, { id: track-2, ... }]

# replica-b.yaml
bus: redis://redis:6379
sessions: [{ id: track-3, ... }, { id: track-4, ... }]
```

No coordination protocol, no leader election, nothing to go wrong at 9am. If you
want stages assigned dynamically instead, the REST API creates and destroys
sessions at runtime (`POST /api/sessions`), so an external scheduler can place
them.

## A worked example: ten stages, two days

```
10 stages × 10 hours          = 100 stage-hours
transcription  100 h × $0.54  = $54
Spanish        100 h × $0.04  = $4
Portuguese     100 h × $0.04  = $4
                                ----
                                $62
```

Hardware: **one container**, 2 vCPU and 2 GB is comfortable. Add a second for
redundancy. `/dashboard` shows the real figure accumulating, and its projection
box extrapolates from the rate you are actually paying rather than from this
table.

## Operating it on the day

- Run `--check` before doors open. It validates the config, the credentials and
  every configured model, and prints the stage list. Failing at 8am is free.
- Watch `/dashboard`. A stage marked **degraded** is still captioning, on the
  chunked fallback, with worse latency — worth investigating, not worth
  panicking about.
- The latency meter's hairline is one second. Green means the audience is
  keeping up with the speaker.
- Transcripts are written to `transcript_dir` when a session stops, in every
  language. That is the subtitle track for the recording.
