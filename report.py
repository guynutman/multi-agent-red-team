"""Markdown report generator for a finished campaign."""

import json
import os
from collections import Counter, defaultdict

from storage.db import Storage
from stats import fmt_rate
from taxonomy import OWASP_LLM_TOP10

MAX_TEXT_CHARS = 2000


def generate_report(
    storage: Storage,
    campaign_id: int,
    output_path: str,
) -> None:
    """
    Read a campaign's attempts and judgments from storage,
    write a Markdown report to output_path.
    """
    campaign = storage.get_campaign(campaign_id)
    attempts = storage.get_campaign_attempts(campaign_id)
    for a in attempts:
        a["turns"] = storage.get_attempt_turns(a["id"])

    lines: list[str] = []
    lines.extend(_render_header(campaign, attempts))
    lines.extend(_render_summary(attempts))
    lines.extend(_render_by_subagent(attempts))
    lines.extend(_render_owasp_coverage(attempts))
    lines.extend(_render_successes(attempts))
    lines.extend(_render_full_log(attempts))

    parent = os.path.dirname(output_path)
    if parent:
        os.makedirs(parent, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines).rstrip() + "\n")


# private helpers, each returning list[str]


def _verdict_counts(attempts: list[dict]) -> Counter:
    """Count verdicts, mapping the LEFT JOIN's NULL to 'unjudged'."""
    return Counter(a["verdict"] or "unjudged" for a in attempts)


def _render_header(campaign: dict, attempts: list[dict]) -> list[str]:
    return [
        f"# Red-Team Campaign Report: {campaign['name']}",
        "",
        "| Field | Value |",
        "| --- | --- |",
        f"| Campaign ID | {campaign['id']} |",
        f"| Target model | `{campaign['target_model']}` |",
        f"| Attacker model | `{campaign['attacker_model']}` |",
        f"| Budget | {campaign['budget']} |",
        f"| Attempts run | {len(attempts)} |",
        f"| Started | {campaign['started_at']} |",
        f"| Finished | {campaign['finished_at'] or '(not finished)'} |",
        f"| Status | {campaign['status']} |",
        "",
    ]


def _scored(attempts: list[dict]) -> list[dict]:
    """Attempts that reached a verdict (excludes errors and unjudged): the rate denominator."""
    return [a for a in attempts if a["verdict"] in ("success", "failure", "unclear")]


def _rate_cells(group: list[dict]) -> tuple[int, int, str]:
    scored = _scored(group)
    s = sum(a["verdict"] == "success" for a in scored)
    return s, len(scored), fmt_rate(s, len(scored))


def _render_summary(attempts: list[dict]) -> list[str]:
    counts = _verdict_counts(attempts)
    s, n, rate = _rate_cells(attempts)
    lines = [
        "## Summary",
        "",
        f"**{s} of {n} scored attempts succeeded: {rate}** "
        f"({len(attempts)} attempts run; {len(attempts) - n} errored or unjudged).",
        "",
        "*Rates are successes / scored attempts, with 95% Wilson confidence intervals.*",
        "",
    ]
    if counts:
        lines += ["| Verdict | Count |", "| --- | --- |"]
        for verdict in ("success", "failure", "unclear", "error", "unjudged"):
            if counts.get(verdict):
                lines.append(f"| {verdict} | {counts[verdict]} |")
        lines.append("")
    return lines


def _render_by_subagent(attempts: list[dict]) -> list[str]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for a in attempts:
        grouped[a["sub_agent_type"]].append(a)

    lines = ["## Results by Sub-Agent", ""]
    if not grouped:
        return lines + ["No attempts were recorded for this campaign.", ""]

    lines += [
        "| Sub-agent | Attempts | Success | Failure | Unclear | Error | Success rate [95% CI] |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for sub_agent_type in sorted(grouped):
        group = grouped[sub_agent_type]
        c = _verdict_counts(group)
        lines.append(
            f"| `{sub_agent_type}` | {len(group)} | {c.get('success', 0)} | {c.get('failure', 0)} | "
            f"{c.get('unclear', 0)} | {c.get('error', 0) + c.get('unjudged', 0)} | {_rate_cells(group)[2]} |"
        )
    lines.append("")
    return lines


def _render_owasp_coverage(attempts: list[dict]) -> list[str]:
    """One row per OWASP LLM Top 10 category, so untested categories are visible gaps."""
    grouped: dict[str, list[dict]] = defaultdict(list)
    for a in attempts:
        grouped[a.get("owasp_category") or "untagged"].append(a)

    lines = [
        "## OWASP LLM Top 10 (2025) Coverage",
        "",
        "| Category | Name | Attempts | Success | Success rate [95% CI] |",
        "| --- | --- | --- | --- | --- |",
    ]
    for cat in OWASP_LLM_TOP10.values():
        group = grouped.pop(cat.id, [])
        if group:
            s, _, rate = _rate_cells(group)
            lines.append(f"| {cat.id} | {cat.name} | {len(group)} | {s} | {rate} |")
        elif cat.out_of_scope:
            lines.append(f"| {cat.id} | {cat.name} | — | — | out of scope: {cat.out_of_scope} |")
        else:
            lines.append(f"| {cat.id} | {cat.name} | 0 | — | not tested |")
    for other in sorted(grouped):  # untagged (pre-taxonomy rows) or unknown ids
        group = grouped[other]
        s, _, rate = _rate_cells(group)
        lines.append(f"| {other} | — | {len(group)} | {s} | {rate} |")
    testable = [c for c in OWASP_LLM_TOP10.values() if not c.out_of_scope]
    tested = sum(1 for c in testable if any(a.get("owasp_category") == c.id for a in attempts))
    lines += ["", f"*{tested} of {len(testable)} black-box-testable categories exercised "
                  f"({len(OWASP_LLM_TOP10) - len(testable)} out of scope).*", ""]
    return lines


def _render_successes(attempts: list[dict]) -> list[str]:
    successes = [a for a in attempts if a["verdict"] == "success"]
    lines = ["## Successful Attacks", ""]
    if not successes:
        return lines + ["No attempts were judged successful.", ""]
    for a in successes:
        lines.extend(_render_attempt(a))
    return lines


def _render_full_log(attempts: list[dict]) -> list[str]:
    lines = ["## Full Attempt Log", ""]
    if not attempts:
        return lines + ["No attempts were recorded for this campaign.", ""]
    for a in attempts:
        lines.extend(_render_attempt(a))
    return lines


def _render_attempt(attempt: dict) -> list[str]:
    lines = [
        f"### Attempt {attempt['id']} — `{attempt['sub_agent_type']}`"
        f"{' (' + attempt['owasp_category'] + ')' if attempt.get('owasp_category') else ''} — "
        f"**{attempt['verdict'] or 'unjudged'}**",
        "",
        f"*Attempted at {attempt['attempted_at']} (retries: {attempt['retries']})*",
        "",
        "**Payload**",
        "",
        _fence(attempt["payload"]),
        "",
    ]
    if attempt["target_context"]:
        lines += ["**Injected context**", "", _fence(attempt["target_context"]), ""]
    if attempt.get("turns"):
        lines += [f"**Conversation** ({attempt['turns'][-1]['turn']} turns)", ""]
        for t in attempt["turns"]:
            lines += [f"*Turn {t['turn']} — {t['role']}*", "", _fence(t["content"]), ""]
        if attempt["reasoning"]:
            lines += ["**Judge reasoning**", "", attempt["reasoning"], ""]
        return lines
    if attempt.get("tool_trace"):
        lines += ["**Tool calls**", ""]
        calls = json.loads(attempt["tool_trace"])
        if not calls:
            lines.append("(none)")
        for i, c in enumerate(calls, 1):
            outcome = f"error: {c['error']}" if c["error"] else _truncate(c["result"], 200).replace("\n", " ⏎ ")
            lines.append(f"{i}. `{c['name']}` `{json.dumps(c['arguments'])[:300]}` → {outcome}")
        lines.append("")
    lines += ["**Target response**", "", _fence(attempt["target_response"]), ""]
    if attempt["reasoning"]:
        lines += ["**Judge reasoning**", "", attempt["reasoning"], ""]
    return lines


def _truncate(text: str | None, limit: int = MAX_TEXT_CHARS) -> str:
    """Clamp long payloads/responses so the report stays readable."""
    if not text:
        return "(empty)"
    if len(text) <= limit:
        return text
    return f"{text[:limit]}\n... [truncated, {len(text) - limit} chars omitted]"


def _fence(text: str | None) -> str:
    """Wrap text in a fenced block, neutralizing any fences it contains."""
    body = _truncate(text).replace("```", "'''")
    return f"```\n{body}\n```"


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Generate a campaign Markdown report.")
    parser.add_argument("campaign_id", type=int)
    parser.add_argument("--db", default="campaigns.db")
    parser.add_argument("-o", "--output", default=None)
    args = parser.parse_args()

    out = args.output or f"reports/campaign_{args.campaign_id}.md"
    with Storage(args.db) as store:
        generate_report(store, args.campaign_id, out)
    print(f"Wrote {out}")
