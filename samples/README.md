# Sample audio

`keynote-en.wav` is a short English clip with technical vocabulary, and
`keynote-en.txt` is the script the `fake` backend replays against it.

`talk-*.wav` is whatever you fetched with `scripts/fetch-talk.sh` and is
deliberately not tracked, for the reason below.

The tracked samples are deliberately **not** recordings of real conference talks. A talk's
recording is almost never licensed in a way that allows redistributing it inside
an Apache-2.0 repository, and a sample file that quietly creates a licensing
problem for everyone who forks the project is not a good sample file.

To caption a real talk, fetch one locally:

```bash
./scripts/fetch-talk.sh "https://www.youtube.com/watch?v=..." samples/talk.wav 120 300
```

Then point a session at it:

```yaml
sessions:
  - id: talk
    source: { type: file, path: ./samples/talk.wav }
    source_language: en
    targets: [es]
```

## Format

Anything ffmpeg can read works — Calandria converts it. If you want to prepare a
file by hand, the internal format is 16 kHz mono signed 16-bit PCM:

```bash
ffmpeg -i input.mp3 -ac 1 -ar 16000 -sample_fmt s16 output.wav
```
