"""One microphone per stage.

Two sockets pushing into the same session interleave two copies of the room
into one audio stream. Nothing reports that as an error: the model simply gets
worse. Observed live, a second capture tab left open pushed transcription
latency from about a second to eight and then stopped captions altogether,
while every counter still read healthy -- no dropped audio, no errors, state
'running'. A test is the only cheap place to notice that.
"""

from fastapi.testclient import TestClient

from calandria.api import create_app
from calandria.config import Config

FRAME = b"\x00\x00" * 160  # 10 ms of silence at 16 kHz, the shape /ws/ingest wants


def _client(source=None, sid="sala"):
    cfg = Config.model_validate({
        "stt": {"backend": "fake"},
        "translation": {"enabled": False},
        "sessions": [{"id": sid, "source": source or {"type": "mic"},
                      "source_language": "es", "targets": ["en"]}],
    })
    return TestClient(create_app(cfg))


def test_a_second_audio_source_displaces_the_first():
    with _client() as client:
        with client.websocket_connect("/ws/ingest?session=sala") as first:
            first.send_bytes(FRAME)
            with client.websocket_connect("/ws/ingest?session=sala") as second:
                second.send_bytes(FRAME)
                # The newest wins: the first is closed rather than left to mix
                # its copy of the room into the same transcript.
                closed = first.receive()
                assert closed["type"] == "websocket.close"
                assert closed["code"] == 4409


def test_the_survivor_keeps_feeding_after_a_takeover():
    """A takeover must not damage the session it took over.

    This is the reconnect case: an operator's laptop drops its WiFi and comes
    back. If displacing the stale socket also broke the source, reconnecting
    would be worse than never having dropped.
    """
    with _client() as client:
        with client.websocket_connect("/ws/ingest?session=sala") as first:
            first.send_bytes(FRAME)
            with client.websocket_connect("/ws/ingest?session=sala") as second:
                for _ in range(10):
                    second.send_bytes(FRAME)
                assert first.receive()["type"] == "websocket.close"
        assert client.get("/api/sessions").json()["sessions"][0]["state"] == "running"


def test_a_third_source_displaces_only_the_current_one():
    """Closing a displaced socket must not vacate the slot the winner holds.

    If the loser's cleanup popped the session entry on its way out, a third
    connection would find the slot empty and start mixing with the second --
    the original bug, one connection later.
    """
    with _client() as client:
        with client.websocket_connect("/ws/ingest?session=sala") as first:
            with client.websocket_connect("/ws/ingest?session=sala") as second:
                assert first.receive()["type"] == "websocket.close"
                with client.websocket_connect("/ws/ingest?session=sala") as third:
                    third.send_bytes(FRAME)
                    assert second.receive()["code"] == 4409


def test_ingest_is_refused_for_a_session_that_is_not_a_microphone():
    src = {"type": "file", "path": "samples/charla-es.wav"}
    with _client(source=src, sid="archivo") as client:
        with client.websocket_connect("/ws/ingest?session=archivo") as ws:
            assert ws.receive()["code"] == 4400


def test_ingest_is_refused_for_a_session_that_does_not_exist():
    with _client() as client:
        with client.websocket_connect("/ws/ingest?session=fantasma") as ws:
            assert ws.receive()["code"] == 4404
