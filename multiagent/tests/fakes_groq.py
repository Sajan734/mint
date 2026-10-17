"""Scripted Groq: each script item is a GroqAnswer or an exception to raise."""

from buyer_agent.groq_client import GroqAnswer


class FakeGroq:
    def __init__(self, script: list) -> None:
        self._script = list(script)
        self.calls: list[tuple[str, str, str]] = []

    async def chat(self, model: str, system: str, user: str, *, key: str = "") -> GroqAnswer:
        self.calls.append((model, system, user))
        item = self._script.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item
