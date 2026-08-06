"""Deterministic edge-cloud router with documented priority order."""

from agent_platform.core.errors import SensitiveDataError
from agent_platform.core.interfaces import DataClassifier, Router
from agent_platform.models import DataLevel, ExecutionTarget, ResourceMetrics, RoutingDecision, RoutingRequest


class EdgeCloudRouter(Router):
    def __init__(self, classifier: DataClassifier) -> None:
        self._classifier = classifier

    def decide(self, request: RoutingRequest, metrics: ResourceMetrics) -> RoutingDecision:
        # 1. Data class always overrides preference, resources, and network.
        if request.data_level in {DataLevel.D2, DataLevel.D3}:
            if request.local_tool_available:
                return RoutingDecision(target=ExecutionTarget.LOCAL, reason=f"{request.data_level.value}_local_only")
            return RoutingDecision(target=ExecutionTarget.REJECTED, reason=f"{request.data_level.value}_no_local_path")

        # 2. Tool availability.
        if not request.local_tool_available:
            if not request.network_available:
                return RoutingDecision(target=ExecutionTarget.QUEUE, reason="local_tool_unavailable_and_offline")
            if request.cloud_tool_available:
                return RoutingDecision(target=ExecutionTarget.CLOUD, reason="local_tool_unavailable", alternatives=[ExecutionTarget.QUEUE])
            return RoutingDecision(target=ExecutionTarget.REJECTED, reason="no_execution_tool")

        # 3. Resource waterline.
        if metrics.thermal_throttled:
            if request.network_available and request.cloud_tool_available:
                return RoutingDecision(target=ExecutionTarget.CLOUD, reason="thermal_throttling", alternatives=[ExecutionTarget.QUEUE])
            return RoutingDecision(target=ExecutionTarget.QUEUE, reason="thermal_throttling_offline")
        if metrics.utilization_percent >= 85 and request.network_available and request.cloud_tool_available:
            return RoutingDecision(target=ExecutionTarget.CLOUD, reason="high_local_load", alternatives=[ExecutionTarget.LOCAL])

        # 4. Network state.
        if not request.network_available:
            return RoutingDecision(target=ExecutionTarget.LOCAL, reason="offline_local_available")

        # 5. User preference is honored only after safety and availability checks.
        if request.user_preference == ExecutionTarget.CLOUD and request.cloud_tool_available:
            try:
                self._classifier.check_outbound("D0 request metadata")
            except SensitiveDataError:
                return RoutingDecision(target=ExecutionTarget.LOCAL, reason="outbound_policy_blocked")
            return RoutingDecision(target=ExecutionTarget.CLOUD, reason="user_preference", alternatives=[ExecutionTarget.LOCAL])
        return RoutingDecision(target=ExecutionTarget.LOCAL, reason="local_available")


__all__ = ["EdgeCloudRouter"]

