"""Scripted LLM backend for offline tests."""

from collections.abc import Callable

from llm.base import LLMResponse, Message


class FakeBackend:
    """Returns canned replies. `reply` is a fixed string or a function of the messages."""

    def __init__(self, reply: str | Callable[[list[Message]], str]):
        self.reply = reply
        self.calls: list[list[Message]] = []

    def call(self, messages: list[Message], **config) -> LLMResponse:
        self.calls.append(messages)
        text = self.reply(messages) if callable(self.reply) else self.reply
        return LLMResponse(text=text, raw={}, retries=0, latency_ms=0)
