"""Configuration: one YAML file describes the whole conference.

Every feature is optional and defaults to something sensible, so a small event
can run on six lines while a large one tunes everything. Validation happens at
load time -- an event operator should find out that two settings conflict when
they start the server, not forty minutes into a keynote.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator


class SourceConfig(BaseModel):
    # 'mic' is the default because it is the only type that needs no further
    # settings: a stage with no configured source is one you push audio to over
    # /ws/ingest. Defaulting to 'file' would make the default value invalid,
    # which turns `POST /api/sessions {"id": "track-3"}` into a puzzle.
    type: Literal["file", "stream", "mic"] = "mic"
    path: str | None = None
    url: str | None = None
    loop: bool = False  # replay a file forever (handy for demos and soak tests)

    @model_validator(mode="after")
    def _check(self):
        if self.type == "file" and not self.path:
            raise ValueError("source.type=file requires 'path'")
        if self.type == "stream" and not self.url:
            raise ValueError("source.type=stream requires 'url'")
        return self


class SessionConfig(BaseModel):
    id: str
    title: str = ""
    source: SourceConfig = Field(default_factory=SourceConfig)
    source_language: str = "en"
    targets: list[str] = Field(default_factory=lambda: ["es"])
    autostart: bool = True

    @model_validator(mode="after")
    def _defaults(self):
        self.title = self.title or self.id
        # Translating a language into itself is a no-op that still costs money.
        self.targets = [t for t in self.targets if t != self.source_language]
        return self


class SttConfig(BaseModel):
    backend: Literal["gemini", "fake"] = "gemini"
    # Overrides the top-level provider for transcription alone. The streaming
    # transcription model is published on AI Studio and not on Vertex, while
    # quota and credits often sit on the other one, so the two roles regularly
    # want different providers.
    provider: Literal["aistudio", "vertex"] | None = None
    model: str = "gemini-3.5-transcribe-live"
    mode: Literal["SMART", "VERBATIM"] = "SMART"
    word_timestamp: bool = False
    language_hint: bool = True
    chunk_ms: int = 100

    # A Live transcription session is capped at 10 minutes by the API. Conference
    # talks are not. We open the replacement early and overlap the two so the
    # audience never sees a gap. See stt/gemini.py.
    rotate_after_seconds: int = 480
    overlap_seconds: float = 3.0

    # The model finalises a segment when it hears end of speech, which on a
    # speaker in full flow can be 15-20 seconds apart, or never. Translation
    # runs on finalised text, so waiting for that marker makes translated
    # captions hostage to how often the speaker pauses. With this on, a sentence
    # the model has moved past is treated as settled. See stt/commit.py.
    commit_sentences: bool = True
    commit_max_words: int = 30  # release a run-on with no punctuation anyway

    # If the streaming backend cannot be kept alive, fall back to chunked
    # transcription rather than going silent. Higher latency, still captions.
    fallback_enabled: bool = True
    fallback_model: str = "gemini-3.5-transcribe"
    fallback_chunk_seconds: float = 4.0

    @model_validator(mode="after")
    def _incompatibilities(self):
        # Verified against the live API: the server closes the socket with
        # code 1007 "Transcription mode SMART is incompatible with word
        # timestamps". Catching it here turns a mid-event disconnect into a
        # startup error message.
        if self.mode == "SMART" and self.word_timestamp:
            raise ValueError(
                "stt.mode=SMART cannot be combined with stt.word_timestamp=true "
                "(the Gemini Live API rejects it with code 1007). "
                "Use mode=VERBATIM if you need word timestamps."
            )
        if self.overlap_seconds >= self.rotate_after_seconds:
            raise ValueError("stt.overlap_seconds must be shorter than rotate_after_seconds")
        return self


class TranslationConfig(BaseModel):
    enabled: bool = True
    provider: Literal["aistudio", "vertex"] | None = None  # see SttConfig.provider
    model: str = "gemini-3.5-flash-lite"
    context_segments: int = 3
    temperature: float = 0.1
    max_concurrent: int = 4  # per session, across all target languages
    # How long to keep retrying a line that hit a rate limit or a capacity
    # blip. Past this the line is stale enough that showing it would confuse a
    # reader more than omitting it.
    retry_budget_seconds: float = 6.0


class FeatureFlags(BaseModel):
    viewer: bool = True
    overlay: bool = True
    dashboard: bool = True
    export: bool = True
    cost_tracking: bool = True
    catchup_buffer: int = 200  # captions kept per session for late joiners; 0 disables


class PricingConfig(BaseModel):
    """USD. Editable because prices change and a stale hardcoded number in a
    dashboard is worse than no number at all."""

    stt_audio_per_min: float = 0.005
    stt_text_per_min: float = 0.004
    mt_input_per_mtok: float = 0.30
    mt_output_per_mtok: float = 2.50


class ServerConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8080


class Config(BaseModel):
    server: ServerConfig = Field(default_factory=ServerConfig)
    provider: Literal["aistudio", "vertex"] = "aistudio"
    bus: str = "memory"
    stt: SttConfig = Field(default_factory=SttConfig)
    translation: TranslationConfig = Field(default_factory=TranslationConfig)
    features: FeatureFlags = Field(default_factory=FeatureFlags)
    pricing: PricingConfig = Field(default_factory=PricingConfig)
    glossary: str | None = None
    transcript_dir: str = "transcripts"
    sessions: list[SessionConfig] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unique_ids(self):
        seen = set()
        for s in self.sessions:
            if s.id in seen:
                raise ValueError(f"duplicate session id: {s.id!r}")
            seen.add(s.id)
        return self

    @classmethod
    def load(cls, path: str | Path | None) -> "Config":
        data: dict = {}
        if path:
            p = Path(path)
            if not p.exists():
                raise FileNotFoundError(f"config file not found: {p}")
            data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        cfg = cls.model_validate(data)
        # Environment always wins, so a container can be retargeted without
        # rewriting the file that is baked into the image.
        if v := os.environ.get("CALANDRIA_PROVIDER"):
            cfg.provider = v  # type: ignore[assignment]
        if v := os.environ.get("CALANDRIA_STT_PROVIDER"):
            cfg.stt.provider = v  # type: ignore[assignment]
        if v := os.environ.get("CALANDRIA_TRANSLATION_PROVIDER"):
            cfg.translation.provider = v  # type: ignore[assignment]
        if v := os.environ.get("CALANDRIA_BUS"):
            cfg.bus = v
        if v := os.environ.get("CALANDRIA_PORT"):
            cfg.server.port = int(v)
        if v := os.environ.get("CALANDRIA_STT_BACKEND"):
            cfg.stt.backend = v  # type: ignore[assignment]
        return cfg
