import os
import time

import httpx
from dotenv import load_dotenv
load_dotenv()

from llm.base import LLMResponse, Message

class GeminiBackend:
    """Backend that talks to Google's Gemini API."""
    
    def __init__(
        self,
        model: str = "gemini-flash-latest",
        api_key: str | None = None,         # if None, read from GEMINI_API_KEY env var
        base_url: str = "https://generativelanguage.googleapis.com/v1beta",
        timeout_s: float = 60.0,
        max_retries: int = 3,
    ): 
        """
        If api_key is None, read from GEMINI_API_KEY env var.
        Raise ValueError if no key is found in either place.
        """
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s
        self.max_retries = max_retries
        resolved = api_key or os.environ.get("GEMINI_API_KEY")
        if not resolved:
            raise ValueError("GEMINI_API_KEY not set")
        self.api_key = resolved
    
    def _transform_messages(self, messages) -> tuple[list, dict | None]:
        system_msgs = [m for m in messages if m["role"] == "system"]
        other_msgs = [m for m in messages if m["role"] != "system"]
        
        contents = [
            {
                "role": "model" if m["role"] == "assistant" else "user",
                "parts": [{"text": m["content"]}],
            }
            for m in other_msgs
        ]
        
        system_instruction = None
        if system_msgs:
            joined = "\n\n".join(m["content"] for m in system_msgs)
            system_instruction = {"parts": [{"text": joined}]}
        
        return contents, system_instruction
            
    def call(self, messages: list[Message], **config) -> LLMResponse: 
        """
        Send messages to Gemini, return response.

        Recognized config keys (whitelist): temperature, top_p, top_k,
        max_output_tokens, response_mime_type.
        Anything else is ignored.
        """
        url = f"{self.base_url}/models/{self.model}:generateContent?key={self.api_key}"
        
        contents, system_instruction = self._transform_messages(messages)
        generation_config = {
            k: v for k, v in config.items()
            if k in {"temperature", "top_p", "top_k", "max_output_tokens", "response_mime_type"}
        }
        
        payload = {"contents": contents, "generationConfig": generation_config}
        if system_instruction is not None:
            payload["systemInstruction"] = system_instruction
        
        started = time.monotonic()
        last_error: Exception | None = None
        
        for attempt in range(self.max_retries):
            try:
                with httpx.Client(timeout=self.timeout_s) as client:
                    resp = client.post(url, json=payload)
                    resp.raise_for_status() 
                data = resp.json()
                elapsed_ms = int((time.monotonic() - started) * 1000)
                return LLMResponse(
                    text=data["candidates"][0]["content"]["parts"][0]["text"],
                    raw=data,
                    retries=attempt,
                    latency_ms=elapsed_ms,
                )
            except httpx.HTTPStatusError as e: 
                if e.response.status_code in {400, 401, 403, 404}:
                    raise
                last_error = e
                time.sleep(2**attempt)
            except (httpx.HTTPError, KeyError, IndexError) as e:
                last_error = e
                time.sleep(2**attempt) # expontential backoff: 1s, 2s, 4s
            
        raise RuntimeError(
            f"GeminiBackend failed after {self.max_retries} retries: {last_error}"
        )
