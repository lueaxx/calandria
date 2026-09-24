"""Deciding when a sentence is settled enough to translate.

The transcription model finalises a segment when it detects end of speech. That
is the speaker's decision, not ours, and speakers vary: a measured presenter
produces a finalised segment every few seconds, while someone in full flow can
run for half a minute without a gap the detector will accept. Tuning the
detector does not help -- every silence and sensitivity setting tested produced
identical results on continuous speech.

Translation cannot wait for that. It runs on finalised text, so a speaker who
does not pause gets no translated captions for as long as they keep talking,
which on a real talk was measured at 15 to 20 seconds at a stretch.

So Calandria commits sentences itself. When the running hypothesis contains a
completed sentence *followed by more text*, the model has moved past that
sentence and is no longer revising it: it can be treated as settled. Translation
then fires per sentence instead of per pause, and the wait drops to about two
seconds.

The conservative part is the trailing fragment, which is still being revised and
is never committed on sentence grounds alone. A run-on with no punctuation is
released on word count instead, because a viewer reading a translation should
not be held hostage to a speaker who never reaches a full stop.
"""

from __future__ import annotations

import re

from .dedup import dedup_overlap, normalise

# Terminal punctuation, including the inverted marks Spanish opens with -- which
# must not be treated as the *end* of anything.
_SENTENCE = re.compile(r"[^.!?…]+[.!?…]+[\"')\]]*\s*|[^.!?…]+$", re.UNICODE)
_WORD = re.compile(r"\w+", re.UNICODE)

DEFAULT_MAX_WORDS = 30
# Words of shown text kept for overlap matching. Comfortably longer than any
# single revision, far shorter than a talk.
_MEMORY_WORDS = 120
# A line is treated as a retelling when this share of its word runs has already
# been shown. Set high enough that a speaker genuinely repeating themselves for
# emphasis still gets captioned.
_RESTATEMENT_N = 4
_RESTATEMENT_RATIO = 0.6


def split_sentences(text: str) -> list[str]:
    """Split into sentences, keeping their punctuation and dropping padding."""
    return [s.strip() for s in _SENTENCE.findall(text or "") if s.strip()]


def word_count(text: str) -> int:
    return len(normalise(text))


def _words(text: str) -> list[str]:
    # The same normalisation the rotation seam uses, so both comparisons agree
    # about what counts as the same word.
    return normalise(text)


def _ngrams(words: list[str], n: int) -> set[str]:
    return {" ".join(words[i:i + n]) for i in range(len(words) - n + 1)}


class SentenceCommitter:
    """Tracks what the audience has already read, and decides what to add.

    State here is the released *text*, not a count of released sentences. A
    count assumes the hypothesis stream and the model's own finals stay in step,
    and they do not: after a final arrives, the next hypothesis sometimes still
    carries the sentence that was just finalised. A counter reset to zero then
    releases that sentence a second time, and the audience reads it twice.

    Matching on text needs no such assumption. If a hypothesis begins with what
    has already been shown, it continues the same stream and only the remainder
    is new. If it does not, the model has started over and so do we. Nothing has
    to predict when that happens.
    """

    def __init__(self, max_words: int = DEFAULT_MAX_WORDS) -> None:
        self.max_words = max_words
        self._released: list[str] = []   # normalised words already sent onward

    def reset(self) -> None:
        self._released = []

    def _remember(self, text: str) -> None:
        """Keep a bounded tail of what has been shown, for overlap matching.

        Only the recent tail can plausibly overlap with what arrives next, and
        an unbounded list would grow for the length of a talk.
        """
        self._released.extend(_words(text))
        if len(self._released) > _MEMORY_WORDS:
            self._released = self._released[-_MEMORY_WORDS:]

    @property
    def released_words(self) -> int:
        return len(self._released)

    def _is_restatement(self, text: str) -> bool:
        """Whether this is mostly a retelling of what the audience just read.

        Trimming works by prefix, so it cannot catch a line that restates
        shown text with a few words in front of it -- and the model does
        exactly that when a stream closes, summarising the tail of the segment
        it was working on. Comparing short word runs instead of prefixes
        recognises the restatement wherever it starts.
        """
        candidate = _ngrams(_words(text), _RESTATEMENT_N)
        if len(candidate) < _RESTATEMENT_N:
            return False                 # too short to judge; let it through
        seen = _ngrams(self._released, _RESTATEMENT_N)
        if not seen:
            return False
        overlap = sum(1 for g in candidate if g in seen) / len(candidate)
        return overlap >= _RESTATEMENT_RATIO

    def _trim(self, text: str) -> str:
        """Remove from `text` whatever the audience has already read.

        Matching is on words rather than sentences because the model revises
        its own punctuation: a clause released as its own sentence often comes
        back folded into a longer one. Comparing sentence to sentence misses
        that and shows the clause twice.

        This is the same operation as repairing the seam between two live
        sessions during a rotation, so it is the same tested function.
        """
        if not self._released:
            return text
        return dedup_overlap(" ".join(self._released), text)

    def offer(self, hypothesis: str) -> tuple[str, str]:
        """Take the running hypothesis; return (newly settled, still provisional).

        A sentence is settled once another has started after it, because the
        model has visibly moved past it. The trailing fragment is held back,
        since it is the part still being revised -- unless it has run past
        `max_words` without reaching any punctuation, in which case waiting
        longer serves nobody.
        """
        sentences = split_sentences(hypothesis)
        if not sentences:
            return "", ""

        settled_upto = len(sentences) - 1        # hold the trailing fragment
        tail = sentences[-1]

        if settled_upto == 0 and word_count(tail) > self.max_words:
            settled_upto = len(sentences)        # a run-on; release it anyway
            tail = ""

        candidate = " ".join(sentences[:settled_upto])
        new = self._trim(candidate)
        if not new.strip():
            return "", self._trim(tail) if self._released else tail

        self._remember(new)
        return new, tail

    def finish(self, final_text: str) -> str:
        """The model's own final arrived; return only what has not been shown.

        The final is authoritative and usually tidier than the hypotheses that
        preceded it, but the audience has already read most of it.
        """
        sentences = split_sentences(final_text)
        if not sentences:
            return ""
        trimmed = self._trim(" ".join(sentences))
        if not trimmed.strip():
            return ""

        # Judge each sentence on its own. A closing final often retells several
        # sentences and adds one; discarding the whole block because most of it
        # is old would throw away the part that is not.
        kept = [s for s in split_sentences(trimmed) if not self._is_restatement(s)]
        if not kept:
            return ""
        out = " ".join(kept)
        self._remember(out)
        return out
