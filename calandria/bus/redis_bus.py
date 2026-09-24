"""Multi-process bus, for conferences bigger than one box.

Captions go out over Redis pub/sub so any replica can serve any viewer, and a
capped list per topic keeps the catch-up history shared too -- a viewer who
reconnects and lands on a different replica still gets the last few minutes.

`redis` is an optional dependency: it is imported here and nowhere else, so an
install that never sets `bus: redis://...` does not need it.
"""

from __future__ import annotations

import json
from typing import AsyncIterator


class RedisBus:
    def __init__(self, url: str, history: int = 200) -> None:
        try:
            import redis.asyncio as aioredis
        except ImportError as exc:  # pragma: no cover - depends on install extras
            raise RuntimeError(
                "bus is set to Redis but the 'redis' package is not installed. "
                "Install it with:  pip install 'calandria[redis]'"
            ) from exc
        self._redis = aioredis.from_url(url, decode_responses=True)
        self._history_max = history

    @staticmethod
    def _hist_key(topic: str) -> str:
        return f"calandria:hist:{topic}"

    async def publish(self, topic: str, payload: dict) -> None:
        data = json.dumps(payload)
        pipe = self._redis.pipeline()
        pipe.publish(topic, data)
        if self._history_max:
            pipe.rpush(self._hist_key(topic), data)
            pipe.ltrim(self._hist_key(topic), -self._history_max, -1)
            pipe.expire(self._hist_key(topic), 6 * 3600)
        await pipe.execute()

    async def subscribe(self, topic: str, replay: int = 0) -> AsyncIterator[dict]:
        pubsub = self._redis.pubsub()
        await pubsub.subscribe(topic)
        try:
            if replay:
                for raw in await self._redis.lrange(self._hist_key(topic), -replay, -1):
                    yield json.loads(raw)
            async for msg in pubsub.listen():
                if msg.get("type") == "message":
                    yield json.loads(msg["data"])
        finally:
            await pubsub.unsubscribe(topic)
            await pubsub.aclose()

    async def history(self, topic: str, limit: int = 0) -> list[dict]:
        start = -limit if limit else 0
        return [json.loads(r) for r in await self._redis.lrange(self._hist_key(topic), start, -1)]

    async def close(self) -> None:
        await self._redis.aclose()
