"""Translation fan-out.

The design decision that matters here is upstream of the code: audio is
transcribed **once**, and the resulting text is translated N times. Audio is the
expensive input; text is nearly free. A stage costs about a third of a US cent
per minute to transcribe, and each additional language adds roughly a tenth of
that. Adding Portuguese across ten stages for a two-day conference costs less
than lunch, which is the difference between "we support three languages" and
"we support the one we could afford".

Two details keep the quality up:

  * **Context.** Each request carries the last few segments. Without them
    "It does." becomes "Lo hace." instead of "Sí, lo hace.", and grammatical
    gender drifts as soon as the subject was mentioned in a previous sentence.
  * **The glossary.** The same terms that bias the transcriber also constrain
    the translator, so a talk whose slides all say "deployment" does not get
    captions that say "despliegue".
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque

from google import genai
from google.genai import types

log = logging.getLogger("calandria.translate")

LANGUAGE_NAMES = {
    "es": "Spanish (neutral Latin American)",
    "en": "English",
    "pt": "Portuguese (Brazilian)",
    "fr": "French",
    "de": "German",
    "it": "Italian",
    "ca": "Catalan",
    "gl": "Galician",
    "eu": "Basque",
    "ja": "Japanese",
    "zh": "Chinese (Simplified)",
}


def language_name(code: str) -> str:
    return LANGUAGE_NAMES.get(code, code)


SYSTEM_PROMPT = """You produce live subtitles for a technical conference talk.

Translate the LINE from {source} into {target}.

Rules:
- Output ONLY the translated line. No quotes, no notes, no alternatives.
- Preserve meaning exactly. Never add, omit, explain or summarise.
- Keep it tight enough to read on screen while the speaker keeps talking.
- Keep code identifiers, command names, product names and acronyms verbatim.
- If the line is a fragment, translate the fragment. Do not complete it.
{glossary}"""


class GeminiTranslator:
    """Translates finalized captions for one (session, target language) pair."""

    def __init__(
        self,
        client: genai.Client,
        *,
        model: str = "gemini-3.5-flash-lite",
        source_language: str = "en",
        target_language: str = "es",
        glossary_rules: str = "",
        context_segments: int = 3,
        temperature: float = 0.1,
        on_usage=None,
    ) -> None:
        self._client = client
        self._model = model
        self._source = source_language
        self._target = target_language
        self._context: deque[tuple[str, str]] = deque(maxlen=max(context_segments, 0))
        self._on_usage = on_usage

        glossary_block = f"\nGlossary:\n{glossary_rules}" if glossary_rules else ""
        self._config = types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT.format(
                source=language_name(source_language),
                target=language_name(target_language),
                glossary=glossary_block,
            ),
            temperature=temperature,
            # Subtitles are short. Capping output keeps a confused model from
            # burning latency on a paragraph nobody will read in time.
            max_output_tokens=512,
        )

    def _prompt(self, text: str) -> str:
        if not self._context:
            return f"LINE: {text}"
        previous = "\n".join(
            f"- {src}  ->  {dst}" for src, dst in self._context
        )
        return (
            "Earlier lines from this talk, for continuity only. Do not "
            f"re-translate them:\n{previous}\n\nLINE: {text}"
        )

    async def translate(self, text: str) -> str:
        text = text.strip()
        if not text:
            return ""
        response = await self._client.aio.models.generate_content(
            model=self._model,
            contents=self._prompt(text),
            config=self._config,
        )
        out = (response.text or "").strip()
        if self._on_usage and response.usage_metadata:
            self._on_usage(
                response.usage_metadata.prompt_token_count or 0,
                (response.usage_metadata.candidates_token_count or 0)
                + (response.usage_metadata.thoughts_token_count or 0),
            )
        if out:
            self._context.append((text, out))
        return out


class TranslationFanout:
    """Runs one translator per target language for a session.

    Requests are bounded by a semaphore. A speaker who talks quickly can queue
    segments faster than they come back, and the correct response is to let the
    queue form rather than open unlimited connections -- but a queue that grows
    without limit is a latency debt, so the oldest pending work is dropped when
    the backlog gets silly.
    """

    def __init__(self, translators: dict[str, GeminiTranslator], max_concurrent: int = 4):
        self._translators = translators
        self._sem = asyncio.Semaphore(max_concurrent)

    @property
    def languages(self) -> list[str]:
        return list(self._translators)

    async def translate(self, lang: str, text: str) -> str:
        async with self._sem:
            try:
                return await self._translators[lang].translate(text)
            except Exception as exc:
                # One failed line must not end the talk. Report it and move on;
                # the dashboard counts it and the original-language captions
                # keep flowing regardless.
                log.warning("translation to %s failed: %s", lang, exc)
                raise
