"""End-to-end orchestrator smoke test. Run: uv run pytest tests/test_orchestrator.py"""

import logging

from judge import Judge
from llm.ollama import OllamaBackend
from orchestrator import Orchestrator
from storage.db import Storage
from subagents.basic import BasicInjectionSubAgent
from subagents.external import ExternalInjectionSubAgent

import pytest

pytestmark = pytest.mark.ollama  # live-model test; auto-skipped without a server

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s: %(message)s",
)

from targets import DEFAULT_TARGET_SYSTEM as TARGET_SYSTEM


def test_end_to_end():
    attacker = OllamaBackend(model="dolphin-mistral")
    target = OllamaBackend(model="llama3:8b")
    judge = Judge(judge_backend=OllamaBackend(model="dolphin-mistral"))
    storage = Storage(":memory:")

    subagents = [
        BasicInjectionSubAgent(attacker_backend=attacker),
        ExternalInjectionSubAgent(attacker_backend=attacker),
    ]

    orch = Orchestrator(
        target_backend=target,
        target_system_prompt=TARGET_SYSTEM,
        subagents=subagents,
        judge=judge,
        storage=storage,
    )

    campaign_id = orch.run_campaign(
        name="e2e_smoke",
        target_model_name="llama3:8b",
        attacker_model_name="dolphin-mistral",
        budget=4,
    )

    attempts = storage.get_campaign_attempts(campaign_id)
    print(f"\n=== Campaign {campaign_id} complete: {len(attempts)} attempts ===")
    for a in attempts:
        print(f"  #{a['id']} type={a['sub_agent_type']} verdict={a['verdict']}")

    assert len(attempts) <= 4
    storage.close()


if __name__ == "__main__":
    test_end_to_end()
    print("Orchestrator OK.")