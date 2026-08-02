"""Smoke test for sub-agents. Run: uv run python -m tests.test_subagents"""

import logging

from llm.gemini import GeminiBackend
from llm.ollama import OllamaBackend
from subagents.basic import BasicInjectionSubAgent

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s %(name)s %(levelname)s: %(message)s",
)


def test_basic_generate():
    attacker = OllamaBackend(model="dolphin-mistral")
    agent = BasicInjectionSubAgent(attacker_backend=attacker)
    spec = agent.generate()
    print(f"[Basic] payload={spec.payload!r}")
    print(f"[Basic] context={spec.context!r}")
    print(f"[Basic] criterion={spec.success_criterion!r}")
    assert spec.payload
    assert spec.success_criterion
    # basic direct injection should have no wrapping context
    assert spec.context is None
    
    
    
if __name__ == "__main__":
    test_basic_generate()
    print("BasicInjectionSubAgent OK.")