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

# Terminal punctuation, including the inverted marks Spanish opens with -- which
# must not be treated as the *end* of anything.
_SENTENCE = re.compile(r"[^.!?…]+[.!?…]+[\"')\]]*\s*|[^.!?…]+$", re.UNICODE)
_WORD = re.compile(r"\w+", re.UNICODE)

DEFAULT_MAX_WORDS = 30


def split_sentences(text: str) -> list[str]:
    """Split into sentences, keeping their punctuation and dropping padding."""
    return [s.strip() for s in _SENTENCE.findall(text or "") if s.strip()]


def word_count(text: str) -> int:
    return len(_WORD.findall(text or ""))


class SentenceCommitter:
    """Tracks one utterance's hypothesis and decides what is safe to release.

    Fed the running hypothesis, it returns the text newly ready to be treated as
    final. When the model eventually produces its own final, `finish` returns
    whatever was not already released, so nothing is shown twice and nothing is
    dropped.
    """

    def __init__(self, max_words: int = DEFAULT_MAX_WORDS) -> None:
        self.max_words = max_words
        self._committed = 0          # sentences of this utterance already released

    def reset(self) -> None:
        self._committed = 0

    @property
    def committed_sentences(self) -> int:
        return self._committed

    def offer(self, hypothesis: str) -> tuple[str, str]:
        """Take the current hypothesis; return (newly settled text, still provisional).

        A sentence is settled once another sentence has started after it. The
        last sentence is held back, because it is the one still being revised --
        unless it has run past `max_words` without reaching any punctuation, in
        which case waiting longer serves nobody.
        """
        sentences = split_sentences(hypothesis)
        if not sentences:
            return "", ""

        settled_upto = len(sentences) - 1        # hold the trailing fragment
        tail = sentences[-1]
        if settled_upto == self._committed and word_count(tail) > self.max_words:
            settled_upto = len(sentences)        # a run-on; release it anyway
            tail = ""
        elif settled_upto < len(sentences):
            tail = sentences[-1]

        if settled_upto <= self._committed:
            return "", tail

        new = " ".join(sentences[self._committed:settled_upto])
        self._committed = settled_upto
        return new, tail

    def finish(self, final_text: str) -> str:
        """The model's own final arrived; return only what has not been shown.

        The final is authoritative and usually cleaner than the hypotheses that
        preceded it, but the audience has already read most of it. Only the part
        beyond what was committed is new.
        """
        sentences = split_sentences(final_text)
        remaining = sentences[self._committed:] if self._committed < len(sentences) else []
        self.reset()
        return " ".join(remaining)
