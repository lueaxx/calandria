"""The whole pipeline, end to end, with no credentials and no network.

This is the test that justifies the `fake` backend existing. Everything between
an audio source and a caption on the bus -- the worker, the queue that lets a
backend be swapped mid-talk, sequence numbering, status, transcript capture --
runs here, deterministically and for free.
"""

import asyncio
import shutil

import pytest

from calandria.audio.base import AudioChunk
from calandria.bus.memory import InMemoryBus
from calandria.config import Config, SessionConfig
from calandria.events import SessionState, topic_captions
from calandria.glossary import Glossary
from calandria.orchestrator import SessionWorker
from calandria.stt.fake import FakeBackend


class ScriptedAudio:
    """Silent audio delivered as fast as the loop will take it.

    The fake backend paces itself against audio timestamps rather than the wall
    clock, so a test can push an hour of "audio" through in milliseconds.
    """

    name = "scripted"

    def __init__(self, seconds: float, chunk: float = 0.1):
        self.seconds = seconds
        self.chunk = chunk

    async def frames(self):
        t = 0.0
        while t < self.seconds:
            yield AudioChunk(data=b"\0" * int(16000 * self.chunk) * 2,
                             ts_start=t, ts_end=t + self.chunk)
            t += self.chunk
            await asyncio.sleep(0)

    async def stop(self):
        pass


async def drive(worker, timeout=15):
    """Run a worker's audio pump and transcription loop together until the
    source is exhausted.

    They are two tasks in production for a reason -- the pump keeps feeding the
    queue while the backend behind it is replaced -- so a test that starts only
    one of them waits forever on a queue nobody fills.
    """
    pump = asyncio.create_task(worker._pump_audio())
    stt = asyncio.create_task(worker._run_stt())
    try:
        await asyncio.wait_for(asyncio.gather(pump, stt), timeout)
    except asyncio.TimeoutError:
        pump.cancel(); stt.cancel()
        raise AssertionError("the pipeline did not finish; it is stuck")


def _worker(bus, tmp_path, targets=(), script=None):
    cfg = Config(
        stt={"backend": "fake"},
        translation={"enabled": False},
        transcript_dir=str(tmp_path),
    )
    session = SessionConfig(id="stage", title="Stage", source_language="en",
                            targets=list(targets))
    w = SessionWorker(session, cfg, bus, Glossary(), client=None)
    w._source = ScriptedAudio(40)
    w._fanout = None
    return w


# --------------------------------------------------------------- the backend

async def test_fake_backend_produces_interims_that_grow_then_a_final():
    backend = FakeBackend(loop=False)
    backend._sentences = ["One two three four five."]
    events = [e async for e in backend.transcribe(ScriptedAudio(6).frames())]

    interims = [e for e in events if not e.is_final]
    finals = [e for e in events if e.is_final]
    assert finals, "a sentence must eventually finalise"
    assert len(interims) > 1, "the sentence should be written progressively"
    # Each interim extends the previous one -- that is the teleprompter effect.
    texts = [e.text for e in interims]
    assert all(b.startswith(a) for a, b in zip(texts, texts[1:]))
    assert finals[0].text == "One two three four five."


async def test_audio_timestamps_advance_monotonically():
    backend = FakeBackend(loop=False)
    events = [e async for e in backend.transcribe(ScriptedAudio(20).frames())]
    stamps = [e.audio_ts for e in events]
    assert stamps == sorted(stamps)


# ---------------------------------------------------------------- the worker

async def test_worker_publishes_captions_to_the_bus(tmp_path):
    bus = InMemoryBus()
    w = _worker(bus, tmp_path)
    await drive(w)

    published = bus.history(topic_captions("stage", "en"))
    assert published, "the stage produced no captions"
    assert any(c["is_final"] for c in published)
    assert all(c["session_id"] == "stage" for c in published)
    assert all(c["origin"] == "stt" for c in published)


async def test_final_captions_are_numbered_in_order(tmp_path):
    bus = InMemoryBus()
    w = _worker(bus, tmp_path)
    await drive(w)
    seqs = [c["seq"] for c in bus.history(topic_captions("stage", "en")) if c["is_final"]]
    assert seqs == sorted(seqs)
    assert len(set(seqs)) == len(seqs), "sequence numbers must be unique"


async def test_an_interim_shares_the_sequence_of_the_final_it_becomes(tmp_path):
    # This is what lets a viewer replace a line in place instead of appending.
    bus = InMemoryBus()
    w = _worker(bus, tmp_path)
    await drive(w)
    msgs = bus.history(topic_captions("stage", "en"))
    first_final = next(i for i, m in enumerate(msgs) if m["is_final"])
    preceding = [m for m in msgs[:first_final] if not m["is_final"]]
    assert preceding, "expected interims before the first final"
    assert preceding[-1]["seq"] == msgs[first_final]["seq"]


async def test_status_tracks_audio_and_caption_counts(tmp_path):
    bus = InMemoryBus()
    w = _worker(bus, tmp_path)
    await drive(w)
    assert w.status.audio_seconds == pytest.approx(40, abs=0.5)
    assert w.status.captions_final > 0
    assert w.status.errors == 0


async def test_transcripts_are_written_when_the_stage_stops(tmp_path):
    bus = InMemoryBus()
    w = _worker(bus, tmp_path)
    await drive(w)
    await w._persist_transcripts()

    out = tmp_path / "stage"
    assert (out / "en.srt").exists() and (out / "en.vtt").exists() and (out / "en.txt").exists()
    srt = (out / "en.srt").read_text(encoding="utf-8")
    assert srt.startswith("1\n") and "-->" in srt
    assert (out / "en.txt").read_text(encoding="utf-8").strip()


async def test_a_stopped_worker_does_not_restart_itself(tmp_path):
    bus = InMemoryBus()
    w = _worker(bus, tmp_path)
    w._stopping = True
    await asyncio.wait_for(w._run_stt(), 5)
    assert w.status.state is SessionState.STOPPED


async def test_the_audio_queue_drops_old_frames_rather_than_stalling(tmp_path):
    """The indirection that lets a backend be replaced mid-talk must not become
    a place where latency accumulates when the model falls behind."""
    bus = InMemoryBus()
    w = _worker(bus, tmp_path)
    w._source = ScriptedAudio(120)      # far more audio than the queue holds
    await w._pump_audio()               # nothing consuming it
    assert w._audio_q.qsize() <= w._audio_q.maxsize


@pytest.mark.skipif(shutil.which("ffmpeg") is None,
                    reason="needs ffmpeg, which decodes every real audio source")
async def test_a_looping_file_marks_where_it_starts_over():
    """A demo that loops its sample must not go silent on the second pass.

    The audience is not the same audience -- whoever just sat down has heard
    none of it -- so the loop boundary has to reach the layer that suppresses
    repeats.
    """
    import wave
    from calandria.audio.ffmpeg_source import file_source

    path = "samples/charla-es.wav"
    with wave.open(path, "rb") as w:
        duration = w.getnframes() / w.getframerate()

    source = file_source(path, chunk_ms=100, loop=True)
    marks, elapsed = [], 0.0
    async for chunk in source.frames():
        if chunk.starts_new_stream:
            marks.append(chunk.ts_start)
        elapsed = chunk.ts_end
        if elapsed > duration + 1.5:
            break
    await source.stop()

    assert marks, "a looping source never signalled that it started over"
    assert abs(marks[0] - duration) < 1.0, f"loop marked at {marks[0]:.1f}s, file is {duration:.1f}s"


def test_the_fallback_reads_the_transcription_part():
    """gemini-3.5-transcribe answers with an `audio_transcription` part, not
    plain text, so reading response.text returns nothing at all -- silently,
    and only on the path that runs when streaming has already failed."""
    from calandria.stt.chunked import _transcript_of

    class Transcription:
        text = "Good morning everyone."

    class Part:
        audio_transcription = Transcription()
        text = None

    class Content:
        parts = [Part()]

    class Candidate:
        content = Content()

    class Response:
        candidates = [Candidate()]
        text = ""          # what the SDK offers, and what used to be read

    assert _transcript_of(Response()) == "Good morning everyone."


def test_the_fallback_still_reads_a_plain_text_response():
    from calandria.stt.chunked import _transcript_of

    class Part:
        audio_transcription = None
        text = "plain"

    class Content:
        parts = [Part()]

    class Candidate:
        content = Content()

    class Response:
        candidates = [Candidate()]
        text = "plain"

    assert _transcript_of(Response()) == "plain"
