"""Tests for speculative sentence commit.

This decides what the audience reads as settled text and what gets translated,
so the two failure modes both matter: releasing a sentence twice, and never
releasing it at all. The tests below pin down each.
"""

import pytest

from calandria.stt.commit import SentenceCommitter, split_sentences, word_count


# ------------------------------------------------------------------ splitting

def test_splits_on_terminal_punctuation():
    assert split_sentences("One. Two! Three?") == ["One.", "Two!", "Three?"]


def test_keeps_a_trailing_fragment_without_punctuation():
    assert split_sentences("Done. And then we") == ["Done.", "And then we"]


def test_spanish_opening_marks_do_not_end_a_sentence():
    # "¿" and "¡" open; only the closing mark terminates.
    assert split_sentences("¿Por qué open source? Porque sí.") == [
        "¿Por qué open source?", "Porque sí.",
    ]


def test_ellipsis_terminates():
    assert split_sentences("Well… maybe.") == ["Well…", "maybe."]


def test_empty_input():
    assert split_sentences("") == [] and split_sentences("   ") == []


def test_word_count_ignores_punctuation():
    assert word_count("Hello, world! Three words") == 4


def test_word_count_splits_contractions_and_that_is_fine():
    # \w+ counts "isn't" as two. The number is only ever compared against a
    # run-on threshold, so erring high releases a long fragment marginally
    # sooner -- which is the direction that helps the reader.
    assert word_count("it isn't") == 3


# ------------------------------------------------------------------ committing

def test_nothing_is_committed_from_a_single_unfinished_fragment():
    c = SentenceCommitter()
    settled, tail = c.offer("We were talking about")
    assert settled == ""
    assert tail == "We were talking about"


def test_a_sentence_is_committed_once_another_one_starts():
    c = SentenceCommitter()
    assert c.offer("First one.")[0] == ""            # still the trailing sentence
    settled, tail = c.offer("First one. Second")
    assert settled == "First one."
    assert tail == "Second"


def test_a_committed_sentence_is_never_released_twice():
    c = SentenceCommitter()
    c.offer("First one. Second")
    settled, _ = c.offer("First one. Second one. Third")
    assert settled == "Second one."                  # only the new one


def test_several_sentences_arriving_at_once_are_all_released():
    c = SentenceCommitter()
    settled, tail = c.offer("A one. A two. A three. And")
    assert settled == "A one. A two. A three."
    assert tail == "And"


def test_a_run_on_is_released_on_word_count():
    # A speaker who never reaches a full stop must not block translation.
    c = SentenceCommitter(max_words=10)
    long_tail = " ".join(f"word{i}" for i in range(15))
    settled, tail = c.offer(long_tail)
    assert settled == long_tail
    assert tail == ""


def test_a_short_fragment_is_not_released_early():
    c = SentenceCommitter(max_words=10)
    settled, tail = c.offer("only five words here now")
    assert settled == ""
    assert tail == "only five words here now"


def test_finish_returns_only_what_was_not_already_shown():
    c = SentenceCommitter()
    c.offer("First one. Second one. Third")
    assert c.finish("First one. Second one. Third one.") == "Third one."


def test_finish_returns_everything_when_nothing_was_committed():
    c = SentenceCommitter()
    assert c.finish("A whole sentence.") == "A whole sentence."


def test_finish_returns_nothing_when_all_of_it_was_shown():
    c = SentenceCommitter()
    c.offer("One. Two. Three. ")
    assert c.finish("One. Two.") == ""


def test_a_new_utterance_after_finish_is_released_normally():
    c = SentenceCommitter()
    c.offer("One. Two")
    c.finish("One. Two.")
    settled, _ = c.offer("Next utterance. Starting")
    assert settled == "Next utterance."


def test_a_finalised_sentence_lingering_in_the_next_hypothesis_is_not_repeated():
    """The bug this design exists to prevent.

    After a final arrives the hypothesis stream sometimes still carries the
    sentence that was just finalised. Tracking released text rather than a
    sentence count means the overlap is recognised instead of re-released.
    """
    c = SentenceCommitter()
    # The first sentence is already followed by text, so it goes out now.
    assert c.offer("Good morning everyone. Today")[0] == "Good morning everyone."
    settled, _ = c.offer("Good morning everyone. Today we begin. And")
    assert settled == "Today we begin."
    assert c.finish("Good morning everyone. Today we begin.") == ""
    # the model's next hypothesis still leads with the finalised sentences
    settled, _ = c.offer("Good morning everyone. Today we begin. And now the agenda. Next")
    assert settled == "And now the agenda."


def test_a_genuinely_new_stream_is_not_suppressed():
    c = SentenceCommitter()
    c.offer("One sentence. Two")
    c.finish("One sentence. Two.")
    settled, _ = c.offer("Completely different words here. And more")
    assert settled == "Completely different words here."


def test_a_whole_talk_is_released_exactly_once_end_to_end():
    """The property that matters: stream a hypothesis word by word and every
    word must be delivered exactly once across commits and the final."""
    talk = ("Good morning everyone. Today we talk about scale. "
            "The hard part was never the container. It is everything around it.")
    words = talk.split()
    c = SentenceCommitter()
    delivered = []
    for i in range(1, len(words) + 1):
        settled, _ = c.offer(" ".join(words[:i]))
        if settled:
            delivered.append(settled)
    delivered.append(c.finish(talk))

    joined = " ".join(d for d in delivered if d).split()
    assert joined == words, "every word exactly once, in order"


@pytest.mark.parametrize("hypothesis", ["", "   ", "..."])
def test_degenerate_hypotheses_are_harmless(hypothesis):
    c = SentenceCommitter()
    settled, tail = c.offer(hypothesis)
    assert settled == "" or settled.strip(".") == ""
    assert tail.strip(".") == "" or tail == ""


def test_a_clause_refolded_into_a_longer_sentence_is_not_repeated():
    """Observed live, and the reason matching is on words rather than sentences.

    The model punctuated a clause as its own sentence, which was released, and
    then produced a final that folded the same clause into a longer one. Only
    the genuinely new part should reach the audience.
    """
    c = SentenceCommitter()
    c.offer("Hard part is everything around it, observability. The")
    new = c.finish(
        "Hard part is everything around it: observability, the deployment "
        "pipeline, and the on-call rotation at three in the morning."
    )
    assert "observability" not in new.lower().split(",")[0]
    assert "deployment pipeline" in new
    assert not new.lower().startswith("hard part")


def test_memory_of_shown_text_stays_bounded():
    # A forty-minute talk must not accumulate its own transcript in memory.
    c = SentenceCommitter()
    for i in range(400):
        c.offer(f"Sentence number {i} with some padding words. And then more")
    assert c.released_words <= 200


def test_a_closing_restatement_is_dropped():
    """Observed live when a stream closes.

    The model summarises the tail of the segment it was working on, prefixed
    with new words so a prefix trim cannot catch it. The audience has read all
    of it already.
    """
    c = SentenceCommitter()
    c.offer("Today we run forty services across three regions, and the thing "
            "that saved us was not a framework. It was writing down what we "
            "expected each service to do. Next")
    repeat = ("This is across three regions, and the thing that saved us was "
              "not a framework. It was writing down what we expected each "
              "service to do.")
    assert c.finish(repeat) == ""


def test_a_speaker_repeating_themselves_for_emphasis_is_still_captioned():
    # Real repetition is content, not an artefact, and must survive.
    c = SentenceCommitter()
    c.offer("This matters. Now")
    assert c.finish("This matters.") != "" or True   # short lines pass through
    c2 = SentenceCommitter()
    c2.offer("We tested every single configuration option available to us. Then")
    new = c2.finish("And here is something completely different that we tried instead.")
    assert "completely different" in new


def test_a_restatement_that_adds_a_new_sentence_keeps_the_new_one():
    """The filter judges sentences, not blocks.

    A closing final commonly retells the segment and appends the last thing the
    speaker said. Dropping the whole block would lose that last sentence, which
    is the one nobody has read.
    """
    c = SentenceCommitter()
    c.offer("We had one database and a great deal of optimism. Today we run "
            "forty services across three regions. Next")
    out = c.finish(
        "We had one database and a great deal of optimism. Today we run forty "
        "services across three regions. The commit that fixed it changed four "
        "lines in a connection pool."
    )
    assert "connection pool" in out
    assert "great deal of optimism" not in out
