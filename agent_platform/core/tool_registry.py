"""Startup-only O(1) tool registry."""

from agent_platform.core.errors import ConfigurationError, ToolNotFoundError
from agent_platform.core.interfaces import Tool


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}
        self._frozen = False

    def register(self, tool: Tool) -> None:
        if self._frozen:
            raise ConfigurationError("Tool registration is closed after startup")
        name = tool.metadata.name
        if name in self._tools:
            raise ConfigurationError(f"Duplicate tool registration: {name}")
        self._tools[name] = tool

    def freeze(self) -> None:
        self._frozen = True

    def get(self, name: str) -> Tool:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise ToolNotFoundError(f"Unregistered tool rejected: {name}") from exc

    def contains(self, name: str) -> bool:
        return name in self._tools

    def names(self) -> tuple[str, ...]:
        return tuple(self._tools)


__all__ = ["ToolRegistry"]

