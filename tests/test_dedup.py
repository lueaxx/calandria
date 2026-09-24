"""Tests for the overlap de-duplication used when rotating Live sessions.

During a rotation both the outgoing and incoming session hear the same few
seconds of audio. The incoming session's first transcript therefore repeats
text the audience has already read. These tests pin down exactly what gets
stripped -- and, just as importantly, what does not, because dropping real
speech is worse than showing a repeated word.
"""

import pytest

from calandria.stt.dedup import dedup_overlap


def test_no_overlap_returns_text_unchanged():
    assert dedup_overlap("we deploy on Friday", "Now about rollbacks") == "Now about rollbacks"


def test_strips_repeated_prefix():
    prev = "and that is why we use Kubernetes for this"
    new = "why we use Kubernetes for this. Now let us look at the operator"
    assert dedup_overlap(prev, new) == "Now let us look at the operator"


def test_ignores_case_and_punctuation_differences():
    prev = "the valuation is only two times your revenue"
    new = "Two times your revenue, but if you would be a software company"
    assert dedup_overlap(prev, new) == "but if you would be a software company"


def test_fully_contained_text_is_dropped_entirely():
    prev = "open source is about freedom not price"
    assert dedup_overlap(prev, "about freedom not price") == ""


def test_single_common_word_is_not_treated_as_overlap():
    # "the" matching by chance must not eat the start of a real sentence.
    prev = "we shipped it on the"
    new = "the database migration took four hours"
    assert dedup_overlap(prev, new) == "the database migration took four hours"


def test_empty_inputs():
    assert dedup_overlap("", "hello world") == "hello world"
    assert dedup_overlap("hello world", "") == ""
    assert dedup_overlap("", "") == ""


def test_prefers_the_longest_overlap():
    # "for this" also matches, but the longer run is the true seam.
    prev = "we run it for this and we run it for this"
    new = "and we run it for this. Next slide please"
    assert dedup_overlap(prev, new) == "Next slide please"


def test_only_the_tail_of_prev_is_considered():
    # An early coincidence in prev must not strip text from new.
    prev = "Next slide please. " + "filler words here " * 10 + "the end of the segment"
    new = "Next slide please"
    assert dedup_overlap(prev, new) == "Next slide please"


@pytest.mark.parametrize("junk", ["...", "—", "  ", "\n"])
def test_whitespace_and_punctuation_only_text(junk):
    assert dedup_overlap("something real", junk).strip() in ("", junk.strip())


def test_numbers_written_two_ways_compare_equal():
    """Observed live: the model wrote "2,000" once and "2000" the next time.

    Tokenising on word characters alone splits "2,000" into two, so the word
    sequences differ and every comparison built on them misses the repeat.
    """
    prev = "our p99 latency went from 2,000 milliseconds to under 150"
    new = "Our P99 latency went from 2000 milliseconds to under 150. The commit that fixed it."
    assert dedup_overlap(prev, new) == "The commit that fixed it."
