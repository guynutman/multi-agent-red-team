"""Ollama backend for local LLMs (Llama 3 8B etc...)."""
import time
import httpx
from llm.base import LLMResponse, Message

class OllamaBackend:
    """Backend that talks to a local Ollama server."""
    
    def __init__(
        self, 
        model: str = "llama3:8b",
        base_url: str = "http://localhost:11434",
        timeout_s: float = 120.0,
        max_retries: int = 3,
    ):
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s
        self.max_retries = max_retries
        
    def call(self, messages: list[Message], **config) -> LLMResponse:
        url = f"{self.base_url}/api/chat"
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {
                k: v
                for k, v in config.items()
                if k in {"temperature", "top_p", "top_k", "num_predict", "seed"}
            },
        }
        
        started = time.mono  tonic()
        last_error: Exception | None = None
        
        for attempt in range(self.max_retries):
            try:
                with httpx.Client(timeout=self.timeout_s) as client: 
                    resp = client.post(url, json=payload)
                    resp.raise_for_status()
                data = resp.json()
                elapsed_ms = int((time.monotonic() - started) * 1000)
                return LLMResponse(
                    text=data["message"]["content"],
                    raw=data,
                    retries=attempt,
                    latency_ms=elapsed_ms,
                )
            except (httpx.HTTPError, KeyError) as e:
                last_error = e
                time.sleep(2**attempt) # expontential backoff: 1s, 2s, 4s
            
        raise RuntimeError(
            f"OllamaBackend failed after {self.max_retries} retries: {last_error}"
        )
