"""ffmpeg-backed sources: any file, any stream.

ffmpeg does the decoding -- mp3, m4a, wav, RTMP, HLS, a YouTube URL piped in --
and hands us raw PCM on stdout. Calandria does the pacing, and that split is
deliberate: a *file* must be throttled to real time so it behaves like a stage,
while a *live stream* already arrives in real time and throttling it again would
put us permanently behind the speaker. `ffmpeg -re` cannot tell those two cases
apart; we can.
"""

from __future__ import annotations

import asyncio
import shutil
import time
from typing import AsyncIterator

from .base import SAMPLE_RATE, AudioChunk, bytes_to_seconds, chunk_bytes


class FFmpegUnavailable(RuntimeError):
    pass


def ffmpeg_path() -> str:
    exe = shutil.which("ffmpeg")
    if not exe:
        raise FFmpegUnavailable(
            "ffmpeg was not found on PATH. It decodes every audio source "
            "Calandria accepts. Install it (apt install ffmpeg / brew install "
            "ffmpeg / winget install Gyan.FFmpeg) or use the bundled Docker image."
        )
    return exe


class FFmpegSource:
    """Decode `target` to PCM. Paces to real time when `realtime` is set."""

    def __init__(
        self,
        target: str,
        *,
        realtime: bool,
        chunk_ms: int = 100,
        loop: bool = False,
        name: str = "ffmpeg",
        extra_input_args: tuple[str, ...] = (),
    ) -> None:
        self.target = target
        self.realtime = realtime
        self.chunk_ms = chunk_ms
        self.loop = loop
        self.name = name
        self.extra_input_args = extra_input_args
        self._proc: asyncio.subprocess.Process | None = None
        self._stopped = False

    def _args(self) -> list[str]:
        return [
            ffmpeg_path(),
            "-hide_banner",
            "-loglevel", "error",
            "-nostdin",
            *self.extra_input_args,
            "-i", self.target,
            "-vn",
            "-f", "s16le",
            "-acodec", "pcm_s16le",
            "-ar", str(SAMPLE_RATE),
            "-ac", "1",
            "pipe:1",
        ]

    async def frames(self) -> AsyncIterator[AudioChunk]:
        size = chunk_bytes(self.chunk_ms)
        emitted = 0.0
        started = time.monotonic()
        pass_number = 0

        while not self._stopped:
            pass_number += 1
            first_of_pass = True
            self._proc = await asyncio.create_subprocess_exec(
                *self._args(),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            assert self._proc.stdout is not None
            while not self._stopped:
                data = await _read_exactly(self._proc.stdout, size)
                if not data:
                    break
                dur = bytes_to_seconds(len(data))
                yield AudioChunk(
                    data=data, ts_start=emitted, ts_end=emitted + dur,
                    starts_new_stream=first_of_pass and pass_number > 1,
                )
                first_of_pass = False
                emitted += dur

                if self.realtime:
                    # Absolute-deadline pacing: each sleep is computed against
                    # the session start, so an overshooting sleep is corrected
                    # by the next one instead of accumulating drift.
                    behind = emitted - (time.monotonic() - started)
                    await asyncio.sleep(max(behind, 0))
                else:
                    await asyncio.sleep(0)  # stay cooperative

            await self._terminate()
            if not self.loop or self._stopped:
                break

    async def _terminate(self) -> None:
        proc, self._proc = self._proc, None
        if proc and proc.returncode is None:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=3)
            except asyncio.TimeoutError:
                proc.kill()

    async def stop(self) -> None:
        self._stopped = True
        await self._terminate()


async def _read_exactly(stream: asyncio.StreamReader, n: int) -> bytes:
    """Read exactly n bytes, or fewer at end of stream (never raises)."""
    buf = bytearray()
    while len(buf) < n:
        part = await stream.read(n - len(buf))
        if not part:
            break
        buf.extend(part)
    return bytes(buf)


def file_source(path: str, chunk_ms: int = 100, loop: bool = False) -> FFmpegSource:
    return FFmpegSource(path, realtime=True, chunk_ms=chunk_ms, loop=loop, name=f"file:{path}")


def stream_source(url: str, chunk_ms: int = 100) -> FFmpegSource:
    return FFmpegSource(
        url,
        realtime=False,
        chunk_ms=chunk_ms,
        name=f"stream:{url}",
        # Keep reconnecting: a stage feed that blips should not end the session.
        extra_input_args=(
            "-reconnect", "1",
            "-reconnect_streamed", "1",
            "-reconnect_delay_max", "10",
        ),
    )
