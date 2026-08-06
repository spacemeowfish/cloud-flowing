"""Seven-step orchestration across all platform safety and execution modules."""

import asyncio
import json
from uuid import UUID

from pydantic import JsonValue

from agent_platform.core.audit_service import AuditService
from agent_platform.core.data_classification import DataClassificationService
from agent_platform.core.edge_cloud_router import EdgeCloudRouter
from agent_platform.core.errors import AgentPlatformError, PermissionDeniedError, SensitiveDataError
from agent_platform.core.model_gateway import ModelGateway
from agent_platform.core.parameter_normalizer import normalize_arguments
from agent_platform.core.policy_engine import PolicyEngine
from agent_platform.core.resource_monitor import ResourceMonitor
from agent_platform.core.schema_validator import SchemaValidator
from agent_platform.core.task_api import TaskAPI
from agent_platform.core.tool_executor import ToolExecutor
from agent_platform.core.tool_registry import ToolRegistry
from agent_platform.models import (
    AuditEvent,
    AuditEventType,
    ExecutionTarget,
    IntentResult,
    MessageRole,
    ModelMessage,
    PolicyContext,
    RoutingRequest,
    TaskConfirmation,
    TaskCreate,
    TaskEvent,
    TaskRecord,
    TaskState,
    ToolCall,
    build_model_acceptance_schema,
)


class AgentCore:
    """Coordinate intent, validation, policy, routing, confirmation, tool, and delivery."""

    def __init__(
        self,
        *,
        tasks: TaskAPI,
        gateway: ModelGateway,
        registry: ToolRegistry,
        executor: ToolExecutor,
        classifier: DataClassificationService,
        policy: PolicyEngine,
        router: EdgeCloudRouter,
        resources: ResourceMonitor,
        audit: AuditService,
        network_available: bool = True,
    ) -> None:
        self.tasks = tasks
        self._gateway = gateway
        self._registry = registry
        self._model_acceptance_schema = build_model_acceptance_schema(registry)
        self._executor = executor
        self._classifier = classifier
        self._policy = policy
        self._router = router
        self._resources = resources
        self._audit = audit
        self._network_available = network_available

    async def submit(self, request: TaskCreate) -> TaskRecord:
        task = await self.start(request)
        return await self.process(task.id, request)

    async def start(self, request: TaskCreate) -> TaskRecord:
        classification = self._classifier.classify(request.text)
        safe_request = request.model_copy(update={"text": classification.redacted_text})
        task = await self.tasks.create(safe_request)
        await self._audit.record(
            AuditEvent(
                task_id=task.id,
                event_type=AuditEventType.INPUT_RECEIVED,
                input_summary=request.text,
            )
        )
        return task

    async def process(self, task_id: UUID, request: TaskCreate) -> TaskRecord:
        classification = self._classifier.classify(request.text)
        task = await self.tasks.get(task_id)
        try:
            task = await self.tasks.transition(
                task.id,
                TaskEvent.UNDERSTAND,
                context_update={"role": request.role, "data_domain": request.data_domain},
                data_level=classification.level,
            )
            interpretation = await self._gateway.interpret(
                classification.redacted_text,
                self._model_acceptance_schema,
                data_level=classification.level,
            )
            intent = interpretation.intent
            await self._audit.record(
                AuditEvent(
                    task_id=task.id,
                    event_type=AuditEventType.MODEL_OUTPUT,
                    output_summary=(
                        f"intent={intent.intent}; missing={','.join(intent.missing_fields)}; "
                        f"route={interpretation.route_source}; calls={interpretation.model_calls}; "
                        f"repaired={str(interpretation.schema_repaired).lower()}"
                    ),
                    data_level=classification.level,
                )
            )
            normalization = normalize_arguments(
                intent=intent.intent,
                arguments=intent.arguments,
                request_text=task.request_text,
            )
            missing_fields = list(intent.missing_fields)
            if "meeting_process.source_path_from_request" in normalization.applied_rules:
                missing_fields = [field for field in missing_fields if field != "source_path"]
            if normalization.applied_rules:
                before_fields = ",".join(sorted(intent.arguments)) or "-"
                after_fields = ",".join(sorted(normalization.arguments)) or "-"
                await self._audit.record(
                    AuditEvent(
                        task_id=task.id,
                        event_type=AuditEventType.MODEL_OUTPUT,
                        output_summary=(
                            f"rules={','.join(normalization.applied_rules)}; "
                            f"fields={before_fields}->{after_fields}"
                        ),
                        decision="parameters_normalized",
                        data_level=classification.level,
                    )
                )
            task = await self.tasks.transition(
                task.id,
                TaskEvent.VALIDATE,
                context_update={
                    "intent": intent.intent,
                    "arguments": normalization.arguments,
                    "missing_fields": missing_fields,
                    "confidence": intent.confidence,
                    "normalization_rules": normalization.applied_rules,
                    "intent_route": interpretation.route_source,
                    "model_calls": interpretation.model_calls,
                    "schema_repaired": interpretation.schema_repaired,
                },
            )
            return await self._continue(task, confirmed=False)
        except asyncio.CancelledError:
            current = await self.tasks.get(task.id)
            if current.state != TaskState.CANCELLED:
                current = await self.tasks.cancel(task.id)
            return current
        except Exception as exc:
            return await self._fail(task.id, exc)

    async def confirm(self, task_id: UUID, confirmation: TaskConfirmation) -> TaskRecord:
        task = await self.tasks.get(task_id)
        if task.state != TaskState.AWAITING_CONFIRMATION:
            raise PermissionDeniedError("Task is not waiting for confirmation")
        if not confirmation.approved:
            await self._audit.record(
                AuditEvent(
                    task_id=task.id,
                    event_type=AuditEventType.CONFIRMATION_REJECTED,
                    decision="confirmation_rejected",
                    data_level=task.data_level,
                )
            )
            return await self.cancel(task_id, "confirmation_rejected")
        arguments = dict(task.context.get("arguments", {}))
        arguments.update(confirmation.arguments)
        if task.context.get("intent") == "reminder_create" and "when" in confirmation.arguments:
            arguments["text"] = task.request_text
        confirmed_data = self._classifier.classify(json.dumps(arguments, ensure_ascii=False))
        if confirmed_data.level.value == "D3":
            raise SensitiveDataError("D3 data cannot be persisted as confirmation arguments")
        await self._audit.record(
            AuditEvent(
                task_id=task.id,
                event_type=AuditEventType.CONFIRMATION_APPROVED,
                decision="confirmation_approved",
                data_level=task.data_level,
            )
        )
        task = await self.tasks.transition(
            task_id,
            TaskEvent.CONFIRM,
            context_update={"arguments": arguments, "missing_fields": [], "confirmed": True},
        )
        try:
            return await self._continue(task, confirmed=True)
        except Exception as exc:
            return await self._fail(task.id, exc)

    async def cancel(self, task_id: UUID, reason: str = "user_cancelled") -> TaskRecord:
        task = await self.tasks.cancel(task_id, reason)
        await self._audit.record(
            AuditEvent(
                task_id=task.id,
                event_type=AuditEventType.TASK_CANCELLED,
                decision=reason,
                success=True,
                data_level=task.data_level,
            )
        )
        return task

    async def _continue(self, task: TaskRecord, *, confirmed: bool) -> TaskRecord:
        intent_name = str(task.context["intent"])
        arguments = dict(task.context.get("arguments", {}))
        missing_fields = list(task.context.get("missing_fields", []))
        if missing_fields:
            return await self.tasks.transition(
                task.id,
                TaskEvent.REQUIRE_CONFIRMATION,
                result={"type": "missing_fields", "fields": missing_fields},
            )

        tool = self._registry.get(intent_name)
        SchemaValidator.validate(arguments, tool.metadata.parameters_schema)
        await self._audit.record(
            AuditEvent(
                task_id=task.id,
                event_type=AuditEventType.SCHEMA_VALIDATED,
                decision="valid",
                data_level=task.data_level,
            )
        )

        role = str(task.context.get("role", "user"))
        domain = str(task.context.get("data_domain", "personal"))
        effective_risk = self._policy.resolve_risk(tool.metadata.name, arguments, tool.metadata.risk_level)
        policy = self._policy.evaluate(
            PolicyContext(
                role=role,
                data_domain=domain,
                risk_level=effective_risk,
                data_level=task.data_level,
                action=tool.metadata.name,
                arguments=arguments,
            )
        )
        await self._audit.record(
            AuditEvent(
                task_id=task.id,
                event_type=AuditEventType.POLICY_DECIDED,
                decision=policy.reason,
                success=policy.allowed,
                data_level=task.data_level,
            )
        )
        if not policy.allowed:
            raise PermissionDeniedError(policy.reason)
        if policy.requires_confirmation and not confirmed:
            preview = getattr(tool, "confirmation_context", None)
            if callable(preview) and policy.confirmation is not None:
                details = await preview(arguments)
                if details:
                    policy = policy.model_copy(
                        update={
                            "confirmation": policy.confirmation.model_copy(
                                update={
                                    "content": (
                                        f"{policy.confirmation.content}\n"
                                        f"日程：{details.get('title', '')}；开始：{details.get('start_at', '')}"
                                    )
                                }
                            )
                        }
                    )
            return await self.tasks.transition(
                task.id,
                TaskEvent.REQUIRE_CONFIRMATION,
                result={"type": "risk_confirmation", "confirmation": policy.confirmation.model_dump(mode="json") if policy.confirmation else {}},
                risk_level=effective_risk,
            )

        decision = self._router.decide(
            RoutingRequest(
                tool_name=tool.metadata.name,
                local_tool_available=True,
                cloud_tool_available=False,
                data_level=task.data_level,
                network_available=self._network_available,
            ),
            self._resources.get_metrics(),
        )
        await self._audit.record(
            AuditEvent(
                task_id=task.id,
                event_type=AuditEventType.ROUTING_DECIDED,
                decision=decision.reason,
                execution_target=decision.target,
                data_level=task.data_level,
            )
        )
        if decision.target == ExecutionTarget.QUEUE:
            return await self.tasks.transition(task.id, TaskEvent.WAIT_NETWORK, result={"status": "waiting_network"})
        if decision.target == ExecutionTarget.REJECTED:
            raise SensitiveDataError(decision.reason)

        task = await self.tasks.transition(
            task.id,
            TaskEvent.EXECUTE,
            risk_level=effective_risk,
        )
        receipt = await self._executor.execute(
            ToolCall(task_id=task.id, tool_name=tool.metadata.name, arguments=arguments),
            self.tasks.cancellation_event(task.id),
        )
        await self._audit.record(
            AuditEvent(
                task_id=task.id,
                event_type=AuditEventType.TOOL_CALLED,
                input_summary=f"tool={tool.metadata.name}",
                output_summary=receipt.output_summary,
                execution_target=decision.target,
                success=receipt.success,
                data_level=task.data_level,
            )
        )
        if not receipt.success:
            raise AgentPlatformError(receipt.error_code or "tool_receipt_failed")
        if receipt.output.get("requires_confirmation") is True:
            confirmation_type = str(receipt.output.get("confirmation_type", "candidate_confirmation"))
            if confirmation_type == "missing_fields":
                result = {
                    "type": "missing_fields",
                    "fields": list(receipt.output.get("fields", [])),
                    "message": str(receipt.output.get("message", receipt.output_summary)),
                }
            else:
                result = {"type": "candidate_confirmation", "receipt": receipt.model_dump(mode="json")}
            return await self.tasks.transition(
                task.id,
                TaskEvent.REQUIRE_CONFIRMATION,
                result=result,
            )

        task = await self.tasks.transition(
            task.id,
            TaskEvent.DELIVER,
            result=receipt.model_dump(mode="json"),
        )
        task = await self.tasks.transition(task.id, TaskEvent.COMPLETE)
        await self._audit.record(
            AuditEvent(
                task_id=task.id,
                event_type=AuditEventType.RESULT_DELIVERED,
                output_summary=receipt.output_summary,
                execution_target=decision.target,
                data_level=task.data_level,
            )
        )
        await self._audit.flush()
        return task

    async def _fail(self, task_id: UUID, exc: Exception) -> TaskRecord:
        task = await self.tasks.get(task_id)
        if task.state in {TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED}:
            return task
        safe_error = exc.detail if isinstance(exc, AgentPlatformError) else f"{type(exc).__name__}: {exc}"
        task = await self.tasks.transition(task_id, TaskEvent.FAIL, error=safe_error)
        await self._audit.record(
            AuditEvent(
                task_id=task.id,
                event_type=AuditEventType.TASK_FAILED,
                output_summary=safe_error,
                success=False,
                data_level=task.data_level,
            )
        )
        await self._audit.flush()
        return task


__all__ = ["AgentCore"]
