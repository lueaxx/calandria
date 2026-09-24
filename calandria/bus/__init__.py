"""Bus selection: `memory` or any `redis://` URL."""

from __future__ import annotations

from .base import Bus
from .memory import InMemoryBus

__all__ = ["Bus", "InMemoryBus", "create_bus"]


def create_bus(spec: str, history: int = 200) -> Bus:
    if spec in ("memory", "", "inmemory"):
        return InMemoryBus(history=history)
    if spec.startswith(("redis://", "rediss://", "unix://")):
        from .redis_bus import RedisBus

        return RedisBus(spec, history=history)
    raise ValueError(f"unknown bus {spec!r}; use 'memory' or a redis:// URL")
