"""Single-process bus. The default, and enough for most conferences.

Publishing is non-blocking by construction: each subscriber owns a bounded
queue, and when that queue is full the oldest message is dropped for that
subscriber alone. A phone on bad wifi therefore degrades its own captions and
nobody else's -- a stage must never stall because someone in row 12 has one bar
of signal.
"""

from __future__ import annotations

import asyncio
from collections import deque
from typing import AsyncIterator

QUEUE_MAX = 256


class InMemoryBus:
    def __init__(self, history: int = 200) -> None:
        self._subs: dict[str, set[asyncio.Queue]] = {}
        self._history: dict[str, deque[dict]] = {}
        self._history_max = history
        self._closed = False

    async def publish(self, topic: str, payload: dict) -> None:
        if self._closed:
            return
        if self._history_max:
            h = self._history.setdefault(topic, deque(maxlen=self._history_max))
            h.append(payload)
        for q in tuple(self._subs.get(topic, ())):
            if q.full():
                try:
                    q.get_nowait()  # drop oldest for this subscriber only
                except asyncio.QueueEmpty:
                    pass
            q.put_nowait(payload)

    async def subscribe(self, topic: str, replay: int = 0) -> AsyncIterator[dict]:
        q: asyncio.Queue = asyncio.Queue(maxsize=QUEUE_MAX)
        self._subs.setdefault(topic, set()).add(q)
        try:
            if replay:
                for msg in list(self._history.get(topic, ()))[-replay:]:
                    yield msg
            while not self._closed:
                yield await q.get()
        finally:
            subs = self._subs.get(topic)
            if subs:
                subs.discard(q)
                if not subs:
                    self._subs.pop(topic, None)

    def history(self, topic: str, limit: int = 0) -> list[dict]:
        msgs = list(self._history.get(topic, ()))
        return msgs[-limit:] if limit else msgs

    def clear(self, topic: str) -> None:
        self._history.pop(topic, None)

    async def close(self) -> None:
        self._closed = True
        for subs in self._subs.values():
            for q in subs:
                q.put_nowait({"__closed__": True})
        self._subs.clear()
