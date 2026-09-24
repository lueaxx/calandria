"""The speech-to-text seam.

Calandria ships one real backend (Gemini Live) and one that needs no
credentials at all. The interface between them is this file, and it is narrow on
purpose: audio chunks in, caption events out. Anyone who would rather run
Whisper, a local Gemma, or a vendor of their choosing implements `transcribe`
and changes one line of config. Nothing above this layer knows or cares.

Note what an `SttEvent` carries. `audio_ts` is the point in the talk the text
covers up to, and `latency_ms` is measured by the backend, because only the
backend knows when that audio was actually handed over. Latency computed
anywhere else in the stack would be measuring the wrong thing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import AsyncIterator, Protocol, runtime_checkable

from ..audio.base import AudioChunk


@dataclass(slots=True)
class SttEvent:
    text: str
    is_final: bool
    audio_ts: float
    latency_ms: float | None = None
    language: str | None = None


@runtime_checkable
class SttBackend(Protocol):
    name: str

    def transcribe(self, frames: AsyncIterator[AudioChunk]) -> AsyncIterator[SttEvent]:
        """Consume audio, yield interim and final captions as they are produced."""
        ...


class SttError(RuntimeError):
    """Raised when a backend cannot continue.

    Always carries the provider's own message. During a live event the single
    most expensive failure mode is one that cannot be diagnosed from the logs,
    so nothing in this package may swallow an error to keep a loop alive.
    """
