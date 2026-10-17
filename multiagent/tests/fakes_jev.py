"""Scripted Jev for table tests: each script item is a JevAnswer or an exception to raise."""

from buyer_agent.config import JEV_MODEL_PIN
from buyer_agent.jev_client import JevAnswer


def answer(**nouls: float) -> JevAnswer:
    return JevAnswer(model=JEV_MODEL_PIN, nouls=dict(nouls), latency_ms=1, timestamp="t")


class FakeJev:
    def __init__(self, script: list) -> None:
        self._script = list(script)
        self.calls: list[tuple[dict, dict, str]] = []

    async def ask(self, state: dict, questions: dict, *, key: str = "") -> JevAnswer:
        self.calls.append((state, questions, key))
        item = self._script.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


def run_sync(coro):
    """Drive a coroutine that never truly suspends. Avoids creating an event loop: on Windows a
    loop opens a socketpair, which the conftest network guard blocks."""
    try:
        coro.send(None)
    except StopIteration as done:
        return done.value
    raise RuntimeError("coroutine suspended; use a real loop")
