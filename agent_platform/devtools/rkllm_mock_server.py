"""Runnable local simulator for the frozen RKLLM OpenAI-compatible contract."""

from __future__ import annotations

import asyncio
import json
import os
import time
from uuid import uuid4

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from agent_platform.adapters.mock_adapter import MockModelAdapter
from agent_platform.adapters.rkllm_contract import (
    RKLLMChatCompletionRequest,
    RKLLMChatCompletionResponse,
)
from agent_platform.adapters.structured_response import extract_flattened_messages, extract_schema_from_prompt
from agent_platform.models import INTENT_RESPONSE_SCHEMA


def _error(message: str, status_code: int) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "message": message,
                "type": "server_error" if status_code >= 500 else "invalid_request_error",
                "param": None,
                "code": None,
            }
        },
    )


def create_rkllm_mock_app(*, model_name: str = "rkllm-mock", delay_seconds: float = 0.0) -> FastAPI:
    """Create a deterministic simulator; it never loads a real model or RKLLM Runtime."""

    app = FastAPI(title="RKLLM Contract Simulator", version="1.0")
    adapter = MockModelAdapter()

    @app.get("/v1/models")
    async def list_models() -> dict[str, object]:
        return {
            "object": "list",
            "data": [{"id": model_name, "object": "model", "created": int(time.time()), "owned_by": "rkllm"}],
        }

    @app.post("/v1/chat/completions")
    async def chat_completions(payload: RKLLMChatCompletionRequest, request: Request) -> object:
        mode = request.headers.get("x-rkllm-mock-mode", "normal")
        if mode == "busy":
            return _error("RKLLM_Server is busy! Maybe you can try again later.", 503)
        if mode == "server_error":
            return _error("simulated RKLLM runtime error", 500)
        if delay_seconds:
            await asyncio.sleep(delay_seconds)
        if mode == "invalid_protocol":
            return {"unexpected": True}

        prompt = payload.messages[-1].content
        try:
            messages = extract_flattened_messages(prompt)
            response_schema = extract_schema_from_prompt(prompt) or INTENT_RESPONSE_SCHEMA
            result = await adapter.generate(messages, response_schema, payload.max_tokens)
        except (ValueError, TypeError) as exc:
            return _error(str(exc), 400)

        content = json.dumps(result, ensure_ascii=False)
        if mode == "think_wrapper":
            content = f"<think>simulated private reasoning</think>\n{content}"
        elif mode == "markdown_wrapper":
            content = f"```json\n{content}\n```"
        elif mode == "invalid_json":
            content = "not-json"
        elif mode == "extra_explanation":
            content = f"{content}\n这是额外解释"

        completion = RKLLMChatCompletionResponse.model_validate(
            {
                "id": f"chatcmpl-{uuid4().hex[:24]}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": payload.model,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": content},
                        "logprobs": None,
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": len(prompt),
                    "completion_tokens": len(content),
                    "total_tokens": len(prompt) + len(content),
                },
            }
        )
        return completion.model_dump(mode="json")

    return app


def main() -> None:
    host = os.environ.get("RKLLM_MOCK_HOST", "127.0.0.1")
    port = int(os.environ.get("RKLLM_MOCK_PORT", "8081"))
    model = os.environ.get("RKLLM_MOCK_MODEL", "rkllm-mock")
    uvicorn.run(create_rkllm_mock_app(model_name=model), host=host, port=port, reload=False)


if __name__ == "__main__":
    main()


__all__ = ["create_rkllm_mock_app", "main"]
