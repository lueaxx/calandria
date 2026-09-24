"""Generate the repository's sample audio from its scripts, using Gemini TTS.

Why synthesise instead of shipping a recording of a real talk: a conference
recording is rarely licensed in a way that permits redistributing it inside an
Apache-2.0 repository, and a sample file that quietly creates a licensing
problem for everyone who forks the project is a bad sample file.

Synthesising also buys two things a borrowed recording cannot:

  * the transcript is **ground truth**, not an approximation, so accuracy can be
    measured rather than eyeballed;
  * the script can be written to exercise the hard parts on purpose -- product
    names, acronyms, numbers, code identifiers, and the speaker names in the
    glossary.

    python scripts/make_samples.py
"""

from __future__ import annotations

import os
import sys
import wave
from pathlib import Path

from google import genai
from google.genai import types

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "samples"
MODEL = "gemini-3.8-flash-tts"
TTS_RATE = 24_000          # what the TTS model returns
TARGET_RATE = 16_000       # what Calandria ingests

# voice, language, script
SCRIPTS: dict[str, tuple[str, str, str]] = {
    "keynote-en": ("Charon", "en", """\
Good morning everyone, and welcome to the opening keynote of Nerdearla.
Today we are going to talk about what it actually takes to run open source infrastructure at scale.
When you deploy a service to Kubernetes, the hard part was never the container.
The hard part is everything around it: observability, the deployment pipeline, and the on-call rotation at three in the morning.
Let me show you what our architecture looked like eighteen months ago.
We had one PostgreSQL database, one monolith, and a great deal of optimism.
Today we run forty services across three regions, and the thing that saved us was not a framework.
It was writing down what we expected each service to do, and then measuring whether it did that.
Our p99 latency went from two thousand milliseconds to under one hundred and fifty.
The commit that fixed it changed four lines in a connection pool.
"""),
    "charla-es": ("Kore", "es", """\
Buenos días, y gracias por venir a esta charla en Nerdearla.
Vamos a hablar de accesibilidad en eventos técnicos, que es un tema del que se habla poco.
La transcripción en vivo no es una función extra, es la diferencia entre poder seguir una charla o no poder.
En nuestra conferencia tenemos más de treinta sesiones en inglés, muchas en simultáneo.
Las herramientas comerciales funcionan, pero son caras y dependen de operación manual.
Por eso decidimos construir una solución abierta que cualquier conferencia pueda desplegar.
El código está en GitHub con licencia Apache dos punto cero.
Se levanta con un solo comando y corre diez escenarios en paralelo.
"""),
}


def decode(data: bytes, mime_type: str) -> tuple[bytes, int]:
    """Return raw samples and their rate.

    The TTS model returns a complete WAV file, not the bare PCM the docs'
    examples imply. Treating those 44 header bytes as audio puts a click at the
    start of every sample; parsing the container also means the rate is read
    rather than assumed.
    """
    if data[:4] == b"RIFF":
        import io

        with wave.open(io.BytesIO(data), "rb") as w:
            return w.readframes(w.getnframes()), w.getframerate()
    rate = TTS_RATE
    if "rate=" in (mime_type or ""):
        rate = int(mime_type.split("rate=")[1].split(";")[0])
    return data, rate


def to_wav(pcm: bytes, path: Path, rate: int) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)


def resample(pcm: bytes, src: int, dst: int) -> bytes:
    """Cheap linear resample, so this script needs no extra dependency."""
    import array

    samples = array.array("h")
    samples.frombytes(pcm)
    ratio = src / dst
    out = array.array("h", bytes(2 * int(len(samples) / ratio)))
    for i in range(len(out)):
        pos = i * ratio
        lo = int(pos)
        hi = min(lo + 1, len(samples) - 1)
        frac = pos - lo
        out[i] = int(samples[lo] * (1 - frac) + samples[hi] * frac)
    return out.tobytes()


def main() -> int:
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        print("GEMINI_API_KEY is not set. Sample generation needs a key; running "
              "Calandria does not (use stt.backend=fake).", file=sys.stderr)
        return 2

    client = genai.Client(api_key=key)
    SAMPLES.mkdir(exist_ok=True)

    for name, (voice, lang, script) in SCRIPTS.items():
        print(f"Synthesising {name} ({voice}, {lang})…", flush=True)
        response = client.models.generate_content(
            model=MODEL,
            # Only the script, with no delivery note attached. Anything else in
            # here is read out loud and ends up in the audio -- an earlier
            # version opened every sample with "Read this as a conference talk",
            # which then did not match the transcript sitting beside it. The TTS
            # model rejects a system instruction, so the way to keep the audio
            # clean is to send nothing but the words.
            contents=script,
            config=types.GenerateContentConfig(
                response_modalities=["AUDIO"],
                speech_config=types.SpeechConfig(
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice)
                    )
                ),
            ),
        )
        part = response.candidates[0].content.parts[0].inline_data
        pcm, rate = decode(part.data, part.mime_type)
        audio = resample(pcm, rate, TARGET_RATE) if rate != TARGET_RATE else pcm
        to_wav(audio, SAMPLES / f"{name}.wav", TARGET_RATE)
        (SAMPLES / f"{name}.txt").write_text(script, encoding="utf-8")
        seconds = len(audio) / 2 / TARGET_RATE
        print(f"  wrote {name}.wav ({seconds:.1f}s) and {name}.txt")

    print("\nDone. These files are generated, so they carry no third-party rights.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
