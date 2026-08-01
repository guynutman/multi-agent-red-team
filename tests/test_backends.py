"""Smoke tests for LLM backends. Run manually: uv run python -m tests.test_backends"""

import logging

from llm.entry import call_llm
from llm.gemini import GeminiBackend
from llm.ollama import OllamaBackend

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s %(name)s %(levelname)s: %(message)s",
)


def test_gemini():
    b = GeminiBackend()
    r = b.call([{"role": "user", "content": "Say hi in 3 words."}])
    print(f"[Gemini] text={r.text!r} retries={r.retries} latency_ms={r.latency_ms}")
    assert r.text
    assert r.latency_ms > 0


def test_ollama():
    b = OllamaBackend()
    r = b.call([{"role": "user", "content": "Say hi in 3 words."}])
    print(f"[Ollama] text={r.text!r} retries={r.retries} latency_ms={r.latency_ms}")
    assert r.text
    assert r.latency_ms > 0


if __name__ == "__main__":
    test_gemini()
    test_ollama()
    print("All backends OK.")
