"""Unified entry point for LLM calls across the project."""

import logging

from llm.base import LLMBackend, LLMResponse, Message

logger = logging.getLogger(__name__)


def call_llm(
    messages: list[Message],
    backend: LLMBackend,
    **config,
) -> LLMResponse:
    """
    Unified entry point for LLM calls across the project.

    Delegates to the backend's .call() method. Serves as the single
    seam where cross-cutting concerns (logging, telemetry, cost tracking)
    can be added later without touching callers.

    Args:
        messages: chat messages in OpenAI-style format
        backend: any LLMBackend implementation (Ollama, Gemini, ...)
        **config: per-call provider options (temperature, top_p, etc.)

    Returns:
        LLMResponse with text, raw provider response, retries, latency_ms
    """
    backend_name = type(backend).__name__
    total_content_len = sum(len(m["content"]) for m in messages)
    logger.debug(
        "call_llm start: backend=%s messages=%d total_len=%d",
        backend_name, len(messages), total_content_len,
    )
    
    response = backend.call(messages, **config)
    
    logger.debug(
        "call_llm done:  backend=%s retries=%d latency_ms=%d",
        backend_name, response.retries, response.latency_ms,
    )
    return response