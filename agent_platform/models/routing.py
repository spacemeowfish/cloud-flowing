"""Edge-cloud routing contracts."""

from pydantic import Field

from agent_platform.models.common import DataLevel, ExecutionTarget, StrictModel


class ResourceMetrics(StrictModel):
    mode: str = Field(default="normal", description="Configured resource mode")
    utilization_percent: float = Field(default=40.0, ge=0, le=100, description="Aggregate resource waterline")
    thermal_throttled: bool = Field(default=False, description="Whether sustained frequency is reduced")


class RoutingRequest(StrictModel):
    tool_name: str = Field(..., description="Requested tool")
    local_tool_available: bool = Field(..., description="Whether local execution exists")
    cloud_tool_available: bool = Field(default=True, description="Whether cloud execution exists")
    data_level: DataLevel = Field(..., description="Highest data classification")
    network_available: bool = Field(default=True, description="Current network state")
    user_preference: ExecutionTarget | None = Field(default=None, description="Optional preferred execution side")


class RoutingDecision(StrictModel):
    target: ExecutionTarget = Field(..., description="Selected execution side")
    reason: str = Field(..., description="Primary routing reason")
    outbound_summary: str = Field(default="none", description="Sanitized outbound data summary")
    alternatives: list[ExecutionTarget] = Field(default_factory=list, description="Available fallback sides")

__all__ = ["ResourceMetrics", "RoutingDecision", "RoutingRequest"]

