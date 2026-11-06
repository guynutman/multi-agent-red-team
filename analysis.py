"""Cross-campaign analysis: success-rate distributions with confidence intervals.

Pools every attempt in a database (or selected campaigns) and reports, per target
model x OWASP category x sub-agent:
  - success rate with a 95% Wilson CI (errors excluded from the denominator)
  - error rate (attacker refusals / malformed output / backend failures)
  - pairwise model comparisons per category (two-proportion z-test)
  - distributions: output tokens, latency, turns used (multi-turn), RAG retrieval
Exports a flat CSV for pandas / plotting.

Usage:
  uv run python analysis.py --db campaigns.db -o reports/analysis.md --csv reports/attempts.csv
  uv run python analysis.py --db campaigns.db --campaigns 3 4 5
"""

import argparse
import csv
import json
import os
from collections import defaultdict
from itertools import combinations

from stats import fmt_rate, quantiles, two_proportion_p
from storage.db import Storage
from taxonomy import OWASP_LLM_TOP10

SCORED = ("success", "failure", "unclear")
CSV_FIELDS = [
    "campaign_id", "campaign", "target_model", "attacker_model", "sub_agent_type", "owasp_category",
    "attempt_index", "seed", "verdict", "success", "latency_ms", "output_tokens", "target_calls",
    "retries", "turns_used", "retrieved", "amplification", "exfiltrated",
]


def load_rows(storage: Storage, campaign_ids: list[int] | None) -> list[dict]:
    campaigns = {c["id"]: c for c in storage.list_campaigns()}
    ids = campaign_ids or list(campaigns)
    rows = []
    for cid in ids:
        c = campaigns[cid]
        for a in storage.get_campaign_attempts(cid):
            extra = json.loads(a["extra"]) if a.get("extra") else {}
            rows.append({
                "campaign_id": cid, "campaign": c["name"], "target_model": c["target_model"],
                "attacker_model": c["attacker_model"], "sub_agent_type": a["sub_agent_type"],
                "owasp_category": a.get("owasp_category") or "untagged",
                "attempt_index": a.get("attempt_index"), "seed": a.get("seed"),
                "verdict": a["verdict"] or "unjudged", "success": int(a["verdict"] == "success"),
                "latency_ms": a.get("latency_ms"), "output_tokens": a.get("output_tokens"),
                "target_calls": a.get("target_calls"), "retries": a.get("retries"),
                "turns_used": extra.get("turns_used"), "retrieved": extra.get("retrieved"),
                "amplification": extra.get("amplification"), "exfiltrated": extra.get("exfiltrated"),
            })
    return rows


def _group(rows, *keys):
    g = defaultdict(list)
    for r in rows:
        g[tuple(r[k] for k in keys)].append(r)
    return g


def _counts(group):
    scored = [r for r in group if r["verdict"] in SCORED]
    return sum(r["success"] for r in scored), len(scored), len(group) - len(scored)


def _q(values):
    vals = [v for v in values if v is not None]
    if not vals:
        return "—"
    p50, p90, p99 = quantiles(vals)
    return f"{p50:.0f} / {p90:.0f} / {p99:.0f}"


def render(rows: list[dict]) -> list[str]:
    models = sorted({r["target_model"] for r in rows})
    lines = [
        "# Cross-Campaign Analysis",
        "",
        f"{len(rows)} attempts across {len({r['campaign_id'] for r in rows})} campaigns; "
        f"target models: {', '.join(f'`{m}`' for m in models)}.",
        "",
        "Rates are successes / scored attempts with 95% Wilson CIs. Errors (attacker refusals, "
        "malformed output, backend failures) are excluded from the rate and reported separately.",
        "",
        "## Success rate by target model and OWASP category",
        "",
        "| Target | Category | n scored | Success rate [95% CI] | Errors |",
        "| --- | --- | --- | --- | --- |",
    ]
    for (model, cat), g in sorted(_group(rows, "target_model", "owasp_category").items()):
        s, n, err = _counts(g)
        name = OWASP_LLM_TOP10[cat].name if cat in OWASP_LLM_TOP10 else cat
        lines.append(f"| `{model}` | {cat} {name} | {n} | {fmt_rate(s, n)} | {err} |")

    lines += ["", "## Success rate by sub-agent", "",
              "| Target | Sub-agent | n scored | Success rate [95% CI] | Error rate |",
              "| --- | --- | --- | --- | --- |"]
    for (model, sa), g in sorted(_group(rows, "target_model", "sub_agent_type").items()):
        s, n, err = _counts(g)
        lines.append(f"| `{model}` | `{sa}` | {n} | {fmt_rate(s, n)} | {err / len(g):.0%} |")

    if len(models) > 1:
        lines += ["", "## Model comparisons (two-proportion z-test, per category)", "",
                  "| Category | Model A | Model B | Rate A | Rate B | p-value |",
                  "| --- | --- | --- | --- | --- | --- |"]
        by_cat = _group(rows, "owasp_category")
        for (cat,), g in sorted(by_cat.items()):
            per_model = _group(g, "target_model")
            for (a,), (b,) in combinations(sorted(per_model), 2):
                sa_, na, _ = _counts(per_model[(a,)])
                sb, nb, _ = _counts(per_model[(b,)])
                p = two_proportion_p(sa_, na, sb, nb)
                lines.append(f"| {cat} | `{a}` | `{b}` | {fmt_rate(sa_, na)} | {fmt_rate(sb, nb)} | {p:.3g} |")
        lines += ["", "*p-values are uncorrected; with many comparisons, apply Bonferroni or Holm.*"]

    lines += ["", "## Distributions (p50 / p90 / p99)", "",
              "| Target | Sub-agent | Output tokens | Latency ms | Turns used |",
              "| --- | --- | --- | --- | --- |"]
    for (model, sa), g in sorted(_group(rows, "target_model", "sub_agent_type").items()):
        lines.append(f"| `{model}` | `{sa}` | {_q(r['output_tokens'] for r in g)} | "
                     f"{_q(r['latency_ms'] for r in g)} | {_q(r['turns_used'] for r in g)} |")

    rag = [r for r in rows if r["sub_agent_type"] == "rag_poisoning" and r["verdict"] in SCORED]
    if rag:
        lines += ["", "## RAG attack chain (LLM08)", "",
                  "| Target | n | Retrieved [95% CI] | Hijacked given retrieved [95% CI] |",
                  "| --- | --- | --- | --- |"]
        for (model,), g in sorted(_group(rag, "target_model").items()):
            ret = [r for r in g if r["retrieved"]]
            lines.append(f"| `{model}` | {len(g)} | {fmt_rate(len(ret), len(g))} | "
                         f"{fmt_rate(sum(r['success'] for r in ret), len(ret))} |")
    return lines + [""]


def write_csv(rows: list[dict], path: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        w.writeheader()
        w.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyse campaigns: rates, CIs, distributions.")
    parser.add_argument("--db", default="campaigns.db")
    parser.add_argument("--campaigns", type=int, nargs="*", help="Campaign ids (default: all).")
    parser.add_argument("-o", "--output", default="reports/analysis.md")
    parser.add_argument("--csv", default=None, help="Also export one row per attempt.")
    args = parser.parse_args()

    with Storage(args.db) as storage:
        rows = load_rows(storage, args.campaigns)
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        f.write("\n".join(render(rows)))
    print(f"Wrote {args.output} ({len(rows)} attempts)")
    if args.csv:
        write_csv(rows, args.csv)
        print(f"Wrote {args.csv}")


if __name__ == "__main__":
    main()
