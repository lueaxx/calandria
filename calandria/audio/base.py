"""Audio ingestion: many shapes in, one shape out.

A stage can be a file on disk, an RTMP or HLS stream, or a laptop microphone in
the room. Everything downstream should be unable to tell the difference, so
every source yields the same thing: 16 kHz mono 16-bit little-endian PCM, in
fixed-size chunks, each stamped with its position in the session's audio.

That timestamp is not decoration. It is what makes an honest latency number
possible later: when a caption arrives we know precisely which moment of speech
it describes, and when that moment was handed to the model.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import AsyncIterator, Protocol, runtime_checkable

SAMPLE_RATE = 16_000
SAMPLE_WIDTH = 2  # 16-bit
CHANNELS = 1


def chunk_bytes(chunk_ms: int) -> int:
    return int(SAMPLE_RATE * chunk_ms / 1000) * SAMPLE_WIDTH


def bytes_to_seconds(n: int) -> float:
    return n / SAMPLE_WIDTH / SAMPLE_RATE


@dataclass(slots=True)
class AudioChunk:
    data: bytes
    ts_start: float  # seconds into this session's audio
    ts_end: float


@runtime_checkable
class AudioSource(Protocol):
    name: str

    def frames(self) -> AsyncIterator[AudioChunk]:
        """Yield PCM chunks until the source is exhausted or stopped."""
        ...

    async def stop(self) -> None:
        ...
