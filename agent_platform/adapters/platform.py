"""Cross-platform file opening adapters."""

import asyncio
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from pydantic import JsonValue

from agent_platform.core.errors import PermissionDeniedError, ToolExecutionError
from agent_platform.core.interfaces import FileOpener


class DisabledFileOpener(FileOpener):
    async def open(self, path: Path) -> dict[str, JsonValue]:
        return {
            "path": str(path),
            "opened_at": datetime.now(UTC).isoformat(),
            "process_status": "disabled_by_configuration",
        }


class SystemFileOpener(FileOpener):
    async def open(self, path: Path) -> dict[str, JsonValue]:
        if not path.is_file():
            raise PermissionDeniedError("Only existing regular files may be opened")
        try:
            if os.name == "nt":
                await asyncio.to_thread(os.startfile, str(path))  # type: ignore[attr-defined]
                pid: int | None = None
            else:
                command = "open" if sys.platform == "darwin" else "xdg-open"
                process = await asyncio.create_subprocess_exec(
                    command,
                    str(path),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                pid = process.pid
        except OSError as exc:
            raise ToolExecutionError(f"Unable to open file with the system application: {exc}") from exc
        return {
            "path": str(path),
            "opened_at": datetime.now(UTC).isoformat(),
            "process_status": "started",
            "pid": pid,
        }


__all__ = ["DisabledFileOpener", "SystemFileOpener"]
