"""Speech-to-text backends."""

from .base import SttBackend, SttError, SttEvent
from .chunked import ChunkedBackend
from .dedup import dedup_overlap
from .fake import FakeBackend
from .gemini import GeminiLiveBackend

__all__ = [
    "SttBackend", "SttError", "SttEvent",
    "GeminiLiveBackend", "ChunkedBackend", "FakeBackend", "dedup_overlap",
]
