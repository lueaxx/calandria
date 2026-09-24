"""Seam repair for session rotation.

The Live transcription API caps a session at ten minutes. A conference talk is
forty. Calandria therefore opens a replacement session before the old one
expires and feeds both the same audio for a few seconds, so that captions never
stop. The cost of that trick is a few seconds of duplicated text, which this
module removes.

The two sessions do not produce byte-identical transcripts of the same audio --
they punctuate differently and sometimes pick different words -- so matching is
done on normalised words, and a match must be at least MIN_OVERLAP_WORDS long
before anything is cut. That threshold is the whole safety argument: showing a
repeated word is a blemish, while silently deleting a sentence the speaker
actually said is a failure of the thing we are building.
"""

from __future__ import annotations

import re

MIN_OVERLAP_WORDS = 2
# Only this many trailing words of the previous transcript can form a seam; an
# overlap window is seconds long, so a match further back is a coincidence.
MAX_LOOKBACK_WORDS = 60

_WORD = re.compile(r"\w+", re.UNICODE)
# A thousands separator: "2,000" and "2.000" must compare equal to "2000".
# Without this the same number written two ways tokenises into a different
# number of words, and every comparison built on words silently misses it.
_DIGIT_SEPARATOR = re.compile(r"(?<=\d)[.,](?=\d)")


def normalise(text: str) -> list[str]:
    """Words, lowercased, with numbers written one way.

    Shared by both places that compare transcribed text: the seam between two
    live sessions during a rotation, and the seam between what the audience has
    already read and what the model just produced.
    """
    return [w.casefold() for w in _WORD.findall(_DIGIT_SEPARATOR.sub("", text or ""))]



def dedup_overlap(previous_tail: str, new_text: str) -> str:
    """Strip from `new_text` the part already shown as the end of `previous_tail`.

    Returns `new_text` unchanged when there is no convincing overlap, and an
    empty string when all of it was already shown.
    """
    new_words = normalise(new_text)
    prev_words = normalise(previous_tail)
    if not new_words or not prev_words:
        return new_text

    prev_words = prev_words[-MAX_LOOKBACK_WORDS:]

    # Find the longest suffix of prev that is also a prefix of new.
    max_k = min(len(prev_words), len(new_words))
    overlap = 0
    for k in range(max_k, MIN_OVERLAP_WORDS - 1, -1):
        if prev_words[-k:] == new_words[:k]:
            overlap = k
            break

    if overlap == 0:
        return new_text
    if overlap == len(new_words):
        return ""

    return _drop_leading_words(new_text, overlap)


def _drop_leading_words(text: str, count: int) -> str:
    """Remove the first `count` words from `text`, keeping the original spelling
    and punctuation of everything that survives."""
    matches = list(_WORD.finditer(text))
    if count >= len(matches):
        return ""
    cut = matches[count].start()
    # Also drop punctuation and spaces stranded at the new beginning.
    return text[cut:].lstrip(" ,.;:!?-–—\t\n")


def tail_words(text: str, count: int = MAX_LOOKBACK_WORDS) -> str:
    """The trailing slice of a transcript worth keeping as a seam reference."""
    matches = list(_WORD.finditer(text))
    if len(matches) <= count:
        return text
    return text[matches[-count].start():]
