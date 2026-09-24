"""What the event is spending, while it spends it.

The hardest question to answer about live captioning is not "does it work" but
"can we afford it for ten stages and two days". A running total, visible on the
dashboard, turns that from a procurement argument into an observation.

Transcription is billed against the duration of audio streamed. Translation is
billed against tokens, which the API reports per response, so those are counted
as they arrive rather than estimated.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class Prices:
    stt_audio_per_min: float = 0.005
    stt_text_per_min: float = 0.004
    mt_input_per_mtok: float = 0.30
    mt_output_per_mtok: float = 2.50


@dataclass(slots=True)
class CostTracker:
    prices: Prices = field(default_factory=Prices)
    audio_seconds: float = 0.0
    mt_input_tokens: int = 0
    mt_output_tokens: int = 0

    def add_audio(self, seconds: float) -> None:
        self.audio_seconds += seconds

    def add_translation(self, input_tokens: int, output_tokens: int) -> None:
        self.mt_input_tokens += input_tokens
        self.mt_output_tokens += output_tokens

    @property
    def stt_usd(self) -> float:
        minutes = self.audio_seconds / 60.0
        return minutes * (self.prices.stt_audio_per_min + self.prices.stt_text_per_min)

    @property
    def mt_usd(self) -> float:
        return (
            self.mt_input_tokens / 1e6 * self.prices.mt_input_per_mtok
            + self.mt_output_tokens / 1e6 * self.prices.mt_output_per_mtok
        )

    @property
    def total_usd(self) -> float:
        return self.stt_usd + self.mt_usd

    def project(self, stages: int, hours: float, extra_languages: int) -> dict:
        """Extrapolate this session's observed rates to a whole conference.

        This is the number that decides whether a conference can do captions at
        all, so it is derived from what actually happened rather than a spec
        sheet: measured cost per minute, multiplied out.
        """
        minutes = self.audio_seconds / 60.0 or 1e-9
        stt_per_min = self.stt_usd / minutes
        mt_per_min_per_lang = (self.mt_usd / minutes / max(extra_languages, 1)) if self.mt_usd else 0.0
        total_minutes = stages * hours * 60
        return {
            "stages": stages,
            "hours": hours,
            "languages": extra_languages,
            "stt_usd": round(stt_per_min * total_minutes, 2),
            "mt_usd": round(mt_per_min_per_lang * extra_languages * total_minutes, 2),
            "total_usd": round(
                (stt_per_min + mt_per_min_per_lang * extra_languages) * total_minutes, 2
            ),
        }

    def to_dict(self) -> dict:
        return {
            "audio_seconds": round(self.audio_seconds, 1),
            "stt_usd": round(self.stt_usd, 5),
            "mt_usd": round(self.mt_usd, 5),
            "total_usd": round(self.total_usd, 5),
            "mt_input_tokens": self.mt_input_tokens,
            "mt_output_tokens": self.mt_output_tokens,
        }
