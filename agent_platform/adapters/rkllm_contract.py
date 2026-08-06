"""Frozen non-streaming subset of the official RKLLM OpenAI-compatible protocol."""

from typing import Literal

from pydantic import Field, JsonValue

from agent_platform.models.common import MessageRole, StrictModel


class RKLLMChatMessage(StrictModel):
    role: MessageRole
    content: str = Field(..., min_length=1)


class RKLLMChatCompletionRequest(StrictModel):
    model: str = Field(..., min_length=1)
    messages: list[RKLLMChatMessage] = Field(..., min_length=1)
    stream: Literal[False] = False
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    top_p: float = Field(default=1.0, gt=0.0, le=1.0)
    top_k: int = Field(default=1, ge=1)
    max_tokens: int = Field(default=512, ge=1, le=8192)
    repeat_penalty: float = Field(default=1.0, gt=0.0)
    frequency_penalty: float = Field(default=0.0, ge=-2.0, le=2.0)
    presence_penalty: float = Field(default=0.0, ge=-2.0, le=2.0)
    enable_thinking: Literal[False] = False


class RKLLMCompletionMessage(StrictModel):
    role: Literal["assistant"]
    content: str


class RKLLMChatCompletionChoice(StrictModel):
    index: int = Field(..., ge=0)
    message: RKLLMCompletionMessage
    logprobs: JsonValue | None = None
    finish_reason: str | None = None


class RKLLMUsage(StrictModel):
    prompt_tokens: int = Field(..., ge=0)
    completion_tokens: int = Field(..., ge=0)
    total_tokens: int = Field(..., ge=0)


class RKLLMChatCompletionResponse(StrictModel):
    id: str = Field(..., min_length=1)
    object: Literal["chat.completion"]
    created: int = Field(..., ge=0)
    model: str = Field(..., min_length=1)
    choices: list[RKLLMChatCompletionChoice] = Field(..., min_length=1)
    usage: RKLLMUsage


__all__ = [
    "RKLLMChatCompletionChoice",
    "RKLLMChatCompletionRequest",
    "RKLLMChatCompletionResponse",
    "RKLLMChatMessage",
    "RKLLMCompletionMessage",
    "RKLLMUsage",
]
