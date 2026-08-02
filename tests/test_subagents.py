"""Smoke test for sub-agents. Run: uv run python -m tests.test_subagents"""

import logging

from llm.ollama import OllamaBackend
from subagents.basic import BasicInjectionSubAgent
from subagents.external import ExternalInjectionSubAgent

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
    
def test_external_generate():
    attacker = OllamaBackend(model="dolphin-mistral")
    agent = ExternalInjectionSubAgent(attacker_backend=attacker)
    spec = agent.generate()
    context_preview = spec.context[:200] if spec.context else None
    print(f"[External] payload={spec.payload!r}")
    print(f"[External] context (first 200)={context_preview!r}")
    print(f"[External] criterion={spec.success_criterion!r}")
    assert spec.payload
    assert spec.context  # external MUST have wrapping context
    assert spec.success_criterion
    
if __name__ == "__main__":
    test_basic_generate()
    test_external_generate()
    print("Sub-agents OK.")