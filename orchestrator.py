import logging
from llm.base import LLMBackend, Message
from llm.entry import call_llm
from judge import Judge
from storage.db import Storage
from subagents.base import InjectionSpec, SubAgent

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
    ):
        """
        target_backend: LLM being attacked
        target_system_prompt: the target's hidden system prompt (defines its constraints)
        subagents: list of SubAgent instances to rotate through
        judge: evaluator that decides success/failure per attempt
        storage: SQLite persistence layer
        """
        self.target_backend = target_backend
        self.target_system_prompt = target_system_prompt
        self.subagents = subagents
        self.judge = judge
        self.storage = storage
        
        
    def run_campaign(
        self,
        name: str,
        target_model_name: str,
        attacker_model_name: str,
        budget: int,
    ) -> int:
        """
        Execute one campaign. Returns the campaign_id.
        
        1. Create campaign row. 
        2. Loop up to `budget` times, dispatching sub-agents round-robin.
        3. For each attempt: generate payload -> send to target -> record attempt
            -> judge -> record verdict.
        4. Finish campaign, return id.
        """
        campaign_id = self.storage.create_campaign(name, target_model_name, attacker_model_name, budget)
        try:
            for attempt in range(budget):
                subagent = self.subagents[attempt % (len(self.subagents))]
                try:
                    spec = subagent.generate()
                    target_response, retries = self._query_target(spec)
                    attempt_id = self.storage.record_attempt(
                        campaign_id=campaign_id,
                        sub_agent_type=subagent.sub_agent_type,
                        payload=spec.payload,
                        target_context=spec.context,
                        target_response=target_response,
                        retries=retries
                    )        
                    verdict = self.judge.evaluate(spec, target_response)
                    self.storage.record_judgment(
                        attempt_id=attempt_id,
                        verdict=verdict.verdict,
                        reasoning=verdict.reasoning,
                    )    
                    logger.info(
                        "attempt %d/%d type=%s verdict=%s",
                        attempt + 1, budget, subagent.sub_agent_type, verdict.verdict,
                    )
                except Exception as e:
                    logger.warning(
                        "attempt %d/%d type=%s failed: %s",
                        attempt + 1, budget, subagent.sub_agent_type, e,
                    )
                    self.storage.finish_campaign(campaign_id, "completed")
        except Exception as e:
            logger.error("Campaign failed: %s", e)
            self.storage.finish_campaign(campaign_id, "aborted")
            raise
        return campaign_id
                        
    def _query_target(self, spec: InjectionSpec) -> tuple[str, int]:
        """Send an injection attempt to the target model."""
        if spec.context is None:
            # basic direct: user message is just the payload
            user_content = spec.payload
        else:
            # external indirect: wrap the context in a summarization request
            user_content = (
                f"Please summarize the following document:\n\n{spec.context}"
            )
            
        messages = [
            {"role": "system", "content": self.target_system_prompt},
            {"role": "user", "content": user_content}, 
        ]
        response = call_llm(messages, self.target_backend, temperature=0.7)
        return response.text, response.retries