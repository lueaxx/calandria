"""The pub/sub seam.

Calandria's scaling story lives behind this interface. One process serving a
small event uses the in-memory bus; a conference with more stages than one box
can carry sets `bus: redis://...` and runs several replicas. Nothing else in the
codebase changes, because nothing else knows which implementation is loaded.

`subscribe` can replay recent messages before going live. That single parameter
is what lets a viewer who joins mid-talk -- or whose phone dropped the
connection on conference wifi -- read what they just missed instead of staring
at a blank screen until the speaker's next sentence.
"""

from __future__ import annotations

from typing import AsyncIterator, Protocol, runtime_checkable


@runtime_checkable
class Bus(Protocol):
    async def publish(self, topic: str, payload: dict) -> None:
        """Fan `payload` out to every current subscriber of `topic`."""
        ...

    def subscribe(self, topic: str, replay: int = 0) -> AsyncIterator[dict]:
        """Yield messages published to `topic`, newest last.

        If `replay` is greater than zero, up to that many recent messages are
        yielded first. Implementations must never block a publisher on a slow
        subscriber: drop for that subscriber instead.
        """
        ...

    async def close(self) -> None:
        ...
