"""Provider-independent model gateway."""

import json
from collections.abc import Sequence
from dataclasses import dataclass

from jsonschema import Draft202012Validator
from pydantic import JsonValue

from agent_platform.adapters import CloudModelAdapter, LlamaCppModelAdapter, MockModelAdapter, OllamaModelAdapter, RKLLMModelAdapter
from agent_platform.config import Settings
from agent_platform.core.errors import ConfigurationError, ModelError, ModelSchemaError
from agent_platform.core.interfaces import ModelAdapter
from agent_platform.core.intent_router import pre_route_intent
from agent_platform.core.parameter_normalizer import deterministic_pre_route_arguments
from agent_platform.models import (
    INTENT_CLASSIFICATION_SCHEMA,
    DataLevel,
    IntentClassificationResult,
    IntentResult,
    MessageRole,
    ModelMessage,
    build_argument_extraction_schema,
    is_model_acceptance_schema,
)


@dataclass(frozen=True)
class InterpretationResult:
    intent: IntentResult
    route_source: str
    model_calls: int
    schema_repaired: bool


class ModelGateway:
    """Expose one generation contract regardless of the selected adapter."""

    def __init__(
        self,
        adapter: ModelAdapter,
        *,
        fallback_adapter: ModelAdapter | None = None,
        fallback_data_levels: frozenset[DataLevel] = frozenset({DataLevel.D0, DataLevel.D1}),
    ) -> None:
        self._adapter = adapter
        self._fallback_adapter = fallback_adapter
        self._fallback_data_levels = fallback_data_levels

    @property
    def is_local_model(self) -> bool:
        """Whether the primary adapter executes on the local device."""

        return not isinstance(self._adapter, CloudModelAdapter)

    @classmethod
    def from_settings(cls, settings: Settings) -> "ModelGateway":
        provider = settings.model_provider.lower()
        if provider == "mock":
            adapter: ModelAdapter = MockModelAdapter()
        elif provider == "cloud":
            adapter = CloudModelAdapter(
                base_url=settings.model_base_url,
                model=settings.model_name,
                api_key=settings.model_api_key,
                timeout_seconds=settings.model_timeout_seconds,
            )
        elif provider == "ollama":
            adapter = OllamaModelAdapter(
                base_url=settings.ollama_base_url,
                model=settings.model_name,
                timeout_seconds=settings.ollama_timeout_seconds,
                thinking_enabled=settings.ollama_thinking_enabled,
                keep_alive=settings.ollama_keep_alive,
                max_new_tokens=settings.ollama_max_new_tokens,
            )
        elif provider == "rkllm":
            adapter = RKLLMModelAdapter(
                base_url=settings.rkllm_server_url,
                model=settings.rkllm_model_name,
                timeout_seconds=settings.rkllm_timeout_seconds,
                queue_timeout_seconds=settings.rkllm_queue_timeout_seconds,
                max_concurrency=settings.rkllm_max_concurrency,
                max_new_tokens=settings.rkllm_max_new_tokens,
            )
        elif provider == "llamacpp":
            adapter = LlamaCppModelAdapter(
                base_url=settings.llamacpp_server_url,
                model=settings.llamacpp_model_name,
                timeout_seconds=settings.llamacpp_timeout_seconds,
                queue_timeout_seconds=settings.llamacpp_queue_timeout_seconds,
                max_concurrency=settings.llamacpp_parallel,
                max_new_tokens=settings.llamacpp_max_tokens,
            )
        else:
            raise ConfigurationError(f"Unsupported MODEL_PROVIDER: {settings.model_provider}")
        fallback: ModelAdapter | None = None
        if provider in {"rkllm", "llamacpp"} and settings.model_fallback_enabled:
            fallback = CloudModelAdapter(
                base_url=settings.model_fallback_base_url,
                model=settings.model_fallback_name,
                api_key=settings.model_fallback_api_key,
                timeout_seconds=settings.model_fallback_timeout_seconds,
            )
        return cls(adapter, fallback_adapter=fallback)

    async def generate(
        self,
        messages: Sequence[ModelMessage],
        response_schema: dict[str, JsonValue],
        max_tokens: int = 512,
        *,
        data_level: DataLevel | None = None,
    ) -> dict[str, JsonValue]:
        try:
            result = await self._adapter.generate(messages, response_schema, max_tokens)
            return self._validate_result(result, response_schema)
        except ModelError as exc:
            can_fallback = (
                self._fallback_adapter is not None
                and exc.retryable
                and data_level is not None
                and data_level in self._fallback_data_levels
            )
            if not can_fallback:
                raise
            result = await self._fallback_adapter.generate(messages, response_schema, max_tokens)
            return self._validate_result(result, response_schema)

    async def generate_text(
        self,
        messages: Sequence[ModelMessage],
        max_tokens: int = 512,
        *,
        data_level: DataLevel | None = None,
    ) -> str:
        """Generate free text without applying the structured Agent JSON contract."""

        try:
            return await self._adapter.generate_text(messages, max_tokens)
        except ModelError as exc:
            can_fallback = (
                self._fallback_adapter is not None
                and exc.retryable
                and data_level is not None
                and data_level in self._fallback_data_levels
            )
            if not can_fallback:
                raise
            return await self._fallback_adapter.generate_text(messages, max_tokens)

    async def interpret(
        self,
        request_text: str,
        response_schema: dict[str, JsonValue],
        *,
        data_level: DataLevel | None = None,
    ) -> InterpretationResult:
        """Select one intent, then extract only that intent's arguments."""

        if not is_model_acceptance_schema(response_schema):
            raise ValueError("interpret requires a model acceptance schema")
        decision = pre_route_intent(request_text)
        model_calls = 0
        if decision is None:
            classified = await self.generate(
                [ModelMessage(role=MessageRole.USER, content=request_text)],
                INTENT_CLASSIFICATION_SCHEMA,
                data_level=data_level,
            )
            model_calls += 1
            classification = IntentClassificationResult.model_validate(classified)
            selected_intent = classification.intent
            selected_confidence = classification.confidence
            route_source = "model_classification"
        else:
            selected_intent = decision.intent
            selected_confidence = 1.0
            route_source = f"pre_route:{decision.rule}"

        selected_schema = build_argument_extraction_schema(response_schema, selected_intent)
        deterministic_arguments = (
            deterministic_pre_route_arguments(selected_intent, request_text) if decision is not None else None
        )
        if deterministic_arguments is not None:
            raw = self._validate_result(
                {"arguments": deterministic_arguments, "missing_fields": []},
                selected_schema,
            )
            return InterpretationResult(
                intent=IntentResult(
                    intent=selected_intent,
                    arguments=dict(raw["arguments"]),
                    missing_fields=[],
                    confidence=selected_confidence,
                ),
                route_source=f"{route_source}:deterministic_arguments",
                model_calls=0,
                schema_repaired=False,
            )
        messages = [ModelMessage(role=MessageRole.USER, content=request_text)]
        schema_repaired = False
        try:
            raw = await self.generate(messages, selected_schema, data_level=data_level)
            model_calls += 1
        except ModelSchemaError as exc:
            model_calls += 1
            repair = self._repair_message(request_text, selected_intent, exc)
            raw = await self.generate(
                [*messages, ModelMessage(role=MessageRole.USER, content=repair)],
                selected_schema,
                data_level=data_level,
            )
            model_calls += 1
            schema_repaired = True
        intent_result = IntentResult(
            intent=selected_intent,
            arguments=dict(raw["arguments"]),
            missing_fields=list(raw["missing_fields"]),
            confidence=selected_confidence,
        )
        return InterpretationResult(
            intent=intent_result,
            route_source=route_source,
            model_calls=model_calls,
            schema_repaired=schema_repaired,
        )

    @staticmethod
    def _validate_result(
        result: dict[str, JsonValue], response_schema: dict[str, JsonValue]
    ) -> dict[str, JsonValue]:
        errors = list(Draft202012Validator(response_schema).iter_errors(result))
        if not errors:
            return result
        messages = tuple(
            f"{'.'.join(str(part) for part in error.absolute_path) or '$'}: {error.message}"
            for error in errors[:5]
        )
        raise ModelSchemaError(
            "Model output did not match the requested schema",
            raw_result=dict(result),
            validation_errors=messages,
        )

    @staticmethod
    def _repair_message(request_text: str, intent: str, error: ModelSchemaError) -> str:
        return (
            "上一次输出是完整 JSON，但违反当前参数 Schema。只修正结构和字段，不改变意图，不添加其他工具字段。\n"
            f"原始请求：{request_text}\n"
            f"固定意图：{intent}\n"
            f"校验错误：{' | '.join(error.validation_errors)}\n"
            f"上次输出：{json.dumps(error.raw_result, ensure_ascii=False, separators=(',', ':'))}\n"
            "重新输出一个符合相同 Schema 的 JSON 对象。"
        )

    async def close(self) -> None:
        await self._adapter.close()
        if self._fallback_adapter is not None and self._fallback_adapter is not self._adapter:
            await self._fallback_adapter.close()


if __name__ == "__main__":
    import asyncio

    from agent_platform.models import INTENT_RESPONSE_SCHEMA, MessageRole

    gateway = ModelGateway(MockModelAdapter())
    print(asyncio.run(gateway.generate([ModelMessage(role=MessageRole.USER, content="查找年度报告")], INTENT_RESPONSE_SCHEMA)))


__all__ = ["InterpretationResult", "ModelGateway"]
