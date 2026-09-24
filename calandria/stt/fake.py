"""A transcription backend that needs no credentials.

Set `stt.backend: fake` and Calandria runs end to end -- ingest, rotation
counters, translation fan-out, viewer, overlay, dashboard, export -- against a
scripted transcript instead of a model. Two reasons this exists and is not a
toy:

  * Anyone evaluating this project can `docker compose up` and watch it work
    before deciding whether to create a Google Cloud account. A demo that
    starts with "first, get an API key" is a demo most people never see.
  * The orchestration can be tested deterministically and for free. Timing bugs
    in a pipeline like this are the expensive kind, and they should not require
    a billing account to reproduce.

The script is replayed against audio time, so captions land in step with the
sample audio rather than as fast as the loop can spin.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import AsyncIterator

from ..audio.base import AudioChunk
from .base import SttEvent

DEFAULT_WPM = 145  # unhurried conference-talk pace
_SENTENCE = re.compile(r"[^.!?]+[.!?]*", re.UNICODE)

PLACEHOLDER = (
    "This is the Calandria demo backend speaking. "
    "No API key is configured, so these captions are scripted rather than "
    "transcribed. Point the configuration at a script file, or set the "
    "transcription backend to Gemini, to caption real audio."
)


class FakeBackend:
    name = "fake"

    def __init__(
        self,
        script: str | Path | None = None,
        *,
        wpm: int = DEFAULT_WPM,
        loop: bool = True,
    ) -> None:
        text = PLACEHOLDER
        if script:
            p = Path(script)
            if p.exists():
                text = p.read_text(encoding="utf-8")
        self._sentences = [s.strip() for s in _SENTENCE.findall(text) if s.strip()]
        self._wpm = wpm
        self._loop = loop

    async def transcribe(self, frames: AsyncIterator[AudioChunk]) -> AsyncIterator[SttEvent]:
        if not self._sentences:
            return
        sec_per_word = 60.0 / self._wpm
        idx = 0
        words = self._sentences[idx].split()
        spoken = 0  # words of the current sentence already "said"
        sentence_start = 0.0
        last_emitted = -1

        async for chunk in frames:
            t = chunk.ts_end
            due = int((t - sentence_start) / sec_per_word)

            if due > spoken and spoken < len(words):
                spoken = min(due, len(words))
                if spoken != last_emitted:
                    last_emitted = spoken
                    yield SttEvent(
                        text=" ".join(words[:spoken]),
                        is_final=False,
                        audio_ts=t,
                        latency_ms=120.0,  # a plausible stand-in, clearly synthetic
                    )

            if spoken >= len(words):
                yield SttEvent(
                    text=self._sentences[idx],
                    is_final=True,
                    audio_ts=t,
                    latency_ms=380.0,
                )
                idx += 1
                if idx >= len(self._sentences):
                    if not self._loop:
                        return
                    idx = 0
                words = self._sentences[idx].split()
                spoken = 0
                last_emitted = -1
                sentence_start = t + 0.4  # a breath between sentences
