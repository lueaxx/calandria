"""Session lifecycle: audio in, captions out, in every configured language.

One `SessionWorker` per stage. Each owns an audio source, a transcription
backend and a translator per target language, and publishes everything it
produces onto the bus. Workers share nothing but the bus, which is what makes
"run more stages" mean "start more workers" and nothing else.

The audio pump deserves a note. The worker reads its source exactly once and
pushes chunks into a bounded queue that the current backend consumes. That
indirection is what lets the backend be *replaced mid-talk* -- when streaming
fails and the chunked fallback takes over -- without restarting the source,
which for a file would mean replaying the talk from the beginning and for a
live stream would mean losing whatever arrived during the swap.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import time
from pathlib import Path

from google import genai

from .audio import AudioChunk, PushSource, create_source
from .bus import Bus
from .config import Config, SessionConfig
from .cost import CostTracker, Prices
from .events import (
    TOPIC_STATUS,
    Caption,
    Origin,
    SessionState,
    SessionStatus,
    topic_captions,
)
from .glossary import Glossary
from .metrics import LatencyWindow
from .stt.base import SttError
from .stt.chunked import ChunkedBackend
from .stt.fake import FakeBackend
from .stt.gemini import GeminiLiveBackend
from .translate.gemini import GeminiTranslator, TranslationFanout

log = logging.getLogger("calandria")

AUDIO_QUEUE_MAX = 150  # ~15 s at 100 ms chunks
LIVE_FAILURES_BEFORE_FALLBACK = 2


def make_client(cfg: Config) -> genai.Client:
    if cfg.provider == "vertex":
        project = os.environ.get("GOOGLE_CLOUD_PROJECT")
        if not project:
            raise RuntimeError(
                "provider is 'vertex' but GOOGLE_CLOUD_PROJECT is not set. "
                "Vertex is worth the extra setup when you want to spend Google "
                "Cloud credits, which since March 2026 no longer apply to "
                "AI Studio keys."
            )
        return genai.Client(
            vertexai=True,
            project=project,
            location=os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1"),
        )
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not key:
        raise RuntimeError(
            "GEMINI_API_KEY is not set. Get one at https://aistudio.google.com/apikey, "
            "or run with stt.backend=fake to try Calandria without any credentials."
        )
    return genai.Client(api_key=key)


class SessionWorker:
    def __init__(
        self,
        session_cfg: SessionConfig,
        app_cfg: Config,
        bus: Bus,
        glossary: Glossary,
        client: genai.Client | None,
    ) -> None:
        self.cfg = session_cfg
        self.app = app_cfg
        self.bus = bus
        self.glossary = glossary
        self.client = client

        self.status = SessionStatus(
            session_id=session_cfg.id,
            title=session_cfg.title,
            state=SessionState.IDLE,
            source_language=session_cfg.source_language,
            targets=list(session_cfg.targets),
        )
        self.cost = CostTracker(prices=Prices(**app_cfg.pricing.model_dump()))
        self.latency = LatencyWindow()
        self.finals: dict[str, list[dict]] = {}

        self._audio_q: asyncio.Queue[AudioChunk | None] = asyncio.Queue(maxsize=AUDIO_QUEUE_MAX)
        self._seq: dict[str, int] = {}
        self._tasks: list[asyncio.Task] = []
        self._source = None
        self._fanout: TranslationFanout | None = None
        self._live_failures = 0
        self._stopping = False

    # ---------------------------------------------------------------- lifecycle

    async def start(self) -> None:
        if self._tasks:
            return
        self._stopping = False
        self.status.state = SessionState.STARTING
        self.status.started_at = time.time()
        self._source = create_source(self.cfg.source, chunk_ms=self.app.stt.chunk_ms)
        self._fanout = self._build_fanout()
        self._tasks = [
            asyncio.create_task(self._pump_audio(), name=f"pump:{self.cfg.id}"),
            asyncio.create_task(self._run_stt(), name=f"stt:{self.cfg.id}"),
        ]
        await self._publish_status()

    async def stop(self) -> None:
        self._stopping = True
        if self._source is not None:
            await self._source.stop()
        for t in self._tasks:
            t.cancel()
        for t in self._tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await t
        self._tasks.clear()
        with contextlib.suppress(asyncio.QueueFull):
            self._audio_q.put_nowait(None)
        self.status.state = SessionState.STOPPED
        await self._persist_transcripts()
        await self._publish_status()

    @property
    def push_source(self) -> PushSource | None:
        """Exposed so the ingest WebSocket can hand PCM to a mic-backed stage."""
        return self._source if isinstance(self._source, PushSource) else None

    # ------------------------------------------------------------------ plumbing

    def _build_fanout(self) -> TranslationFanout | None:
        if not (self.app.translation.enabled and self.cfg.targets and self.client):
            return None
        rules = self.glossary.translation_rules()
        translators = {
            lang: GeminiTranslator(
                self.client,
                model=self.app.translation.model,
                source_language=self.cfg.source_language,
                target_language=lang,
                glossary_rules=rules,
                context_segments=self.app.translation.context_segments,
                temperature=self.app.translation.temperature,
                on_usage=self.cost.add_translation,
            )
            for lang in self.cfg.targets
        }
        return TranslationFanout(translators, self.app.translation.max_concurrent)

    def _build_backend(self, degraded: bool):
        if self.app.stt.backend == "fake":
            script = None
            if self.cfg.source.type == "file" and self.cfg.source.path:
                candidate = Path(self.cfg.source.path).with_suffix(".txt")
                script = candidate if candidate.exists() else None
            return FakeBackend(script)

        vocab = self.glossary.stt_vocabulary()
        lang = self.cfg.source_language if self.app.stt.language_hint else None
        if degraded:
            return ChunkedBackend(
                self.client,
                model=self.app.stt.fallback_model,
                language=lang,
                vocabulary=vocab,
                window_seconds=self.app.stt.fallback_chunk_seconds,
                on_audio_seconds=self._count_audio,
            )
        return GeminiLiveBackend(
            self.client,
            model=self.app.stt.model,
            mode=self.app.stt.mode,
            word_timestamp=self.app.stt.word_timestamp,
            language=lang,
            vocabulary=vocab,
            rotate_after_seconds=self.app.stt.rotate_after_seconds,
            overlap_seconds=self.app.stt.overlap_seconds,
            on_audio_seconds=self._count_audio,
            on_rotate=self._count_rotation,
        )

    def _count_audio(self, seconds: float) -> None:
        self.status.audio_seconds += seconds
        if self.app.features.cost_tracking:
            self.cost.add_audio(seconds)

    def _count_rotation(self) -> None:
        self.status.rotations += 1

    async def _pump_audio(self) -> None:
        assert self._source is not None
        try:
            async for chunk in self._source.frames():
                if self._audio_q.full():
                    with contextlib.suppress(asyncio.QueueEmpty):
                        self._audio_q.get_nowait()
                self._audio_q.put_nowait(chunk)
        finally:
            with contextlib.suppress(asyncio.QueueFull):
                self._audio_q.put_nowait(None)

    async def _frames(self):
        while True:
            chunk = await self._audio_q.get()
            if chunk is None:
                return
            yield chunk

    # ----------------------------------------------------------------- the loop

    async def _run_stt(self) -> None:
        degraded = self.app.stt.backend != "fake" and self._live_failures >= LIVE_FAILURES_BEFORE_FALLBACK
        while not self._stopping:
            backend = self._build_backend(degraded)
            self.status.backend = backend.name
            self.status.state = SessionState.DEGRADED if degraded else SessionState.RUNNING
            await self._publish_status()
            try:
                async for evt in backend.transcribe(self._frames()):
                    await self._handle_event(evt)
                return  # source exhausted; a finished talk is not an error
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.status.errors += 1
                self.status.last_error = f"{type(exc).__name__}: {exc}"
                log.error("[%s] %s", self.cfg.id, self.status.last_error)
                await self._publish_status()
                if self._stopping:
                    return
                if not degraded:
                    self._live_failures += 1
                    if (
                        self.app.stt.fallback_enabled
                        and self._live_failures >= LIVE_FAILURES_BEFORE_FALLBACK
                    ):
                        log.warning(
                            "[%s] streaming failed %d times; falling back to chunked "
                            "transcription. Captions continue with higher latency.",
                            self.cfg.id, self._live_failures,
                        )
                        degraded = True
                self.status.reconnects += 1
                await asyncio.sleep(min(2 ** self.status.reconnects, 15))
        self.status.state = SessionState.STOPPED
        await self._publish_status()

    async def _handle_event(self, evt) -> None:
        text = evt.text.strip()
        if not text:
            return
        lang = self.cfg.source_language
        caption = Caption(
            session_id=self.cfg.id,
            lang=lang,
            seq=self._next_seq(lang, final=evt.is_final),
            text=text,
            is_final=evt.is_final,
            origin=Origin.STT,
            audio_ts=evt.audio_ts,
            latency_ms=evt.latency_ms,
        )
        await self.bus.publish(topic_captions(self.cfg.id, lang), caption.to_dict())

        if not evt.is_final:
            return

        if evt.latency_ms is not None:
            self.latency.add(evt.latency_ms)
            self.status.latency_p50 = self.latency.p50
            self.status.latency_p95 = self.latency.p95
        self.status.captions_final += 1
        self.status.cost_usd = self.cost.total_usd
        self.finals.setdefault(lang, []).append(caption.to_dict())
        await self._publish_status()

        if self._fanout:
            for target in self._fanout.languages:
                asyncio.create_task(self._translate_and_publish(target, caption))

    async def _translate_and_publish(self, lang: str, source_caption: Caption) -> None:
        try:
            translated = await self._fanout.translate(lang, source_caption.text)
        except Exception:
            self.status.errors += 1
            await self._publish_status()
            return
        if not translated:
            return
        caption = Caption(
            session_id=self.cfg.id,
            lang=lang,
            seq=self._next_seq(lang, final=True),
            text=translated,
            is_final=True,
            origin=Origin.MT,
            audio_ts=source_caption.audio_ts,
            latency_ms=(time.time() - source_caption.emitted_at) * 1000
            + (source_caption.latency_ms or 0),
        )
        self.finals.setdefault(lang, []).append(caption.to_dict())
        self.status.cost_usd = self.cost.total_usd
        await self.bus.publish(topic_captions(self.cfg.id, lang), caption.to_dict())

    def _next_seq(self, lang: str, final: bool) -> int:
        # Interims share the sequence number of the final they will become, so a
        # viewer can replace in place instead of appending a new line per update.
        if final:
            self._seq[lang] = self._seq.get(lang, 0) + 1
        return self._seq.get(lang, 0) + (0 if final else 1)

    async def _publish_status(self) -> None:
        await self.bus.publish(TOPIC_STATUS, self.status.to_dict())

    async def _persist_transcripts(self) -> None:
        if not self.app.features.export or not self.finals:
            return
        out = Path(self.app.transcript_dir) / self.cfg.id
        out.mkdir(parents=True, exist_ok=True)
        from .export import to_srt, to_txt, to_vtt

        for lang, items in self.finals.items():
            (out / f"{lang}.srt").write_text(to_srt(items), encoding="utf-8")
            (out / f"{lang}.vtt").write_text(to_vtt(items), encoding="utf-8")
            (out / f"{lang}.txt").write_text(to_txt(items), encoding="utf-8")
        log.info("[%s] transcripts written to %s", self.cfg.id, out)


class Orchestrator:
    def __init__(self, cfg: Config, bus: Bus) -> None:
        self.cfg = cfg
        self.bus = bus
        self.glossary = Glossary.load(cfg.glossary)
        for warning in self.glossary.warnings():
            log.warning("glossary: %s", warning)
        self.client = None if cfg.stt.backend == "fake" else make_client(cfg)
        self.workers: dict[str, SessionWorker] = {}
        for s in cfg.sessions:
            self.workers[s.id] = SessionWorker(s, cfg, bus, self.glossary, self.client)

    async def start_all(self) -> None:
        for worker in self.workers.values():
            if worker.cfg.autostart:
                await worker.start()

    async def stop_all(self) -> None:
        await asyncio.gather(
            *(w.stop() for w in self.workers.values()), return_exceptions=True
        )

    def add(self, session_cfg: SessionConfig) -> SessionWorker:
        if session_cfg.id in self.workers:
            raise ValueError(f"session {session_cfg.id!r} already exists")
        worker = SessionWorker(session_cfg, self.cfg, self.bus, self.glossary, self.client)
        self.workers[session_cfg.id] = worker
        return worker

    async def remove(self, session_id: str) -> None:
        worker = self.workers.pop(session_id, None)
        if worker:
            await worker.stop()

    def statuses(self) -> list[dict]:
        return [w.status.to_dict() for w in self.workers.values()]

    def totals(self) -> dict:
        total = sum(w.cost.total_usd for w in self.workers.values())
        audio = sum(w.status.audio_seconds for w in self.workers.values())
        running = sum(
            1 for w in self.workers.values()
            if w.status.state in (SessionState.RUNNING, SessionState.DEGRADED)
        )
        return {
            "sessions": len(self.workers),
            "running": running,
            "audio_seconds": round(audio, 1),
            "cost_usd": round(total, 5),
            "cost_per_stage_hour": round(total / (audio / 3600), 4) if audio > 60 else None,
        }
