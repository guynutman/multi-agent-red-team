import re
from abc import ABC, abstractmethod

from llm.base import LLMBackend
from pydantic import BaseModel
from taxonomy import get_category


class InjectionSpec(BaseModel):
    """One attack the sub-agent wants to attempt."""
    payload: str
    context: str | None = None
    success_criterion: str
    
    
class SubAgent(ABC):
    """Base class for all attack sub-agents."""
    
    sub_agent_type: str = "base"
    # OWASP LLM Top 10 (2025) id this sub-agent exercises, e.g. "LLM01".
    owasp_category: str = "LLM01"
    # Key into the orchestrator's canary map. When set, a response containing that
    # canary is a deterministic success (used by leakage agents: LLM02, LLM07).
    canary_key: str | None = None

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        get_category(cls.owasp_category)  # fail fast on a typo'd category id
    
    def __init__(self, attacker_backend: LLMBackend):
        self.attacker_backend = attacker_backend
    
    @abstractmethod
    def generate(self) -> InjectionSpec:
        """Produce one attack spec."""
        ...
    
    def _parse_spec(self, text: str) -> InjectionSpec:
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned
            cleaned = cleaned.rsplit("```", 1)[0]
        cleaned = cleaned.strip()
        # NEW: strip control characters (except \n, \r, \t) that break JSON parsing
        cleaned = re.sub(r"[\x00-\x1f]", "", cleaned)
        
        if not cleaned.startswith("{"):
            raise ValueError(
                f"Attacker LLM did not return JSON (likely a refusal). "
                f"First 200 chars: {cleaned[:200]!r}"
            )

        return InjectionSpec.model_validate_json(cleaned)