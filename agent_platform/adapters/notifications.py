"""Platform notification callbacks for reminders."""

import re
from typing import Any

from winotify import Notification


def _clean_reminder_text(raw_text: str) -> str:
    """Strip common command prefixes from reminder text."""
    cleaned = re.sub(
        r"^(?:请|帮我|请帮我)?(?:提醒我|提醒|设置提醒|创建提醒)[：:\s]*",
        "",
        raw_text,
    )
    return cleaned.strip() or raw_text


async def windows_toast(reminder: dict[str, Any]) -> None:
    """Show a Windows 10/11 toast notification in the bottom-right corner."""
    text = _clean_reminder_text(str(reminder.get("text", "提醒")))
    toast = Notification(
        app_id="Agent Platform",
        title="Agent 提醒",
        msg=text,
        duration="short",
    )
    toast.show()


async def console_print(reminder: dict[str, Any]) -> None:
    """Original console logger (fallback)."""
    print(f"REMINDER: {reminder.get('text', '')}")


__all__ = ["console_print", "windows_toast"]
