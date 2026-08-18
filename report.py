"""Markdown report generator for a finished campaign."""

import os
from collections import Counter, defaultdict

from storage.db import Storage

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

    lines: list[str] = []
    lines.extend(_render_header(campaign, attempts))
    lines.extend(_render_summary(attempts))
    lines.extend(_render_by_subagent(attempts))
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


def _render_summary(attempts: list[dict]) -> list[str]:
    counts = _verdict_counts(attempts)
    total = len(attempts)
    successes = counts.get("success", 0)
    rate = f"{successes / total:.1%}" if total else "n/a"

    lines = [
        "## Summary",
        "",
        f"**{successes} of {total} attempts succeeded ({rate} success rate).**",
        "",
    ]
    if counts:
        lines += ["| Verdict | Count |", "| --- | --- |"]
        for verdict in ("success", "failure", "unclear", "unjudged"):
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
        "| Sub-agent | Attempts | Success | Failure | Unclear | Success rate |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for sub_agent_type in sorted(grouped):
        group = grouped[sub_agent_type]
        counts = _verdict_counts(group)
        successes = counts.get("success", 0)
        lines.append(
            f"| `{sub_agent_type}` | {len(group)} | {successes} | "
            f"{counts.get('failure', 0)} | {counts.get('unclear', 0)} | "
            f"{successes / len(group):.1%} |"
        )
    lines.append("")
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
        f"### Attempt {attempt['id']} — `{attempt['sub_agent_type']}` — "
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
