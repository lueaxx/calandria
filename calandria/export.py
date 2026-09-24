"""Transcript export: SRT, WebVTT, plain text, JSON.

Captioning a talk live and then throwing the text away is a waste. The same
segments that were on screen become the subtitle track for the recording, so
the archived video is accessible too -- in every language the event ran.

Timings come from `audio_ts`, the position in the talk's own audio, which makes
the exported file line up with the recording rather than with whenever the
captioning process happened to start.
"""

from __future__ import annotations

from dataclasses import dataclass

MIN_CUE_SECONDS = 1.2
MAX_CUE_SECONDS = 7.0


@dataclass(slots=True)
class Cue:
    start: float
    end: float
    text: str


def _timestamp(seconds: float, comma: bool) -> str:
    seconds = max(seconds, 0.0)
    h, rem = divmod(int(seconds), 3600)
    m, s = divmod(rem, 60)
    ms = int(round((seconds - int(seconds)) * 1000))
    if ms == 1000:  # rounding can carry
        s, ms = s + 1, 0
    sep = "," if comma else "."
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def build_cues(finals: list[dict]) -> list[Cue]:
    """Turn finalized captions into cues with sane, non-overlapping timings.

    Each caption knows where it *ended* in the audio but not where it began, so
    a cue starts where the previous one ended and is clamped to a readable
    duration.
    """
    cues: list[Cue] = []
    previous_end = 0.0
    for item in finals:
        text = (item.get("text") or "").strip()
        if not text:
            continue
        end = float(item.get("audio_ts") or 0.0)
        start = previous_end
        if end <= start:
            end = start + MIN_CUE_SECONDS
        if end - start > MAX_CUE_SECONDS:
            start = end - MAX_CUE_SECONDS
        cues.append(Cue(start=start, end=end, text=text))
        previous_end = end
    return cues


def to_srt(finals: list[dict]) -> str:
    out = []
    for i, c in enumerate(build_cues(finals), start=1):
        out.append(
            f"{i}\n{_timestamp(c.start, True)} --> {_timestamp(c.end, True)}\n{c.text}\n"
        )
    return "\n".join(out)


def to_vtt(finals: list[dict]) -> str:
    out = ["WEBVTT", ""]
    for c in build_cues(finals):
        out.append(f"{_timestamp(c.start, False)} --> {_timestamp(c.end, False)}")
        out.append(c.text)
        out.append("")
    return "\n".join(out)


def to_txt(finals: list[dict]) -> str:
    return "\n".join((f.get("text") or "").strip() for f in finals if (f.get("text") or "").strip())


FORMATS = {"srt": to_srt, "vtt": to_vtt, "txt": to_txt}
MEDIA_TYPES = {
    "srt": "application/x-subrip",
    "vtt": "text/vtt",
    "txt": "text/plain; charset=utf-8",
    "json": "application/json",
}
