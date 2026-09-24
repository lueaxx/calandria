"""The fallback that keeps an event running when streaming will not.

A live event has no maintenance window. If the streaming session cannot be kept
alive -- a network partition, a regional outage, a quota wall hit at the worst
possible moment -- the honest options are to go dark or to get worse. Going
dark, for the people in the room who are reading these captions because they
cannot hear the speaker, is not an option.

So this backend buffers a few seconds of audio and transcribes it with the
regular request/response model. Latency goes from well under a second to
roughly the buffer length, which is a visible downgrade and a survivable one.
The dashboard shows the session as DEGRADED so the production team knows.
"""

from __future__ import annotations

import asyncio
import io
import logging
import time
import wave
from typing import AsyncIterator

from google import genai
from google.genai import types

from ..audio.base import CHANNELS, SAMPLE_RATE, SAMPLE_WIDTH, AudioChunk
from .base import SttError, SttEvent

log = logging.getLogger("calandria.stt")

PROMPT = (
    "Transcribe this audio verbatim. Output only the transcript text, with no "
    "preamble, no speaker labels and no timestamps. If there is no intelligible "
    "speech, output nothing at all."
)


def pcm_to_wav(pcm: bytes) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(CHANNELS)
        w.setsampwidth(SAMPLE_WIDTH)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm)
    return buf.getvalue()


class ChunkedBackend:
    name = "gemini-chunked"

    def __init__(
        self,
        client: genai.Client,
        *,
        model: str = "gemini-3.5-transcribe",
        language: str | None = None,
        vocabulary: list[str] | None = None,
        window_seconds: float = 4.0,
        on_audio_seconds=None,
    ) -> None:
        self._client = client
        self._model = model
        self._window = window_seconds
        self._on_audio_seconds = on_audio_seconds

        hint = []
        if language:
            hint.append(f"The speaker is using {language}.")
        if vocabulary:
            # Without a biasing API on this path, the glossary goes in the
            # prompt. Less effective than custom_vocabulary, better than nothing.
            hint.append(
                "These terms appear in this talk and must be spelled exactly: "
                + ", ".join(vocabulary[:80])
            )
        self._config = types.GenerateContentConfig(
            system_instruction=" ".join([PROMPT, *hint]),
            temperature=0.0,
        )

    async def transcribe(self, frames: AsyncIterator[AudioChunk]) -> AsyncIterator[SttEvent]:
        buf = bytearray()
        window_start: float | None = None
        window_started_wall = time.monotonic()
        pending: asyncio.Task | None = None

        async for chunk in frames:
            if window_start is None:
                window_start = chunk.ts_start
                window_started_wall = time.monotonic()
            buf.extend(chunk.data)
            if self._on_audio_seconds:
                self._on_audio_seconds(chunk.ts_end - chunk.ts_start)

            if chunk.ts_end - window_start >= self._window:
                if pending is not None:
                    evt = await pending
                    if evt:
                        yield evt
                pending = asyncio.create_task(
                    self._transcribe_window(bytes(buf), chunk.ts_end, window_started_wall)
                )
                buf.clear()
                window_start = None

        if pending is not None:
            evt = await pending
            if evt:
                yield evt
        if buf and window_start is not None:
            evt = await self._transcribe_window(
                bytes(buf), window_start + len(buf) / SAMPLE_WIDTH / SAMPLE_RATE,
                window_started_wall,
            )
            if evt:
                yield evt

    async def _transcribe_window(
        self, pcm: bytes, audio_ts: float, started_wall: float
    ) -> SttEvent | None:
        try:
            response = await self._client.aio.models.generate_content(
                model=self._model,
                contents=[
                    types.Part.from_bytes(data=pcm_to_wav(pcm), mime_type="audio/wav"),
                ],
                config=self._config,
            )
        except Exception as exc:
            raise SttError(f"chunked transcription failed: {exc}") from exc

        text = (response.text or "").strip()
        if not text:
            return None
        return SttEvent(
            text=text,
            is_final=True,
            audio_ts=audio_ts,
            latency_ms=(time.monotonic() - started_wall) * 1000,
        )
