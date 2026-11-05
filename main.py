"""CLI entry point for the multi-agent red-team system."""

import argparse
import logging

from judge import Judge
from llm.base import LLMBackend
from llm.gemini import GeminiBackend
from llm.ollama import OllamaBackend
from orchestrator import Orchestrator
from storage.db import Storage
from subagents.base import SubAgent
from subagents.agentic import ToolHijackSubAgent
from subagents.basic import BasicInjectionSubAgent
from subagents.external import ExternalInjectionSubAgent
from subagents.leakage import SensitiveInfoDisclosureSubAgent, SystemPromptLeakageSubAgent
from targets import DEFAULT_CANARIES, DEFAULT_TARGET_SYSTEM

SUBAGENT_REGISTRY: dict[str, type[SubAgent]] = {
    "basic_direct": BasicInjectionSubAgent,
    "external_indirect": ExternalInjectionSubAgent,
    "system_prompt_leak": SystemPromptLeakageSubAgent,
    "secret_leak": SensitiveInfoDisclosureSubAgent,
    "tool_hijack": ToolHijackSubAgent,
}


def build_backend(spec: str) -> LLMBackend:
    """Construct a backend from a 'provider:model' string."""
    provider, model = spec.split(":", 1)
    if provider == "ollama":
        return OllamaBackend(model=model)
    elif provider == "gemini":
        return GeminiBackend(model=model)
    else:
        raise ValueError(
            f"Unknown provider: {provider!r}. Expected 'ollama' or 'gemini'."
        )


def build_subagents(names_csv: str, attacker: LLMBackend) -> list[SubAgent]:
    """Parse comma-separated sub-agent names, instantiate each with the attacker."""
    names = [name.strip() for name in names_csv.split(",")]
    subagents = []
    for name in names:
        if name not in SUBAGENT_REGISTRY:
            raise ValueError(
                f"Unknown sub-agent: {name!r}. "
                f"Available: {list(SUBAGENT_REGISTRY.keys())}"
            )
        cls = SUBAGENT_REGISTRY[name]
        subagents.append(cls(attacker_backend=attacker))
    return subagents


def load_target_system(path: str | None) -> str:
    """Read the target system prompt from a file, or return the default."""
    if path is None:
        return DEFAULT_TARGET_SYSTEM
    with open(path) as f:
        return f.read().strip()


def parse_canaries(pairs: list[str] | None, custom_prompt: bool) -> dict[str, str]:
    """Defaults apply to the default prompt; --canary KEY=VALUE overrides/extends them."""
    canaries = {} if custom_prompt else dict(DEFAULT_CANARIES)
    for pair in pairs or []:
        key, sep, value = pair.partition("=")
        if not sep or not key or not value:
            raise ValueError(f"--canary expects KEY=VALUE, got {pair!r}")
        canaries[key] = value
    return canaries


def parse_args() -> argparse.Namespace:
    """Define and parse CLI arguments."""
    parser = argparse.ArgumentParser(
        description="Run a multi-agent LLM red-teaming campaign."
    )
    parser.add_argument("--campaign-name", required=True, help="Human-readable campaign name.")
    parser.add_argument("--target", required=True, help="Target model spec, e.g. 'ollama:llama3:8b'.")
    parser.add_argument("--attacker", required=True, help="Attacker model spec.")
    parser.add_argument("--judge", default=None, help="Judge model spec. Defaults to attacker.")
    parser.add_argument("--sub-agents", required=True, help="Comma-separated sub-agent names.")
    parser.add_argument("--budget", type=int, required=True, help="Max attempts per campaign.")
    parser.add_argument("--db-path", default="campaigns.db", help="SQLite database path.")
    parser.add_argument("--target-system-prompt", default=None, help="Path to target system prompt file.")
    parser.add_argument(
        "--canary", action="append", metavar="KEY=VALUE",
        help="Canary planted in a custom target prompt (keys: system_prompt, secret). Repeatable.",
    )
    parser.add_argument("--max-tool-steps", type=int, default=4, help="Agent-loop step cap for tool-using sub-agents.")
    parser.add_argument("--output-report", default=None, help="If set, write Markdown report here.")
    parser.add_argument("--log-level", default="INFO", help="DEBUG, INFO, WARNING, ERROR, CRITICAL.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s %(name)s %(levelname)s: %(message)s",
    )
    logger = logging.getLogger(__name__)

    target_backend = build_backend(args.target)
    attacker_backend = build_backend(args.attacker)
    judge_backend = build_backend(args.judge) if args.judge else attacker_backend

    subagents = build_subagents(args.sub_agents, attacker_backend)
    judge = Judge(judge_backend=judge_backend)
    target_system_prompt = load_target_system(args.target_system_prompt)
    canaries = parse_canaries(args.canary, custom_prompt=args.target_system_prompt is not None)
    for sa in subagents:
        if sa.canary_key and sa.canary_key not in canaries:
            logger.warning(
                "%s has no %r canary configured; falling back to the LLM judge only "
                "(pass --canary %s=<value present in your prompt>)",
                sa.sub_agent_type, sa.canary_key, sa.canary_key,
            )

    with Storage(args.db_path) as storage:
        orch = Orchestrator(
            target_backend=target_backend,
            target_system_prompt=target_system_prompt,
            subagents=subagents,
            judge=judge,
            storage=storage,
            canaries=canaries,
            max_tool_steps=args.max_tool_steps,
        )
        campaign_id = orch.run_campaign(
            name=args.campaign_name,
            target_model_name=args.target,
            attacker_model_name=args.attacker,
            budget=args.budget,
        )
        logger.info("Campaign %d complete", campaign_id)
        print(f"Campaign id: {campaign_id}")

        if args.output_report:
            from report import generate_report
            generate_report(storage, campaign_id, args.output_report)
            print(f"Report written to: {args.output_report}")


if __name__ == "__main__":
    main()