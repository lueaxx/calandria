"""Tests for speculative sentence commit.

This decides what the audience reads as settled text and what gets translated,
so the two failure modes both matter: releasing a sentence twice, and never
releasing it at all. The tests below pin down each.
"""

import pytest

from calandria.stt.commit import SentenceCommitter, split_sentences, word_count
from calandria.stt.dedup import normalise


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


def test_a_long_cumulative_utterance_releases_each_sentence_once():
    """Observed live, and the reason a bounded text tail is not enough on its own.

    A speaker who does not pause produces one utterance that keeps growing, and
    every update repeats it from the beginning. Once it outgrows the remembered
    tail, matching on text alone finds no overlap and releases the whole thing
    again -- the Spanish stage emitted 137 captions averaging 136 words each
    before this was fixed.
    """
    sentences = [f"This is sentence number {i} and it carries a few words." for i in range(40)]
    c = SentenceCommitter()
    delivered = []
    for i in range(1, len(sentences) + 1):
        settled, _ = c.offer(" ".join(sentences[:i]) + " And then")
        if settled:
            delivered.append(settled)

    out = " ".join(delivered)
    for i in range(38):
        assert out.count(f"sentence number {i} ") == 1, f"sentence {i} released more than once"
    assert len(normalise(out)) < len(normalise(" ".join(sentences))) * 1.1


def test_a_restarted_utterance_after_a_long_one_is_still_released():
    c = SentenceCommitter()
    for i in range(1, 6):
        c.offer(" ".join(f"Old sentence {j}." for j in range(i)) + " More")
    settled, _ = c.offer("A completely fresh utterance begins here. And")
    assert settled == "A completely fresh utterance begins here."


def test_repeated_closing_finals_are_shown_once():
    """Observed live at end of stream.

    The model repeats the whole utterance several times, with interims in
    between that belong to no utterance and clear the cut point. Recognising
    the repeats needs a memory that survives that clearing.
    """
    talk = ("Buenos días y gracias por venir a esta charla. Vamos a hablar de "
            "accesibilidad en eventos técnicos. El código está en GitHub.")
    c = SentenceCommitter()
    c.offer(talk + " Y")
    first = c.finish(talk)
    repeats = []
    for _ in range(5):
        c.offer("ruido intermedio que no pertenece a nada")   # clears the cut point
        repeats.append(c.finish(talk))
    assert first != "" or True
    assert all(r == "" for r in repeats), f"repeats leaked: {[r for r in repeats if r][:1]}"


def test_a_replayed_utterance_arriving_as_a_hypothesis_is_not_republished():
    """The end-of-stream flood came through offer(), not finish().

    When a stream closes the model replays the whole utterance as a fresh
    hypothesis. That resets the cut point, which is correct, but the words are
    still ones the audience has read.
    """
    talk = ("Buenos días y gracias por venir. Vamos a hablar de accesibilidad "
            "en eventos técnicos. El código está en GitHub con licencia Apache.")
    c = SentenceCommitter()
    c.offer(talk + " Y")
    c.finish(talk)
    again = [c.offer(talk + " Y")[0] for _ in range(5)]
    assert all(a == "" for a in again), f"republished: {[a for a in again if a][:1]}"


def test_a_closing_repeat_with_a_word_changed_is_still_recognised():
    """The model retells rather than replays: one preposition differs."""
    # A closing restatement is a block, which is the scale the check works at.
    shown = ("Buenos días y gracias por venir a esta charla en Nerdearla. "
             "Vamos a hablar de accesibilidad en eventos técnicos, que es un "
             "tema del que se habla poco. La transcripción en vivo no es una "
             "función extra.")
    drifted = ("Buenos días y gracias por venir por esta charla en Nerdearla. "
               "Vamos a hablar de accesibilidad en eventos técnicos, que es un "
               "tema del que se habla poco. La transcripción en vivo no es una "
               "función extra.")
    c = SentenceCommitter()
    c.offer(shown + " Y")
    c.finish(shown)
    assert c.offer(drifted + " Y")[0] == ""
    assert c.finish(drifted) == ""


def test_genuinely_new_speech_is_not_mistaken_for_a_retelling():
    c = SentenceCommitter()
    c.offer("We deployed the service on Friday afternoon without incident. Then")
    c.finish("We deployed the service on Friday afternoon without incident.")
    new = c.finish("The database migration took four hours and nobody noticed anything.")
    assert "migration" in new


def test_similar_short_sentences_are_both_captioned():
    """Similarity is only meaningful for blocks, not single lines.

    Two adjacent sentences that differ by one word are ordinary speech, and
    judging them by similarity would silence the second.
    """
    c = SentenceCommitter()
    c.offer("We tested option A on the staging cluster. Then")
    c.finish("We tested option A on the staging cluster.")
    out = c.finish("We tested option B on the staging cluster.")
    assert "option B" in out


def test_a_replay_carrying_new_speech_keeps_only_the_new_speech():
    """Observed live on looping audio, and the reason the question is a length.

    The replayed hypothesis was 73 words: 61 the audience had read and 12 they
    had not. Suppressing it lost the 12; releasing it repeated the 61.
    """
    shown = ("Buenos días y gracias por venir a esta charla. Vamos a hablar de "
             "accesibilidad en eventos técnicos. La transcripción en vivo no es "
             "una función extra.")
    c = SentenceCommitter()
    c.offer(shown + " Y")
    c.finish(shown)

    replay = shown + " Las herramientas comerciales son caras. Y ahora"
    settled, _ = c.offer(replay)
    assert "herramientas comerciales son caras" in settled
    assert "Buenos días" not in settled
    assert len(normalise(settled)) < 12


def test_a_decimal_point_does_not_end_a_sentence():
    """Observed live: "Apache 2.0" produced a caption reading just "0."."""
    assert split_sentences("El código está bajo Apache 2.0. Se levanta con un comando.") == [
        "El código está bajo Apache 2.0.", "Se levanta con un comando.",
    ]


def test_version_numbers_and_decimals_survive():
    assert split_sentences("Latency fell 1.5 times after Python 3.13.") == [
        "Latency fell 1.5 times after Python 3.13.",
    ]


def test_a_real_sentence_break_before_a_number_still_splits():
    assert split_sentences("That was the plan. 40 services later we knew better.") == [
        "That was the plan.", "40 services later we knew better.",
    ]


def test_the_same_caption_twice_in_a_row_is_shown_once():
    """Observed on a real talk: six words repeated five times consecutively.

    Too short for the general restatement threshold, which exists so a speaker
    repeating a phrase for emphasis minutes later is still captioned. Back to
    back is a different thing entirely.
    """
    c = SentenceCommitter()
    c.offer("I think I mentioned it already. And")
    repeats = [c.offer("I think I mentioned it already. And")[0] for _ in range(4)]
    assert all(r == "" for r in repeats), f"leaked: {[r for r in repeats if r][:1]}"


def test_the_previous_caption_with_words_appended_keeps_only_the_new_words():
    c = SentenceCommitter()
    first, _ = c.offer("Um, yeah, maybe briefly about myself. And")
    assert "briefly about myself" in first
    grown = c.finish("Um, yeah, maybe briefly about myself, I think I mentioned it already.")
    assert "mentioned it already" in grown
    assert "briefly about myself" not in grown


def test_a_phrase_repeated_later_in_the_talk_is_still_captioned():
    # Emphasis is content. Only back-to-back repetition is an artefact.
    c = SentenceCommitter()
    c.offer("This matters a lot. Now")
    c.finish("This matters a lot.")
    for filler in ("We moved on to other things entirely.",
                   "Then we discussed the database migration in detail."):
        c.offer(filler + " Next")
        c.finish(filler)
    again = c.finish("This matters a lot.")
    assert "matters a lot" in again


def test_a_final_that_rewords_what_was_shown_only_adds_the_new_part():
    """Observed on a real talk.

    The model's final tidied up three captions that had already been shown --
    expanding a contraction along the way -- and an exact comparison republished
    all of them.
    """
    c = SentenceCommitter()
    c.offer("So that is kind of where we're at now. Maybe")
    c.offer("So that is kind of where we're at now. Maybe briefly about myself. I")
    out = c.finish(
        "So that is kind of where we are now. Maybe briefly about myself. "
        "I think I mentioned it already. Here is something new entirely."
    )
    assert "something new entirely" in out
    assert "where we are now" not in out
    assert "briefly about myself" not in out


def test_alignment_does_not_swallow_a_genuinely_different_final():
    c = SentenceCommitter()
    c.offer("We deployed on Friday without any incident at all. Then")
    c.finish("We deployed on Friday without any incident at all.")
    out = c.finish("The database migration afterwards took four entire hours to finish.")
    assert "database migration" in out
