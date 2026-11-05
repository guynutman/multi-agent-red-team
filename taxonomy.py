"""OWASP Top 10 for LLM Applications (2025) — the classification used to tag attacks.

Every sub-agent declares which category it exercises; the orchestrator stores that
id on each attempt, and the report renders coverage across all ten categories.
"""

from typing import NamedTuple


class OwaspCategory(NamedTuple):
    id: str
    name: str
    summary: str


OWASP_LLM_TOP10: dict[str, OwaspCategory] = {
    c.id: c
    for c in (
        OwaspCategory("LLM01", "Prompt Injection",
                      "Inputs (direct or via external content) alter the model's intended behavior."),
        OwaspCategory("LLM02", "Sensitive Information Disclosure",
                      "The model reveals PII, credentials, or confidential data."),
        OwaspCategory("LLM03", "Supply Chain",
                      "Compromised models, datasets, or third-party components."),
        OwaspCategory("LLM04", "Data and Model Poisoning",
                      "Manipulated training/fine-tuning/embedding data introduces backdoors or bias."),
        OwaspCategory("LLM05", "Improper Output Handling",
                      "Unvalidated model output reaches downstream systems (XSS, SQLi, RCE, SSRF)."),
        OwaspCategory("LLM06", "Excessive Agency",
                      "The model is granted too much functionality, permission, or autonomy."),
        OwaspCategory("LLM07", "System Prompt Leakage",
                      "The hidden system prompt or its secrets are extracted."),
        OwaspCategory("LLM08", "Vector and Embedding Weaknesses",
                      "Weaknesses in RAG retrieval and embedding stores are exploited."),
        OwaspCategory("LLM09", "Misinformation",
                      "The model produces false or misleading content presented as fact."),
        OwaspCategory("LLM10", "Unbounded Consumption",
                      "Uncontrolled inference leads to DoS, cost blow-up, or model extraction."),
    )
}


def get_category(category_id: str) -> OwaspCategory:
    try:
        return OWASP_LLM_TOP10[category_id]
    except KeyError:
        raise ValueError(
            f"Unknown OWASP LLM category {category_id!r}; "
            f"expected one of {', '.join(OWASP_LLM_TOP10)}"
        ) from None
