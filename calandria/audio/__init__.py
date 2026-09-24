"""Source selection from config."""

from __future__ import annotations

from .base import SAMPLE_RATE, AudioChunk, AudioSource, bytes_to_seconds, chunk_bytes
from .ffmpeg_source import FFmpegSource, FFmpegUnavailable, file_source, stream_source
from .mic_source import PushSource

__all__ = [
    "SAMPLE_RATE", "AudioChunk", "AudioSource", "bytes_to_seconds", "chunk_bytes",
    "FFmpegSource", "FFmpegUnavailable", "file_source", "stream_source",
    "PushSource", "create_source",
]


def create_source(source_cfg, chunk_ms: int = 100) -> AudioSource:
    if source_cfg.type == "file":
        return file_source(source_cfg.path, chunk_ms=chunk_ms, loop=source_cfg.loop)
    if source_cfg.type == "stream":
        return stream_source(source_cfg.url, chunk_ms=chunk_ms)
    if source_cfg.type == "mic":
        return PushSource()
    raise ValueError(f"unknown source type {source_cfg.type!r}")
