"""Configuration is validated at startup so that an operator finds out about a
bad combination before the doors open, not during a keynote."""

import pytest
from pydantic import ValidationError

from calandria.config import Config, SessionConfig, SttConfig


def test_smart_mode_and_word_timestamps_are_rejected():
    # Verified against the live API, which closes the socket with
    # 1007 "Transcription mode SMART is incompatible with word timestamps".
    with pytest.raises(ValidationError, match="1007"):
        SttConfig(mode="SMART", word_timestamp=True)


def test_verbatim_mode_allows_word_timestamps():
    assert SttConfig(mode="VERBATIM", word_timestamp=True).word_timestamp


def test_overlap_must_be_shorter_than_the_rotation_interval():
    with pytest.raises(ValidationError, match="overlap_seconds"):
        SttConfig(rotate_after_seconds=10, overlap_seconds=10)


def test_translating_a_language_into_itself_is_dropped():
    # It would cost money to produce a copy of what we already have.
    s = SessionConfig(id="a", source_language="es", targets=["es", "en"])
    assert s.targets == ["en"]


def test_session_title_defaults_to_its_id():
    assert SessionConfig(id="track-3").title == "track-3"


def test_duplicate_session_ids_are_rejected():
    with pytest.raises(ValidationError, match="duplicate session id"):
        Config(sessions=[{"id": "a"}, {"id": "a"}])


def test_file_source_requires_a_path():
    with pytest.raises(ValidationError, match="requires 'path'"):
        SessionConfig(id="a", source={"type": "file"})


def test_stream_source_requires_a_url():
    with pytest.raises(ValidationError, match="requires 'url'"):
        SessionConfig(id="a", source={"type": "stream"})


def test_empty_config_is_valid_and_fully_defaulted():
    cfg = Config()
    assert cfg.stt.backend == "gemini"
    assert cfg.bus == "memory"
    assert cfg.features.dashboard is True
    assert cfg.sessions == []


def test_environment_overrides_the_file(monkeypatch, tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("server:\n  port: 8080\nbus: memory\n", encoding="utf-8")
    monkeypatch.setenv("CALANDRIA_PORT", "9999")
    monkeypatch.setenv("CALANDRIA_BUS", "redis://elsewhere:6379")
    monkeypatch.setenv("CALANDRIA_STT_BACKEND", "fake")
    cfg = Config.load(p)
    assert (cfg.server.port, cfg.bus, cfg.stt.backend) == (
        9999, "redis://elsewhere:6379", "fake",
    )


def test_missing_config_file_is_an_error_not_a_silent_default():
    with pytest.raises(FileNotFoundError):
        Config.load("definitely/not/here.yaml")
