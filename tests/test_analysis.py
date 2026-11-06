"""Offline tests for stats.py and analysis.py."""

import math

from analysis import load_rows, render, write_csv
from stats import quantiles, two_proportion_p, wilson
from storage.db import Storage


def test_wilson_known_values():
    lo, hi = wilson(1, 2)
    assert round(lo, 3) == 0.095 and round(hi, 3) == 0.905
    assert wilson(0, 10)[0] == 0.0 and wilson(10, 10)[1] == 1.0
    assert wilson(0, 0) == (0.0, 1.0)


def test_two_proportion_and_quantiles():
    assert two_proportion_p(50, 100, 50, 100) == 1.0
    assert two_proportion_p(90, 100, 10, 100) < 1e-10
    assert math.isnan(two_proportion_p(1, 0, 1, 1))
    assert quantiles([1, 2, 3, 4, 5], (0.5,)) == [3]


def _seed_two_models() -> Storage:
    st = Storage(":memory:")
    for model, wins in (("ollama:a", 8), ("ollama:b", 2)):
        cid = st.create_campaign("c", model, "atk", 11)
        for i in range(10):
            aid = st.record_attempt(cid, "basic_direct", "p", None, "r", 0, owasp_category="LLM01",
                                    attempt_index=i, output_tokens=10 * i, latency_ms=100 + i)
            st.record_judgment(aid, "success" if i < wins else "failure", "x")
        aid = st.record_attempt(cid, "basic_direct", "", None, "", 0, owasp_category="LLM01", attempt_index=10)
        st.record_judgment(aid, "error", "[error:generate] refusal")
    return st


def test_render_pools_campaigns_and_compares_models(tmp_path):
    st = _seed_two_models()
    rows = load_rows(st, None)
    assert len(rows) == 22
    text = "\n".join(render(rows))
    assert "| `ollama:a` | LLM01 Prompt Injection | 10 | 80.0% [49.0%–94.3%] | 1 |" in text
    assert "| `ollama:b` | LLM01 Prompt Injection | 10 | 20.0% [5.7%–51.0%] | 1 |" in text
    assert "## Model comparisons" in text and "| LLM01 | `ollama:a` | `ollama:b` |" in text
    write_csv(rows, str(tmp_path / "a.csv"))
    assert (tmp_path / "a.csv").read_text().count("\n") == 23
