"""The bus must never let one slow subscriber affect anybody else.

A phone on bad conference wifi is the normal case, not the edge case. If a
subscriber that cannot keep up could apply back-pressure to a publisher, one bad
connection in row 12 would stall captions for the whole room.
"""

import asyncio

import pytest

from calandria.bus import create_bus
from calandria.bus.memory import QUEUE_MAX, InMemoryBus


class Listener:
    """A subscriber running in the background, collecting into a list.

    `bus.subscribe()` returns a lazy async generator, so it does not register
    itself until something iterates it. This waits for that to have happened
    before the test publishes anything.
    """

    def __init__(self, bus, topic, replay=0):
        self.received: list[dict] = []
        self._gen = bus.subscribe(topic, replay=replay)
        self._ready = asyncio.Event()
        self._task = asyncio.create_task(self._run())

    async def _run(self):
        agen = self._gen.__aiter__()
        first = asyncio.ensure_future(agen.__anext__())
        # One event-loop turn is enough for subscribe() to have registered.
        await asyncio.sleep(0)
        self._ready.set()
        try:
            self.received.append(await first)
            async for msg in agen:
                self.received.append(msg)
        except (asyncio.CancelledError, StopAsyncIteration):
            pass

    async def ready(self):
        await self._ready.wait()
        await asyncio.sleep(0)

    async def wait_for(self, n, timeout=2.0):
        async def poll():
            while len(self.received) < n:
                await asyncio.sleep(0.005)
        await asyncio.wait_for(poll(), timeout)
        return self.received

    async def stop(self):
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass


async def test_a_subscriber_receives_what_is_published():
    bus = InMemoryBus()
    listener = Listener(bus, "t")
    await listener.ready()
    await bus.publish("t", {"n": 1})
    await bus.publish("t", {"n": 2})
    assert await listener.wait_for(2) == [{"n": 1}, {"n": 2}]
    await listener.stop()


async def test_every_subscriber_gets_its_own_copy():
    bus = InMemoryBus()
    a, b = Listener(bus, "t"), Listener(bus, "t")
    await a.ready(); await b.ready()
    await bus.publish("t", {"n": 1})
    assert await a.wait_for(1) == await b.wait_for(1) == [{"n": 1}]
    await a.stop(); await b.stop()


async def test_replay_lets_a_late_joiner_catch_up():
    bus = InMemoryBus(history=10)
    for i in range(5):
        await bus.publish("t", {"n": i})
    listener = Listener(bus, "t", replay=3)
    assert [m["n"] for m in await listener.wait_for(3)] == [2, 3, 4]
    await listener.stop()


async def test_history_is_capped():
    bus = InMemoryBus(history=3)
    for i in range(10):
        await bus.publish("t", {"n": i})
    assert [m["n"] for m in bus.history("t")] == [7, 8, 9]


async def test_publishing_never_blocks_on_a_stalled_subscriber():
    """The point of the whole design: a subscriber that stops reading loses its
    own oldest messages, and the publisher is not slowed down at all."""
    bus = InMemoryBus()
    gen = bus.subscribe("t")
    agen = gen.__aiter__()
    pending = asyncio.ensure_future(agen.__anext__())   # registers, then reads no more
    await asyncio.sleep(0)

    for i in range(QUEUE_MAX * 3):                      # far more than the queue holds
        await asyncio.wait_for(bus.publish("t", {"n": i}), timeout=0.5)

    assert bus.history("t", 1)[0]["n"] == QUEUE_MAX * 3 - 1   # publisher unharmed
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending          # let the cancellation land before closing
    await gen.aclose()


async def test_unsubscribing_cleans_up():
    bus = InMemoryBus()
    listener = Listener(bus, "t")
    await listener.ready()
    await bus.publish("t", {"n": 1})
    await listener.wait_for(1)
    await listener.stop()
    await asyncio.sleep(0.01)
    assert not bus._subs.get("t"), "a closed subscriber must not leak its queue"


def test_factory_accepts_memory_and_rejects_nonsense():
    assert isinstance(create_bus("memory"), InMemoryBus)
    with pytest.raises(ValueError, match="unknown bus"):
        create_bus("kafka://nope")
