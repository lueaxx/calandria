"""Cost arithmetic and subtitle timing.

Both are things nobody checks by looking. A wrong dollar figure quietly informs
a budget decision; a wrong timestamp quietly desynchronises a subtitle track
from the recording it belongs to.
"""

import json

from calandria.cost import CostTracker, Prices
from calandria.export import build_cues, to_srt, to_txt, to_vtt
from calandria.glossary import Glossary


# ------------------------------------------------------------------- cost

def test_transcription_is_billed_against_audio_duration():
    c = CostTracker(prices=Prices(stt_audio_per_min=0.005, stt_text_per_min=0.004))
    c.add_audio(3600)
    assert round(c.stt_usd, 4) == round(60 * 0.009, 4) == 0.54


def test_translation_is_billed_against_reported_tokens():
    c = CostTracker(prices=Prices(mt_input_per_mtok=0.30, mt_output_per_mtok=2.50))
    c.add_translation(1_000_000, 1_000_000)
    assert round(c.mt_usd, 4) == 2.80


def test_total_is_transcription_plus_translation():
    c = CostTracker()
    c.add_audio(600)
    c.add_translation(10_000, 5_000)
    assert round(c.total_usd, 6) == round(c.stt_usd + c.mt_usd, 6)


def test_projection_extrapolates_the_measured_rate():
    c = CostTracker()
    c.add_audio(3600)                       # one stage-hour, no translation
    p = c.project(stages=10, hours=10, extra_languages=0)
    assert p["stt_usd"] == 54.0             # 100 stage-hours at $0.54
    assert p["total_usd"] == 54.0


def test_projection_does_not_divide_by_zero_before_any_audio():
    assert CostTracker().project(10, 10, 2)["total_usd"] == 0.0


# ----------------------------------------------------------------- export

def _finals(*pairs):
    return [{"text": t, "audio_ts": ts} for t, ts in pairs]


def test_cues_start_where_the_previous_one_ended():
    cues = build_cues(_finals(("one", 4.0), ("two", 9.0)))
    assert (cues[0].start, cues[0].end) == (0.0, 4.0)
    assert (cues[1].start, cues[1].end) == (4.0, 9.0)


def test_a_very_long_gap_is_clamped_to_a_readable_cue():
    # A three-minute silence must not produce a three-minute subtitle.
    cues = build_cues(_finals(("after a long pause", 200.0)))
    assert cues[0].end - cues[0].start <= 7.0


def test_empty_captions_are_skipped():
    assert build_cues(_finals(("", 1.0), ("   ", 2.0), ("real", 3.0))) [0].text == "real"


def test_srt_is_numbered_and_uses_comma_milliseconds():
    out = to_srt(_finals(("Hola", 2.5)))
    assert out.startswith("1\n")
    assert "00:00:00,000 --> 00:00:02,500" in out


def test_vtt_has_its_header_and_uses_dot_milliseconds():
    out = to_vtt(_finals(("Hola", 2.5)))
    assert out.startswith("WEBVTT")
    assert "00:00:00.000 --> 00:00:02.500" in out


def test_timestamps_roll_over_into_hours():
    assert "01:01:05,250" in to_srt(_finals(("late in the day", 3665.25)))


def test_txt_is_just_the_lines():
    assert to_txt(_finals(("one", 1.0), ("two", 2.0))) == "one\ntwo"


# --------------------------------------------------------------- glossary

def test_vocabulary_merges_every_section_without_duplicates():
    g = Glossary(terms=["Kubernetes"], speakers=["Ada"],
                 keep_untranslated=["deployment"], force={"kubernetes": "Kubernetes"})
    vocab = g.stt_vocabulary()
    assert vocab.count("Kubernetes") == 1          # case-insensitive de-dup
    assert set(vocab) >= {"Kubernetes", "Ada", "deployment"}


def test_translation_rules_are_empty_when_there_is_nothing_to_say():
    # An empty heading on every segment would be tokens spent on nothing.
    assert Glossary().translation_rules() == ""


def test_translation_rules_mention_the_terms_that_must_survive():
    rules = Glossary(keep_untranslated=["deployment"], speakers=["Ada Lovelace"]).translation_rules()
    assert "deployment" in rules and "Ada Lovelace" in rules


def test_a_long_glossary_warns_rather_than_silently_truncating():
    g = Glossary(terms=[f"term{i}" for i in range(300)])
    assert any("under" in w for w in g.warnings())


def test_glossary_loads_from_yaml(tmp_path):
    p = tmp_path / "g.yaml"
    p.write_text("terms: [Nerdearla]\nkeep_untranslated: [commit]\n", encoding="utf-8")
    g = Glossary.load(p)
    assert g.terms == ["Nerdearla"] and g.keep_untranslated == ["commit"]


def test_no_glossary_configured_is_fine():
    assert not Glossary.load(None)
