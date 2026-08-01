# defines vocabulary every part of system uses to talk to LLMs 
# no logic here; only contracts

'''
This file contains 3 classes: 
Message - shape of one chat message (role + content)
LLMResponse - every backend returns an LLMResponse (text + metadata)
LLMBackend - the interface every backend must implement
'''

from typing import Literal, Protocol, TypedDict

from pydantic import BaseModel, Field

class Message(TypedDict): 
    """One chat message in OpenAI-style format."""
    role: Literal["system", "user", "assistant"]
    content: str

class LLMResponse(BaseModel):
    """Every backend returns an LLMResponse from a call."""
    text: str = Field(..., description="The model's response text.")
    raw: dict = Field(..., description="Full provider response, for debugging")
    retries: int = Field(0, description="Internal retries needed for this call.")
    latency_ms: int = Field(..., description="Total call duration in milliseconds.")
    
class LLMBackend(Protocol):
    """Interface every backend implements."""
    
    def call(self, messages: list[Message], **config) -> LLMResponse:
        ...