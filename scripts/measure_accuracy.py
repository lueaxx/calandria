"""Measure transcription accuracy against the sample transcripts.

The samples are synthesised from a written script, so that script is ground
truth rather than an approximation. That makes word error rate a real
measurement here, and lets a change to the glossary or the transcription mode be
evaluated instead of argued about.

    python scripts/measure_accuracy.py                 # both samples
    python scripts/measure_accuracy.py keynote-en      # one
    python scripts/measure_accuracy.py --no-glossary   # what the glossary buys
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from google import genai  # noqa: E402

from calandria.audio.base import AudioChunk  # noqa: E402
from calandria.glossary import Glossary  # noqa: E402
from calandria.stt.gemini import GeminiLiveBackend  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "samples"
RATE = 16_000
WORD = re.compile(r"\w+", re.UNICODE)


def normalise(text: str) -> list[str]:
    return [w.casefold() for w in WORD.findall(text)]


def word_error_rate(reference: list[str], hypothesis: list[str]) -> tuple[int, float]:
    """Levenshtein distance over words, divided by the reference length."""
    prev = list(range(len(hypothesis) + 1))
    for i, r in enumerate(reference, 1):
        cur = [i]
        for j, h in enumerate(hypothesis, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (r != h)))
        prev = cur
    edits = prev[-1]
    return edits, edits / max(len(reference), 1)


async def play(path: Path, chunk_ms: int = 100):
    """Feed a file at real time, the way a stage would."""
    import time

    with wave.open(str(path), "rb") as w:
        pcm = w.readframes(w.getnframes())
    size = int(RATE * chunk_ms / 1000) * 2
    start = time.monotonic()
    t = 0.0
    for i in range(0, len(pcm), size):
        data = pcm[i:i + size]
        dur = len(data) / 2 / RATE
        yield AudioChunk(data=data, ts_start=t, ts_end=t + dur)
        t += dur
        await asyncio.sleep(max(t - (time.monotonic() - start), 0))


async def measure(name: str, use_glossary: bool) -> dict:
    wav, txt = SAMPLES / f"{name}.wav", SAMPLES / f"{name}.txt"
    reference = normalise(txt.read_text(encoding="utf-8"))
    language = "es" if name.endswith("-es") else "en"

    glossary = Glossary.load(ROOT / "glossary.yaml") if use_glossary else Glossary()
    backend = GeminiLiveBackend(
        genai.Client(api_key=os.environ["GEMINI_API_KEY"]),
        language=language,
        vocabulary=glossary.stt_vocabulary(),
    )

    finals, latencies = [], []
    async for evt in backend.transcribe(play(wav)):
        if evt.is_final:
            finals.append(evt.text)
            if evt.latency_ms:
                latencies.append(evt.latency_ms)

    hypothesis = normalise(" ".join(finals))
    edits, wer = word_error_rate(reference, hypothesis)
    latencies.sort()
    return {
        "sample": name,
        "glossary": use_glossary,
        "reference_words": len(reference),
        "hypothesis_words": len(hypothesis),
        "edits": edits,
        "wer": wer,
        "accuracy": 1 - wer,
        "p50": latencies[len(latencies) // 2] if latencies else None,
        "p95": latencies[int(len(latencies) * 0.95)] if latencies else None,
        "text": " ".join(finals),
    }


async def main() -> int:
    if not os.environ.get("GEMINI_API_KEY"):
        print("GEMINI_API_KEY is not set.", file=sys.stderr)
        return 2

    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    use_glossary = "--no-glossary" not in sys.argv
    names = args or [p.stem for p in sorted(SAMPLES.glob("*.wav"))]

    print(f"{'sample':<14} {'glossary':<9} {'words':>6} {'edits':>6} "
          f"{'WER':>7} {'accuracy':>9} {'p50':>7} {'p95':>7}")
    print("-" * 72)
    for name in names:
        r = await measure(name, use_glossary)
        print(f"{r['sample']:<14} {str(r['glossary']):<9} {r['reference_words']:>6} "
              f"{r['edits']:>6} {r['wer']:>6.1%} {r['accuracy']:>8.1%} "
              f"{(r['p50'] or 0):>6.0f}ms {(r['p95'] or 0):>6.0f}ms")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
