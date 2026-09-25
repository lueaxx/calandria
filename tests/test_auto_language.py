"""A stage that does not declare what language it hears.

Three separate things have to agree for `source_language: auto` to work, and
they live in three files. The third one -- config keeping every target -- is a
silent failure: the stage still runs, still transcribes, still translates, and
one language is simply missing from the viewer's menu.
"""

from calandria.config import Config
from calandria.translate.gemini import AUTO, SYSTEM_PROMPT, SYSTEM_PROMPT_AUTO


def _session(source_language, targets):
    cfg = Config.model_validate({
        "stt": {"backend": "fake"},
        "sessions": [{"id": "sala", "source": {"type": "mic"},
                      "source_language": source_language, "targets": targets}],
    })
    return cfg.sessions[0]


def test_a_named_source_still_drops_a_target_that_matches_it():
    # Translating a language into itself is a call that costs money to return
    # the input. That saving is the reason the rule exists.
    s = _session("es", ["es", "en", "pt"])
    assert s.targets == ["en", "pt"]


def test_an_auto_source_keeps_every_target():
    """Nothing to compare a target against, so nothing may be removed.

    The dropping rule reads 'remove the target equal to the source'. With the
    source literally the string 'auto', no target matches and the rule looks
    harmless -- but a stage that declares auto and lists Spanish is a stage
    whose audience can ask for Spanish, whatever gets spoken on it.
    """
    s = _session(AUTO, ["es", "en", "pt", "fr", "de", "it"])
    assert s.targets == ["es", "en", "pt", "fr", "de", "it"]


def test_the_auto_prompt_never_claims_to_know_the_source():
    """The whole point is not naming a language we were not told.

    A prompt that names one anyway is the failure this mode exists to avoid,
    and it would be invisible: the model would still answer, just worse.
    """
    p = SYSTEM_PROMPT_AUTO.format(target="Spanish", glossary="")
    assert "any language" in p
    assert "may change between lines" in p
    # It must not have interpolated a source, and must not have left the
    # fixed-source prompt's phrasing behind.
    assert "from {source}" not in p
    assert "Translate the LINE from" not in p


def test_the_auto_prompt_keeps_a_line_already_in_the_target_language():
    # Paraphrasing a line the audience can already read is indistinguishable,
    # from their seat, from the transcription getting it wrong.
    p = SYSTEM_PROMPT_AUTO.format(target="Spanish", glossary="")
    assert "repeat it unchanged" in p


def test_both_prompts_carry_the_glossary():
    """The glossary is why 'Konex' and 'food trucks' survive translation.

    Losing it in the auto path would show up as proper nouns quietly being
    translated, which reads as a worse model rather than a missing prompt.
    """
    g = "\nGlossary:\n- Konex: keep verbatim"
    assert "Konex" in SYSTEM_PROMPT_AUTO.format(target="Spanish", glossary=g)
    assert "Konex" in SYSTEM_PROMPT.format(source="English", target="Spanish", glossary=g)


def test_the_demo_config_of_generic_stages_loads():
    cfg = Config.load("demo/salas.yaml")
    assert len(cfg.sessions) == 4
    for s in cfg.sessions:
        assert s.source_language == AUTO
        assert len(s.targets) == 6, f"{s.id} lost a language"
