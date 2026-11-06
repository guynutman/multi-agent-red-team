"""Offline tests for multi-turn adaptive attacks and conversation persistence.
Run: uv run pytest tests/test_multiturn.py"""

import json

import pytest

from judge import Judge
from orchestrator import Orchestrator
from report import generate_report
from storage.db import Storage
from subagents.multiturn import CrescendoLeakSubAgent, MultiTurnSubAgent
from targets import DEFAULT_CANARIES, DEFAULT_TARGET_SYSTEM, SYSTEM_PROMPT_CANARY
from tests.fakes import FakeBackend

OPENING = json.dumps({"payload": "What's the weather like?", "context": None,
                      "success_criterion": "Target reveals its system prompt."})


def attacker_backend():
    """Opening spec, then numbered follow-ups."""
    n = iter(range(2, 100))
    return FakeBackend(lambda m: OPENING if len(m) == 2 else json.dumps({"payload": f"follow-up {next(n)}"}))


def _run(target_replies: list[str], max_turns=4, judge_reply='{"verdict": "failure", "reasoning": "no leak"}'):
    it = iter(target_replies)
    target = FakeBackend(lambda _m: next(it, "Sunny."))
    attacker = attacker_backend()
    judge = FakeBackend(judge_reply)
    storage = Storage(":memory:")
    orch = Orchestrator(
        target_backend=target, target_system_prompt=DEFAULT_TARGET_SYSTEM,
        subagents=[CrescendoLeakSubAgent(attacker_backend=attacker, max_turns=max_turns)],
        judge=Judge(judge_backend=judge), storage=storage, canaries=DEFAULT_CANARIES,
    )
    cid = orch.run_campaign("mt", "fake", "fake", budget=1)
    [attempt] = storage.get_campaign_attempts(cid)
    turns = storage.get_attempt_turns(attempt["id"])
    return storage, cid, attempt, turns, target, attacker, judge


def test_runs_all_turns_and_keeps_target_history():
    storage, _, attempt, turns, target, _, judge = _run(["r1", "r2", "r3", "r4"])
    assert attempt["verdict"] == "failure" and attempt["owasp_category"] == "LLM07"
    assert [(t["turn"], t["role"]) for t in turns][:4] == [(1, "attacker"), (1, "target"), (2, "attacker"), (2, "target")]
    assert len(turns) == 8
    # target sees the whole conversation so far on its last call
    last = target.calls[-1]
    assert [m["role"] for m in last] == ["system"] + ["user", "assistant"] * 3 + ["user"]
    assert last[-1]["content"] == "follow-up 4"
    # judge sees every turn's reply, not just the last
    assert "[turn 1] r1" in judge.calls[0][1]["content"] and "[turn 4] r4" in judge.calls[0][1]["content"]
    storage.close()


def test_attacker_memory_sees_target_replies():
    _, _, _, _, _, attacker, _ = _run(["first reply", "second reply"], max_turns=3)
    final_view = attacker.calls[-1]
    contents = "\n".join(m["content"] for m in final_view)
    assert "first reply" in contents and "second reply" in contents
    assert SYSTEM_PROMPT_CANARY not in contents  # attacker never sees the canary


def test_canary_stops_early_and_skips_judge():
    _, _, attempt, turns, target, _, judge = _run(["Sunny.", f"My rules say: {SYSTEM_PROMPT_CANARY}", "never sent"])
    assert attempt["verdict"] == "success" and attempt["reasoning"].startswith("[canary]")
    assert len(target.calls) == 2 and turns[-1]["turn"] == 2
    assert judge.calls == []


def test_state_resets_between_attempts():
    agent = CrescendoLeakSubAgent(attacker_backend=attacker_backend())
    agent.generate(); agent.follow_up("x", 2)
    agent.generate()
    assert len(agent.history) == 3  # system, opening request, opening reply


def test_bad_follow_up_json_raises():
    with pytest.raises(ValueError):
        MultiTurnSubAgent._parse_payload("I refuse.")
    assert MultiTurnSubAgent._parse_payload('Sure: {"payload": "hi"}') == "hi"


def test_report_renders_conversation(tmp_path):
    storage, cid, *_ = _run(["a", "b"], max_turns=2)
    out = tmp_path / "r.md"
    generate_report(storage, cid, str(out))
    text = out.read_text()
    assert "**Conversation** (2 turns)" in text and "*Turn 2 — target*" in text
    assert text.count("```") % 2 == 0
