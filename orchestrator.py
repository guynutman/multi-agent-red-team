"""Campaign scheduler: dispatch, concurrency, error isolation, persistence.

Attack logic lives in the sub-agents (generate -> execute -> evaluate); this module
never branches on attack type.
"""

import copy
import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor

from judge import Judge
from llm.base import LLMBackend
from oracles import canary_in  # noqa: F401  (re-exported for callers/tests)
from storage.db import Storage
from subagents.base import SubAgent, TargetContext

logger = logging.getLogger(__name__)


class Orchestrator:
    """Runs a red-teaming campaign end-to-end."""

    def __init__(
        self,
        target_backend: LLMBackend,
        target_system_prompt: str,
        subagents: list[SubAgent],
        judge: Judge,
        storage: Storage,
        canaries: dict[str, str] | None = None,
        max_tool_steps: int = 4,
        workers: int = 1,
        seed: int | None = None,
    ):
        """
        target_backend: LLM being attacked
        target_system_prompt: the target's hidden system prompt (defines its constraints)
        subagents: SubAgent instances to rotate through (round-robin)
        judge: evaluator used when no deterministic oracle applies
        storage: SQLite persistence layer (thread-safe)
        canaries: canary_key -> value planted in the target system prompt
        max_tool_steps: agent-loop cap for tool-using sub-agents
        workers: attempts run concurrently (match OLLAMA_NUM_PARALLEL on the server)
        seed: base seed; attempt i uses seed + i for attacker and target calls
        """
        self.target_backend = target_backend
        self.target_system_prompt = target_system_prompt
        self.subagents = subagents
        self.judge = judge
        self.storage = storage
        self.canaries = canaries or {}
        self.max_tool_steps = max_tool_steps
        self.workers = max(1, workers)
        self.seed = seed
        self._done = 0
        self._lock = threading.Lock()

    def run_campaign(
        self,
        name: str,
        target_model_name: str,
        attacker_model_name: str,
        budget: int,
    ) -> int:
        """Execute `budget` attempts round-robin across sub-agents. Returns the campaign_id."""
        campaign_id = self.storage.create_campaign(name, target_model_name, attacker_model_name, budget)
        self._done = 0
        try:
            if self.workers == 1:
                for i in range(budget):
                    self._run_attempt(campaign_id, i, budget)
            else:
                with ThreadPoolExecutor(max_workers=self.workers) as pool:
                    list(pool.map(lambda i: self._run_attempt(campaign_id, i, budget), range(budget)))
            self.storage.finish_campaign(campaign_id, "completed")
        except Exception as e:
            logger.error("Campaign failed: %s", e)
            self.storage.finish_campaign(campaign_id, "aborted")
            raise
        return campaign_id

    def _run_attempt(self, campaign_id: int, index: int, budget: int) -> None:
        """One attempt. Any failure is recorded as an 'error' attempt, never raised."""
        # Fresh copy per attempt: sub-agents hold per-attack state (e.g. multi-turn memory).
        agent = copy.copy(self.subagents[index % len(self.subagents)])
        seed = None if self.seed is None else self.seed + index
        agent.seed = seed
        ctx = TargetContext(
            backend=self.target_backend,
            system_prompt=self.target_system_prompt,
            judge=self.judge,
            canaries=self.canaries,
            max_tool_steps=self.max_tool_steps,
            seed=seed,
        )
        stage = "generate"
        spec = result = None
        attempt_id = None
        try:
            spec = agent.generate()
            stage = "execute"
            result = agent.execute(spec, ctx)
            attempt_id = self._record(campaign_id, index, agent, ctx, spec, result)
            stage = "evaluate"
            verdict = agent.evaluate(spec, result, ctx)
            self.storage.record_judgment(attempt_id, verdict.verdict, verdict.reasoning)
            outcome = verdict.verdict
        except Exception as e:
            # Record the failure so refusal/error rates are visible in the report,
            # instead of silently shrinking the sample.
            reason = f"[error:{stage}] {type(e).__name__}: {e}"
            if attempt_id is None:
                attempt_id = self._record(campaign_id, index, agent, ctx, spec, result)
            self.storage.record_judgment(attempt_id, "error", reason[:2000])
            outcome = f"error ({stage})"
            logger.warning("attempt %d type=%s failed at %s: %s", index + 1, agent.sub_agent_type, stage, e)
        with self._lock:
            self._done += 1
            done = self._done
        logger.info(
            "attempt %d/%d (#%d) type=%s owasp=%s verdict=%s",
            done, budget, index + 1, agent.sub_agent_type, agent.owasp_category, outcome,
        )

    def _record(self, campaign_id, index, agent, ctx, spec, result) -> int:
        attempt_id = self.storage.record_attempt(
            campaign_id=campaign_id,
            sub_agent_type=agent.sub_agent_type,
            owasp_category=agent.owasp_category,
            payload=spec.payload if spec else "",
            target_context=spec.context if spec else None,
            target_response=result.target_response if result else "",
            retries=ctx.retries,
            tool_trace=json.dumps(result.tool_trace) if result and result.tool_trace is not None else None,
            attempt_index=index,
            seed=ctx.seed,
            latency_ms=ctx.latency_ms,
            output_tokens=ctx.output_tokens,
            target_calls=ctx.calls,
            extra=json.dumps(result.extra) if result and result.extra else None,
        )
        if result and result.turns:
            self.storage.record_turns(attempt_id, result.turns)
        return attempt_id
