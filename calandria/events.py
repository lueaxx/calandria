"""The data model.

Everything that moves through Calandria is a Caption. One dataclass, produced
by the STT layer and by the translation layer alike, consumed by viewers, the
OBS overlay, the exporter and the dashboard.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum


class Origin(str, Enum):
    """Where a caption's text came from."""

    STT = "stt"  # transcribed from audio, in the speaker's own language
    MT = "mt"  # machine-translated from an STT caption


class SessionState(str, Enum):
    IDLE = "idle"
    STARTING = "starting"
    RUNNING = "running"
    DEGRADED = "degraded"  # fallback backend in use; captions still flowing
    STOPPED = "stopped"
    FAILED = "failed"


@dataclass(slots=True)
class Caption:
    """One line of subtitle, interim or final.

    `audio_ts` is the position *in the session's audio* that this text covers up
    to. `emitted_at` is when we produced it. The gap between the wall-clock time
    at which `audio_ts` was fed to the model and `emitted_at` is the only honest
    latency number, and it is what `latency_ms` holds. Measuring anything else
    (say, how fast the server pushed bytes to a browser) flatters the system
    without telling the audience how far behind the speaker they are reading.
    """

    session_id: str
    lang: str
    seq: int
    text: str
    is_final: bool
    origin: Origin
    audio_ts: float = 0.0
    emitted_at: float = field(default_factory=time.time)
    latency_ms: float | None = None

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "lang": self.lang,
            "seq": self.seq,
            "text": self.text,
            "is_final": self.is_final,
            "origin": self.origin.value,
            "audio_ts": round(self.audio_ts, 3),
            "emitted_at": self.emitted_at,
            "latency_ms": round(self.latency_ms) if self.latency_ms is not None else None,
        }


@dataclass(slots=True)
class SessionStatus:
    """What the production team sees on the dashboard for one stage."""

    session_id: str
    title: str
    state: SessionState
    source_language: str
    targets: list[str]
    audio_seconds: float = 0.0
    captions_final: int = 0
    rotations: int = 0
    reconnects: int = 0
    dropped_audio: int = 0
    errors: int = 0
    last_error: str | None = None
    backend: str = "gemini-live"
    latency_p50: float | None = None
    latency_p95: float | None = None
    cost_usd: float = 0.0
    started_at: float | None = None

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "title": self.title,
            "state": self.state.value,
            "source_language": self.source_language,
            "targets": list(self.targets),
            "audio_seconds": round(self.audio_seconds, 1),
            "captions_final": self.captions_final,
            "rotations": self.rotations,
            "reconnects": self.reconnects,
            "dropped_audio": self.dropped_audio,
            "errors": self.errors,
            "last_error": self.last_error,
            "backend": self.backend,
            "latency_p50": round(self.latency_p50) if self.latency_p50 else None,
            "latency_p95": round(self.latency_p95) if self.latency_p95 else None,
            "cost_usd": round(self.cost_usd, 4),
            "uptime": round(time.time() - self.started_at, 1) if self.started_at else 0,
        }


def topic_captions(session_id: str, lang: str) -> str:
    return f"captions:{session_id}:{lang}"


TOPIC_STATUS = "status"
