"""Configurable no-hardware resource monitor."""

from pathlib import Path

import yaml

from agent_platform.models import ResourceMetrics


class ResourceMonitor:
    def __init__(self, mode: str = "normal", config_path: Path | None = None) -> None:
        path = config_path or Path(__file__).parents[1] / "config" / "resource_monitor.yaml"
        self._modes = yaml.safe_load(path.read_text(encoding="utf-8"))["modes"]
        self.set_mode(mode)

    def set_mode(self, mode: str) -> None:
        if mode not in self._modes:
            raise ValueError(f"Unknown resource mode: {mode}")
        self._mode = mode

    def get_metrics(self) -> ResourceMetrics:
        values = self._modes[self._mode]
        return ResourceMetrics(mode=self._mode, **values)


__all__ = ["ResourceMonitor"]

