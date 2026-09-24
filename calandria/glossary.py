"""One glossary file, two jobs.

A conference glossary is the cheapest quality win available. The same list of
words does duty twice:

  * as `custom_vocabulary` on the transcription model, so "Kubernetes" does not
    come back as "cooper netties";
  * as instructions to the translator, so "deployment" is not helpfully
    rendered as "despliegue" halfway through a talk where every slide says
    "deployment".

Keeping them in one file means the operator maintains one list, and the two
halves of the pipeline cannot drift apart.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

# The transcription API accepts up to 1000 biasing terms, but quality is best
# with far fewer -- a long list dilutes the bias. Warn rather than truncate
# silently, so the operator knows their 400-name speaker list is doing nothing.
VOCAB_HARD_LIMIT = 1000
VOCAB_SOFT_LIMIT = 150


@dataclass(slots=True)
class Glossary:
    terms: list[str] = field(default_factory=list)
    keep_untranslated: list[str] = field(default_factory=list)
    force: dict[str, str] = field(default_factory=dict)
    speakers: list[str] = field(default_factory=list)

    @classmethod
    def load(cls, path: str | Path | None) -> "Glossary":
        if not path:
            return cls()
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"glossary file not found: {p}")
        d = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        return cls(
            terms=list(d.get("terms") or []),
            keep_untranslated=list(d.get("keep_untranslated") or []),
            force=dict(d.get("force") or {}),
            speakers=list(d.get("speakers") or []),
        )

    def stt_vocabulary(self) -> list[str]:
        """Biasing terms for the transcription model, de-duplicated, order kept."""
        seen: set[str] = set()
        out: list[str] = []
        for word in (*self.terms, *self.speakers, *self.keep_untranslated, *self.force):
            key = word.casefold()
            if word and key not in seen:
                seen.add(key)
                out.append(word)
        return out[:VOCAB_HARD_LIMIT]

    def warnings(self) -> list[str]:
        n = len(self.stt_vocabulary())
        out = []
        if n > VOCAB_HARD_LIMIT:
            out.append(f"glossary has {n} terms; only the first {VOCAB_HARD_LIMIT} are sent")
        elif n > VOCAB_SOFT_LIMIT:
            out.append(
                f"glossary has {n} terms; recognition quality is usually best "
                f"under {VOCAB_SOFT_LIMIT}, consider trimming rare ones"
            )
        return out

    def translation_rules(self) -> str:
        """A prompt fragment. Empty when there is nothing to say, so we do not
        spend tokens on an empty heading every single segment."""
        parts: list[str] = []
        if self.keep_untranslated:
            parts.append(
                "Leave these exactly as they appear, untranslated: "
                + ", ".join(sorted(self.keep_untranslated))
            )
        if self.force:
            pairs = ", ".join(f'"{k}" -> "{v}"' for k, v in sorted(self.force.items()))
            parts.append(f"Always render these this way: {pairs}")
        names = [*self.speakers, *self.terms]
        if names:
            parts.append(
                "These are proper nouns; keep their spelling and never translate them: "
                + ", ".join(sorted(set(names)))
            )
        return "\n".join(parts)

    def __bool__(self) -> bool:
        return bool(self.terms or self.keep_untranslated or self.force or self.speakers)
