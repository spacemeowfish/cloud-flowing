"""Startup-only external connector registry."""

from pydantic import JsonValue

from agent_platform.adapters.base_http_connector import BaseHttpConnector
from agent_platform.core.data_classification import DataClassificationService
from agent_platform.core.errors import ConfigurationError


class ConnectionManager:
    def __init__(self, classifier: DataClassificationService) -> None:
        self._classifier = classifier
        self._connectors: dict[str, BaseHttpConnector] = {}
        self._frozen = False

    def register(self, connector: BaseHttpConnector) -> None:
        if self._frozen:
            raise ConfigurationError("Connector registration is closed after startup")
        name = connector.config.name
        if name in self._connectors:
            raise ConfigurationError(f"Duplicate connector: {name}")
        self._connectors[name] = connector

    def freeze(self) -> None:
        self._frozen = True

    async def execute(self, name: str, parameters: dict[str, JsonValue]) -> dict[str, JsonValue]:
        try:
            connector = self._connectors[name]
        except KeyError as exc:
            raise ConfigurationError(f"Unknown connector: {name}") from exc
        result = await connector.execute(parameters)
        self._classifier.classify(str(result))
        return result

    async def health(self) -> dict[str, bool]:
        return {name: await connector.health_check() for name, connector in self._connectors.items()}

    async def close(self) -> None:
        for connector in self._connectors.values():
            await connector.close()


__all__ = ["ConnectionManager"]

