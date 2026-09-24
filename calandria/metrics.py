"""Latency percentiles over a sliding window.

A single average over a whole talk hides exactly the thing an operator needs to
see: that the last two minutes got worse. The window is deliberately short so
the dashboard reacts while there is still time to do something about it.
"""

from __future__ import annotations

from collections import deque


class LatencyWindow:
    def __init__(self, size: int = 120) -> None:
        self._samples: deque[float] = deque(maxlen=size)

    def add(self, ms: float) -> None:
        if ms is not None and ms >= 0:
            self._samples.append(ms)

    def _pct(self, p: float) -> float | None:
        if not self._samples:
            return None
        ordered = sorted(self._samples)
        idx = min(int(len(ordered) * p), len(ordered) - 1)
        return ordered[idx]

    @property
    def p50(self) -> float | None:
        return self._pct(0.50)

    @property
    def p95(self) -> float | None:
        return self._pct(0.95)

    @property
    def count(self) -> int:
        return len(self._samples)

    def to_dict(self) -> dict:
        return {"p50": self.p50, "p95": self.p95, "n": self.count}
