"""Gemini Live streaming transcription, with seamless session rotation.

Three things in here are worth reading before changing anything.

**Rotation.** The API ends a live transcription session after ten minutes. Talks
run forty. So shortly before the deadline we open a second session, feed both
the same audio for a few seconds, then retire the first and de-duplicate the
repeated text at the seam. The audience sees continuous captions; the operator
sees a counter go up.

**Error propagation.** Both halves of a session -- the sender and the receiver --
run inside a TaskGroup, so if either dies the other is cancelled and the real
exception surfaces. This is not tidiness. While building this, a config error
that the server reported clearly as `1007: Transcription mode SMART is
incompatible with word timestamps` reached the logs as an unrelated
`keepalive ping timeout`, because the receiving task's exception was never
observed. Nothing here may swallow a message from the server.

**Latency.** The server reports `audio_offset` on its voice-activity events:
the position in the audio where speech actually ended. Cross-referencing that
with the wall-clock time at which we fed that same position gives the real delay
between someone speaking and the caption existing. It is the number the audience
experiences, and it is the only one this file reports.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from typing import AsyncIterator, Callable

from google import genai
from google.genai import types

from ..audio.base import AudioChunk
from .base import SttError, SttEvent
from .commit import SentenceCommitter
from .dedup import dedup_overlap, tail_words

log = logging.getLogger("calandria.stt")

_SENTINEL = object()

# Send times are kept for this many seconds of audio. Comfortably longer than
# any real transcription delay, short enough that a stale offset finds nothing.
_SEND_TIME_WINDOW_S = 60.0
_SEND_TIME_MEMORY = 900  # entries before pruning is worth the scan


class _LiveSession:
    """One websocket to the transcription model."""

    def __init__(self, client: genai.Client, model: str,
                 config: types.LiveConnectConfig,
                 committer: SentenceCommitter | None = None):
        self._client = client
        self._model = model
        self._config = config
        self.inq: asyncio.Queue = asyncio.Queue(maxsize=200)
        self.outq: asyncio.Queue = asyncio.Queue(maxsize=400)
        self.opened = asyncio.Event()
        self.error: BaseException | None = None
        self.go_away = False
        self.fed_at: dict[float, float] = {}
        self.audio_seconds = 0.0
        # Set when this session is promoted after a rotation: the tail of the
        # retiring session's last final, against which our first final is
        # de-duplicated.
        self.pending_dedup: str = ""
        # A finalized transcript is held here until the server reports where
        # the speech actually ended. See _flush_pending.
        self._pending_final: tuple[str, float] | None = None
        # Releases settled sentences without waiting for the model's own
        # end-of-speech marker. None disables the behaviour entirely.
        self._committer = committer
        # Audio offset where the current speech burst began, kept until the
        # first hypothesis covering it arrives so that 'time to first caption'
        # can be measured for every stage -- including one whose speaker never
        # pauses long enough to produce an end-of-speech marker.
        self._speech_start: float | None = None
        # Where this session sits in the talk. The server's audio offsets are
        # relative to the session, and a session is replaced every few minutes,
        # so after the first rotation its clock restarts at zero while the talk
        # does not. Everything the server reports is shifted by this.
        self.base_offset: float | None = None
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="live-session")

    def forget_shown(self) -> None:
        """Treat what follows as speech the audience has not heard."""
        if self._committer is not None:
            self._committer.forget_history()

    def feed(self, chunk: AudioChunk) -> None:
        if self.inq.full():          # the model is behind; newest audio wins
            with contextlib.suppress(asyncio.QueueEmpty):
                self.inq.get_nowait()
        self.inq.put_nowait(chunk)

    async def aclose(self) -> None:
        self.inq.put_nowait(_SENTINEL)
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task

    async def _run(self) -> None:
        try:
            async with self._client.aio.live.connect(
                model=self._model, config=self._config
            ) as session:
                self.opened.set()
                async with asyncio.TaskGroup() as tg:
                    tg.create_task(self._send(session))
                    tg.create_task(self._recv(session))
        except* Exception as eg:
            self.error = eg.exceptions[0]
            log.warning("live session ended: %s: %s",
                        type(self.error).__name__, self.error)
        finally:
            self.opened.set()  # unblock anyone waiting on a session that failed to open
            with contextlib.suppress(asyncio.QueueFull):
                self.outq.put_nowait(_SENTINEL)

    async def _send(self, session) -> None:
        while True:
            item = await self.inq.get()
            if item is _SENTINEL:
                await session.send_realtime_input(audio_stream_end=True)
                return
            await session.send_realtime_input(
                audio=types.Blob(data=item.data, mime_type="audio/pcm;rate=16000")
            )
            if self.base_offset is None:
                self.base_offset = item.ts_start
            # Keyed by position in the talk, which is what the rest of the
            # system means by a timestamp.
            self.fed_at[round(item.ts_end, 1)] = time.monotonic()
            self.audio_seconds = item.ts_end
            self._forget_old_send_times()

    async def _recv(self, session) -> None:
        try:
            async for response in session.receive():
                now = time.monotonic()

                if response.go_away is not None:
                    # The server is about to close this session. Rotate early
                    # rather than wait for the socket to drop.
                    self.go_away = True

                va = response.voice_activity
                if va is not None and va.audio_offset is not None:
                    kind = getattr(va.voice_activity_type, "name", "")
                    if kind == "ACTIVITY_END":
                        self._flush_pending(self._to_talk_time(va.audio_offset))
                    elif kind == "ACTIVITY_START":
                        self._speech_start = self._to_talk_time(va.audio_offset)

                sc = response.server_content
                if not sc:
                    continue

                interim = sc.interim_input_transcription
                if interim is not None and interim.text:
                    # A new hypothesis means the previous utterance is over and
                    # its end-of-speech marker is not coming.
                    self._flush_pending(None)
                    self._on_hypothesis(interim.text)

                final = sc.input_transcription
                if final is not None and final.text:
                    self._flush_pending(None)
                    self._pending_final = (final.text, now)
        finally:
            self._flush_pending(None)

    def tick(self) -> None:
        """Give the committer a beat even when the model has sent nothing.

        Driven from the audio loop, so it keeps time with the talk rather than
        with the model's mood.
        """
        if self._committer is None:
            return
        settled, tail = self._committer.tick()
        if not settled:
            return  # nothing came due; do not re-push a tail already on screen
        self._push(SttEvent(text=settled, is_final=True,
                            audio_ts=self.audio_seconds, latency_ms=None))
        if tail:
            self._push(SttEvent(text=tail, is_final=False,
                                audio_ts=self.audio_seconds,
                                latency_ms=self._time_to_first_caption()))

    def _on_hypothesis(self, text: str) -> None:
        """Release whatever the running hypothesis has settled, show the rest.

        Waiting for the model's own end-of-speech marker before treating
        anything as final makes translation hostage to how often the speaker
        pauses -- measured at 15 to 20 seconds on a real talk, and never at all
        on continuous speech. Sentences the model has moved past are released
        here instead. See stt/commit.py.
        """
        first_caption_ms = self._time_to_first_caption()

        if self._committer is None:
            self._push(SttEvent(text=text, is_final=False,
                                audio_ts=self.audio_seconds,
                                latency_ms=first_caption_ms))
            return

        settled, tail = self._committer.offer(text)
        if settled:
            # No end-of-speech marker exists for a sentence released this way,
            # so there is no honest latency to attach. Leaving it unset keeps
            # the reported percentiles measurements rather than guesses.
            self._push(SttEvent(
                text=settled, is_final=True, audio_ts=self.audio_seconds, latency_ms=None
            ))
        if tail:
            self._push(SttEvent(text=tail, is_final=False,
                                audio_ts=self.audio_seconds,
                                latency_ms=first_caption_ms))

    def _flush_pending(self, speech_end_offset: float | None) -> None:
        """Release a held final, timing it against where speech really ended.

        The server sends the transcript first and the end-of-speech marker a
        beat later. Holding the transcript for that beat is what makes the
        reported latency the audience's latency: wall-clock now, minus the
        moment we handed over the audio containing the last word. Using the
        marker that arrives *before* a transcript would instead measure the
        length of the sentence, which is not a property of this system at all.
        """
        if self._pending_final is None:
            return
        text, arrived_at = self._pending_final
        self._pending_final = None

        # Most of this utterance has usually been released already; only the
        # part the audience has not seen is new.
        if self._committer is not None:
            text = self._committer.finish(text)
            if not text.strip():
                return

        audio_ts = self.audio_seconds
        latency = None
        if speech_end_offset is not None:
            audio_ts = speech_end_offset
            sent_at = self._fed_at_nearest(speech_end_offset)
            if sent_at is not None:
                latency = max((arrived_at - sent_at) * 1000, 0.0)
        self._push(SttEvent(
            text=text, is_final=True, audio_ts=audio_ts, latency_ms=latency
        ))

    def _to_talk_time(self, audio_offset) -> float | None:
        """Convert a session-relative offset into a position in the talk."""
        offset = _parse_offset(audio_offset)
        if offset is None:
            return None
        return (self.base_offset or 0.0) + offset

    def _time_to_first_caption(self) -> float | None:
        """Wall-clock delay between speech starting and text existing for it.

        Reported once per speech burst. Unlike the end-of-speech measurement it
        does not depend on the speaker pausing, so every stage produces samples
        and an operator can tell a healthy stage from a stalled one.
        """
        if self._speech_start is None:
            return None
        sent_at = self._fed_at_nearest(self._speech_start)
        self._speech_start = None
        if sent_at is None:
            return None
        return max((time.monotonic() - sent_at) * 1000, 0.0)

    def _forget_old_send_times(self) -> None:
        """Keep only recent send times.

        Two reasons, and the second is the one that bites. The map would
        otherwise grow for the length of a talk; and a stale entry turns a
        server offset that refers to audio from a minute ago into a reported
        latency of a minute, which is a measurement of nothing. With few
        samples that single value becomes the p95 and paints a healthy stage
        red. A lookup that finds nothing produces no sample at all, which is
        the honest outcome.
        """
        if len(self.fed_at) <= _SEND_TIME_MEMORY:
            return
        cutoff = self.audio_seconds - _SEND_TIME_WINDOW_S
        self.fed_at = {ts: at for ts, at in self.fed_at.items() if ts >= cutoff}

    def _fed_at_nearest(self, offset: float) -> float | None:
        """When did we hand over the audio at this position?

        Offsets are reported at millisecond resolution while we record one entry
        per chunk, so an exact hit is not guaranteed; accept the closest chunk
        within a chunk's width and give up rather than guess beyond that.
        """
        key = round(offset, 1)
        if (hit := self.fed_at.get(key)) is not None:
            return hit
        for delta in (0.1, -0.1, 0.2, -0.2):
            if (hit := self.fed_at.get(round(key + delta, 1))) is not None:
                return hit
        return None

    def _push(self, evt: SttEvent) -> None:
        if self.outq.full():
            with contextlib.suppress(asyncio.QueueEmpty):
                self.outq.get_nowait()
        self.outq.put_nowait(evt)


def _parse_offset(value) -> float | None:
    """`audio_offset` arrives as a duration string such as '15.080s'."""
    try:
        return float(str(value).rstrip("s"))
    except (TypeError, ValueError):
        return None


class GeminiLiveBackend:
    name = "gemini-live"

    def __init__(
        self,
        client: genai.Client,
        *,
        model: str = "gemini-3.5-transcribe-live",
        mode: str = "SMART",
        word_timestamp: bool = False,
        language: str | None = None,
        vocabulary: list[str] | None = None,
        rotate_after_seconds: float = 480,
        overlap_seconds: float = 3.0,
        commit_sentences: bool = True,
        commit_max_words: int = 30,
        commit_stable_seconds: float = 0.7,
        on_rotate: Callable[[], None] | None = None,
        # Which stage this is. A rotation logged without it is unreadable once
        # more than one stage is running, which is the only case that matters.
        label: str = "",
    ) -> None:
        self._client = client
        self._model = model
        self._rotate_after = rotate_after_seconds
        self._overlap = overlap_seconds
        self._commit = commit_sentences
        self._commit_max_words = commit_max_words
        self._commit_stable = commit_stable_seconds
        self._label = label or "stage"
        self._on_rotate = on_rotate

        fields: dict = {}
        if language:
            # A language hint is not cosmetic: without one the model spends the
            # opening seconds guessing, and the first interim of a talk can come
            # back in the wrong language entirely.
            fields["language_codes"] = [language]
        if vocabulary:
            fields["custom_vocabulary"] = vocabulary
        if mode:
            fields["mode"] = mode
        if word_timestamp:
            fields["word_timestamp"] = True

        self._config = types.LiveConnectConfig(
            response_modalities=["TEXT"],
            input_audio_transcription=types.AudioTranscriptionConfig(**fields),
        )

    def _new_session(self) -> _LiveSession:
        committer = (SentenceCommitter(self._commit_max_words, self._commit_stable)
                     if self._commit else None)
        s = _LiveSession(self._client, self._model, self._config, committer)
        s.start()
        return s

    async def transcribe(self, frames: AsyncIterator[AudioChunk]) -> AsyncIterator[SttEvent]:
        # The session opens on the first chunk, not here. A configured stage
        # that nobody is talking on yet would otherwise hold a socket against
        # the model to carry silence, and a conference configures every room it
        # owns, not only the ones in session. Ten rooms with three talking meant
        # seven live sessions transmitting nothing.
        #
        # That is a quota problem before it is a tidiness one: concurrent Live
        # sessions are capped per project, each rotation briefly needs two, and
        # running out closes them with 1008 "The operation was aborted" -- an
        # error that names nothing you can act on and lands on whichever stage
        # happens to be speaking.
        primary: _LiveSession | None = None
        secondary: _LiveSession | None = None
        rotation_started_at: float | None = None  # audio ts when overlap began
        session_started_ts = 0.0
        last_final_tail = ""

        try:
            async for chunk in frames:
                if primary is None:
                    primary = self._new_session()
                    session_started_ts = chunk.ts_start
                if chunk.starts_new_stream:
                    # The source started over. Clearing what was shown is not
                    # enough on its own: the model's session continues across
                    # the boundary and its hypothesis still carries the previous
                    # pass, which would then be released as one enormous line.
                    # A new pass is a new talk, so it gets a new session --
                    # without the overlap a rotation uses, because there is no
                    # seam to repair here.
                    log.info("[%s] source restarted; beginning a fresh session", self._label)
                    await primary.aclose()
                    if secondary is not None:
                        await secondary.aclose()
                        secondary = None
                        rotation_started_at = None
                    primary = self._new_session()
                    session_started_ts = chunk.ts_start
                    last_final_tail = ""
                primary.feed(chunk)
                if secondary is not None:
                    secondary.feed(chunk)
                # Audio arrives every 100 ms whether or not the model is
                # talking, which makes it the one clock in here that never
                # stops. A sentence that has gone still is released on this
                # beat rather than waiting for the model's next word.
                primary.tick()

                age = chunk.ts_end - session_started_ts
                if secondary is None and (age >= self._rotate_after or primary.go_away):
                    log.info("[%s] rotating live session at %.1fs of audio", self._label, chunk.ts_end)
                    secondary = self._new_session()
                    rotation_started_at = chunk.ts_end

                # Drain whatever the *primary* has produced. The secondary's
                # output is deliberately discarded during the overlap: both are
                # hearing the same words, and showing them twice is exactly the
                # artefact rotation exists to avoid.
                for evt in _drain(primary.outq):
                    if evt is _SENTINEL:
                        continue
                    evt = _apply_pending_dedup(primary, evt)
                    if not evt.text.strip():
                        continue  # the seam consumed it entirely
                    if evt.is_final:
                        last_final_tail = tail_words(evt.text)
                    yield evt

                if (
                    secondary is not None
                    and rotation_started_at is not None
                    and chunk.ts_end - rotation_started_at >= self._overlap
                ):
                    await primary.aclose()
                    for evt in _drain(secondary.outq):
                        pass  # anything buffered mid-overlap was already shown
                    primary, secondary = secondary, None
                    session_started_ts = chunk.ts_end
                    rotation_started_at = None
                    primary.pending_dedup = last_final_tail
                    if self._on_rotate:
                        self._on_rotate()

                if primary.error is not None:
                    raise SttError(str(primary.error)) from primary.error

            # Source exhausted: let the model finalise its tail. A stage that
            # never received audio has no session and so has no tail.
            if primary is None:
                return
            primary.inq.put_nowait(_SENTINEL)
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                try:
                    evt = await asyncio.wait_for(primary.outq.get(), timeout=2)
                except asyncio.TimeoutError:
                    break
                if evt is _SENTINEL:
                    break
                yield _apply_pending_dedup(primary, evt)
            if primary.error is not None:
                raise SttError(str(primary.error)) from primary.error
        finally:
            if primary is not None:
                await primary.aclose()
            if secondary is not None:
                await secondary.aclose()


def _apply_pending_dedup(session: _LiveSession, evt: SttEvent) -> SttEvent:
    """Trim the first final of a freshly promoted session against the seam."""
    pending = session.pending_dedup
    if pending and evt.is_final:
        evt.text = dedup_overlap(pending, evt.text)
        session.pending_dedup = ""
    return evt


def _drain(q: asyncio.Queue) -> list:
    out = []
    while True:
        try:
            out.append(q.get_nowait())
        except asyncio.QueueEmpty:
            return out
