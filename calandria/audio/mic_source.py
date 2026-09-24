"""Audio pushed in from outside, over a WebSocket.

Used by the browser capture page, and by anything else that would rather push
PCM at Calandria than have Calandria pull from a URL -- a vMix plugin, a small
agent running on the stage laptop, a test harness.

Since the producer sets the pace, this source never throttles. It also drops
the oldest audio when the queue backs up: for live captions, fresh audio is
worth more than complete audio, and an unbounded queue would simply grow a
latency debt that never gets repaid.
"""

from __future__ import annotations

import asyncio
from typing import AsyncIterator

from .base import AudioChunk, bytes_to_seconds

QUEUE_MAX_CHUNKS = 100  # ~10 s at 100 ms chunks


class PushSource:
    def __init__(self, name: str = "mic") -> None:
        self.name = name
        self._q: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=QUEUE_MAX_CHUNKS)
        self._stopped = False
        self.dropped_chunks = 0

    def push(self, pcm: bytes) -> None:
        """Called by the producer. Never blocks, never raises."""
        if self._stopped:
            return
        if self._q.full():
            try:
                self._q.get_nowait()
                self.dropped_chunks += 1
            except asyncio.QueueEmpty:
                pass
        self._q.put_nowait(pcm)

    async def frames(self) -> AsyncIterator[AudioChunk]:
        emitted = 0.0
        while not self._stopped:
            data = await self._q.get()
            if data is None:
                break
            dur = bytes_to_seconds(len(data))
            yield AudioChunk(data=data, ts_start=emitted, ts_end=emitted + dur)
            emitted += dur

    async def stop(self) -> None:
        self._stopped = True
        await self._q.put(None)
