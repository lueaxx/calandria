"""How translation handles failure.

Two mistakes are possible and they pull in opposite directions: dropping a line
that would have succeeded a second later, and showing a line so late that it
contradicts what the speaker is now saying. These tests pin the line between
them.
"""

import asyncio

import pytest

from calandria.transient import is_transient as _is_transient
from calandria.translate.gemini import TranslationFanout


class FlakyTranslator:
    """Fails a set number of times, then succeeds."""

    def __init__(self, failures: int, exc: Exception):
        self.remaining = failures
        self.exc = exc
        self.calls = 0

    async def translate(self, text: str) -> str:
        self.calls += 1
        if self.remaining > 0:
            self.remaining -= 1
            raise self.exc
        return f"translated: {text}"


def rate_limited() -> Exception:
    return RuntimeError(
        "429 RESOURCE_EXHAUSTED. Quota exceeded for metric: "
        "generate_content_free_tier_requests, limit: 15"
    )


def unavailable() -> Exception:
    return RuntimeError("503 UNAVAILABLE. This model is currently experiencing high demand.")


def bad_request() -> Exception:
    return RuntimeError("400 INVALID_ARGUMENT. Request contains an invalid argument.")


# ------------------------------------------------------- classifying failures

@pytest.mark.parametrize("exc", [rate_limited(), unavailable(),
                                 RuntimeError("500 internal"), RuntimeError("504 timeout")])
def test_transient_failures_are_recognised(exc):
    assert _is_transient(exc)


def test_a_bad_request_is_not_transient():
    # Retrying it cannot help, and it would burn the budget a recoverable
    # error was going to need.
    assert not _is_transient(bad_request())


def test_a_status_code_attribute_is_enough():
    exc = RuntimeError("something opaque")
    exc.code = 429
    assert _is_transient(exc)


# ------------------------------------------------------------------ retrying

async def test_a_rate_limited_line_is_retried_and_delivered():
    t = FlakyTranslator(failures=2, exc=rate_limited())
    fanout = TranslationFanout({"es": t}, max_concurrent=2, retry_budget_seconds=5)
    assert await fanout.translate("es", "hello") == "translated: hello"
    assert t.calls == 3


async def test_a_permanent_failure_is_not_retried():
    t = FlakyTranslator(failures=99, exc=bad_request())
    fanout = TranslationFanout({"es": t}, retry_budget_seconds=5)
    with pytest.raises(RuntimeError, match="400"):
        await fanout.translate("es", "hello")
    assert t.calls == 1, "a request that cannot succeed must be attempted once"


async def test_retrying_stops_at_the_deadline():
    """A subtitle that arrives after the speaker has moved on is worse than no
    subtitle, so the budget is a wall clock, not an attempt count."""
    t = FlakyTranslator(failures=99, exc=rate_limited())
    fanout = TranslationFanout({"es": t}, retry_budget_seconds=0.9)
    start = asyncio.get_running_loop().time()
    with pytest.raises(RuntimeError, match="429"):
        await fanout.translate("es", "hello")
    elapsed = asyncio.get_running_loop().time() - start
    assert elapsed < 3.0, "gave up far later than the budget allowed"
    assert 1 < t.calls < 10, f"expected a few attempts, made {t.calls}"


async def test_a_failure_in_one_language_does_not_block_another():
    good = FlakyTranslator(failures=0, exc=rate_limited())
    bad = FlakyTranslator(failures=99, exc=bad_request())
    fanout = TranslationFanout({"es": good, "pt": bad}, retry_budget_seconds=1)

    results = await asyncio.gather(
        fanout.translate("es", "hola"),
        fanout.translate("pt", "hola"),
        return_exceptions=True,
    )
    assert results[0] == "translated: hola"
    assert isinstance(results[1], RuntimeError)


async def test_concurrency_is_bounded():
    """The semaphore has to actually hold, or a burst of finalized lines opens
    one connection per line and makes the rate limiting worse."""
    live = 0
    peak = 0

    class Counting:
        async def translate(self, text):
            nonlocal live, peak
            live += 1
            peak = max(peak, live)
            await asyncio.sleep(0.05)
            live -= 1
            return text

    fanout = TranslationFanout({"es": Counting()}, max_concurrent=2)
    await asyncio.gather(*(fanout.translate("es", f"line {i}") for i in range(10)))
    assert peak <= 2
