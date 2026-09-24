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
from difflib import SequenceMatcher

from .dedup import dedup_overlap, drop_leading_words, normalise

# Terminal punctuation, including the inverted marks Spanish opens with -- which
# must not be treated as the *end* of anything.
_SENTENCE = re.compile(r"[^.!?…]+[.!?…]+[\"')\]]*\s*|[^.!?…]+$", re.UNICODE)
_WORD = re.compile(r"\w+", re.UNICODE)

DEFAULT_MAX_WORDS = 30
# A ceiling on one utterance, far past anything a person says without a
# detectable pause. Reaching it means something is wrong, not that a sentence
# is long.
_MAX_UTTERANCE_WORDS = 8000
# Below this a repeated run is a speaker making a point, not the model
# retelling a segment.
_MIN_RESTATEMENT_WORDS = 8
# How much recently shown text is kept for spotting a retelling. Long enough to
# cover the segment a closing final repeats, short enough that a speaker
# returning to a theme minutes later is still captioned.
_HISTORY_WORDS = 400
# How much of a line must align with recently shown text to count as a
# retelling rather than new speech.
_RESTATEMENT_SIMILARITY = 0.85
# Below this a line is judged only by exact match; see _already_shown.
_SIMILARITY_MIN_WORDS = 25


def split_sentences(text: str) -> list[str]:
    """Split into sentences, keeping their punctuation and dropping padding.

    A full stop between digits is a decimal point, not the end of anything:
    without this, "Apache 2.0" becomes a sentence ending in "Apache 2." and a
    second one reading "0.", and the audience sees a caption containing a single
    zero. Version numbers and decimals turn up constantly in technical talks.
    """
    parts = [s.strip() for s in _SENTENCE.findall(text or "") if s.strip()]
    merged: list[str] = []
    for part in parts:
        if (merged and part[0].isdigit()
                and len(merged[-1]) > 1 and merged[-1][-1] == "."
                and merged[-1][-2].isdigit()):
            merged[-1] = merged[-1] + part
        else:
            merged.append(part)
    return merged


def word_count(text: str) -> int:
    return len(normalise(text))



class SentenceCommitter:
    """Tracks what the audience has already read of the current utterance.

    The model's running hypothesis always restates the utterance from its
    beginning, so the question at every update is simply: how much of this have
    they seen? That is answered by keeping the words already released and
    checking whether the new hypothesis starts with them.

    The check is an exact prefix comparison, which is the whole point. An
    earlier version kept only a bounded tail to save memory, which made exact
    comparison impossible and forced a pile of heuristics -- suffix matching,
    n-gram overlap ratios -- each of which failed on a different real input:
    utterances released twice, utterances released in full on every update,
    closing restatements slipping through. An utterance is at most a few
    thousand words. Keeping all of them costs nothing and needs no thresholds.

    When a hypothesis does not start with what was released, it belongs to a
    different utterance and the slate is cleared. Nothing has to predict when
    the model decides to start over.
    """

    def __init__(self, max_words: int = DEFAULT_MAX_WORDS) -> None:
        self.max_words = max_words
        # Where to cut the current utterance. Cleared when the model starts a
        # new one, because the cut point is meaningless across utterances.
        self._released: list[str] = []
        # What the audience has read lately, regardless of which utterance it
        # came from. This must outlive `_released`: when a stream closes the
        # model repeats the whole utterance several times with interims in
        # between, and those interims clear `_released` just before the next
        # repeat needs it.
        self._history: list[str] = []

    def reset(self) -> None:
        self._released = []

    @property
    def released_words(self) -> int:
        return len(self._released)

    def _covered(self, flat: list[str]) -> int:
        """How many leading words of `flat` have already been shown.

        A question, not a command: it never clears state. Clearing belongs to
        `offer`, which knows it is looking at a new utterance -- `finish` asks
        the same question and still needs the old words afterwards to recognise
        a restatement.
        """
        n = len(self._released)
        if n and len(flat) >= n and flat[:n] == self._released:
            return n
        return 0

    def _remember(self, words: list[str]) -> None:
        self._history = (self._history + words)[-_HISTORY_WORDS:]
        self._released.extend(words)
        if len(self._released) > _MAX_UTTERANCE_WORDS:
            # Far past any real utterance; treat it as a fresh one rather than
            # grow without bound.
            self._released = self._released[-_MAX_UTTERANCE_WORDS:]

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

        flat = normalise(hypothesis)
        covered = self._covered(flat)
        if not covered and self._released:
            self.reset()                 # this hypothesis is a new utterance

        first_new, consumed = 0, 0
        for i, sentence in enumerate(sentences):
            consumed += len(normalise(sentence))
            if consumed <= covered:
                first_new = i + 1
            else:
                break

        settled_upto = len(sentences) - 1        # hold the trailing fragment
        tail = sentences[-1]
        if settled_upto <= first_new and word_count(tail) > self.max_words:
            settled_upto = len(sentences)        # a run-on; release it anyway
            tail = ""

        if settled_upto <= first_new:
            return "", tail

        # The cut point says where this utterance was left off; it says nothing
        # about whether the audience has read these words before. A replayed
        # utterance resets the cut point, so the history is consulted too.
        new = self._drop_already_shown(" ".join(sentences[first_new:settled_upto]))
        if not new.strip():
            return "", tail
        self._remember(normalise(new))
        return new, tail

    def _trim_reworded(self, text: str) -> str:
        """Trim a final that restates shown text without repeating it verbatim.

        When a stream closes the model tends to retell the tail of the segment,
        and often puts a few words of its own in front -- "This is across three
        regions..." where the audience already read "across three regions...".
        A prefix comparison cannot see past that framing, so try skipping a word
        or two before giving up. Bounded deliberately: past three words this is
        no longer the same sentence being restated.
        """
        shown = " ".join(self._released)
        trimmed = dedup_overlap(shown, text)
        if trimmed != text:
            return trimmed
        for skip in (0, 1, 2, 3):
            candidate = drop_leading_words(text, skip) if skip else text
            if not candidate:
                break
            if self._already_shown(normalise(candidate)):
                return ""
            if skip:
                trimmed = dedup_overlap(shown, candidate)
                if trimmed != candidate:
                    return trimmed
        return text

    def _shown_prefix_len(self, words: list[str]) -> int:
        """How many of these words, from the start, the audience has read.

        The question is a length, not a yes or no. A replayed utterance usually
        arrives with a little new speech on the end, so "have they seen this"
        has no good answer: suppressing loses the new part, releasing repeats
        the old one. Asking how much was seen makes the cut exact.
        """
        best, n = 0, len(self._history)
        for start in range(n):
            k = 0
            while (start + k < n and k < len(words)
                   and self._history[start + k] == words[k]):
                k += 1
            if k > best:
                best = k
                if best == len(words):
                    break
        return best

    def _drop_already_shown(self, text: str) -> str:
        """Remove the leading part of `text` that has already been read."""
        words = normalise(text)
        if not words or not self._history:
            return text
        seen = self._shown_prefix_len(words)
        if seen >= len(words):
            return ""
        if seen >= _MIN_RESTATEMENT_WORDS:
            return drop_leading_words(text, seen)
        # No usable prefix: the retelling may have been reworded rather than
        # replayed, which only a similarity comparison can recognise.
        return "" if self._already_shown(words) else text

    def _already_shown(self, words: list[str]) -> bool:
        """Is this exact run of words sitting somewhere in what was shown?

        A seam answers "where does this join on"; this answers "have they read
        this before". They are different questions, and a closing restatement
        needs the second one -- it retells from the middle of what was shown,
        not from the end, so no seam exists to find.

        Contiguous and exact, so a speaker who genuinely repeats a short phrase
        for emphasis is not silenced; only a run long enough to be a retelling
        counts.
        """
        n = len(words)
        if n < _MIN_RESTATEMENT_WORDS or not self._history:
            return False

        # Exact first: cheap, and covers a verbatim replay.
        if n <= len(self._history) and any(
            self._history[i:i + n] == words
            for i in range(len(self._history) - n + 1)
        ):
            return True

        # A retelling is rarely word-perfect -- "gracias por venir a esta
        # charla" comes back as "gracias por venir por esta charla" -- so an
        # exact comparison alone lets the closing repeat through.
        #
        # Only whole blocks are judged this way. The thing being caught is a
        # segment replayed at the end of a stream, which runs to dozens of
        # words; at the scale of one sentence, two genuinely different lines
        # ("we tested option A", "we tested option B") are similar enough to
        # trip any useful threshold, and suppressing those would silence real
        # speech.
        if n < _SIMILARITY_MIN_WORDS:
            return False
        matcher = SequenceMatcher(None, self._history, words, autojunk=False)
        matched = sum(block.size for block in matcher.get_matching_blocks())
        return matched / n >= _RESTATEMENT_SIMILARITY

    def finish(self, final_text: str) -> str:
        """The model's own final arrived; return only what has not been shown.

        The final is authoritative and usually tidier than the hypotheses that
        preceded it, but the audience has read most of it already. When it
        matches what was released word for word, the remainder is exact. When
        the model has reworded it, fall back to trimming the overlap.

        The released words are kept rather than cleared, because the next
        hypothesis sometimes still carries this utterance -- and if it carries a
        different one, the prefix check notices and clears them anyway.
        """
        sentences = split_sentences(final_text)
        if not sentences:
            return ""

        flat = normalise(final_text)
        covered = self._covered(flat)

        if covered >= len(flat):
            return ""
        if covered:
            # Cut at the word, not at the sentence. The model routinely refolds
            # a clause that was released as its own sentence into a longer one,
            # and cutting on sentence boundaries would show that clause twice.
            new = drop_leading_words(final_text, covered)
        else:
            new = self._drop_already_shown(self._trim_reworded(final_text))

        if not new.strip():
            return ""
        self._remember(normalise(new))
        return new
