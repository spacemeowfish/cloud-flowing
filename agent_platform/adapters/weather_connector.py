"""Credential-free deterministic weather connector for the MVP."""

from pydantic import JsonValue

from agent_platform.adapters.base_http_connector import BaseHttpConnector, ConnectorConfig


class MockWeatherConnector(BaseHttpConnector):
    def __init__(self, config: ConnectorConfig | None = None) -> None:
        super().__init__(config or ConnectorConfig(name="weather_mock", fallback="cache"))
        self.failures_remaining = 0

    def authenticate(self, request: dict[str, JsonValue]) -> dict[str, JsonValue]:
        return request

    async def request(self, parameters: dict[str, JsonValue]) -> dict[str, JsonValue]:
        if self.failures_remaining > 0:
            self.failures_remaining -= 1
            raise RuntimeError("simulated weather outage")
        city = str(parameters.get("city", "聊城"))
        return {
            "city": city,
            "condition": "晴",
            "temperature_c": 26,
            "humidity_percent": 48,
            "source": "mock",
            "status": "ok",
        }

    async def health_check(self) -> bool:
        return self.failures_remaining == 0

    async def degraded_response(self, parameters: dict[str, JsonValue]) -> dict[str, JsonValue]:
        return {
            "city": str(parameters.get("city", "聊城")),
            "condition": "未知",
            "temperature_c": None,
            "humidity_percent": None,
            "source": "mock-cache",
            "status": "degraded",
        }


if __name__ == "__main__":
    import asyncio

    print(asyncio.run(MockWeatherConnector().execute({"city": "聊城"})))


__all__ = ["MockWeatherConnector"]

