"""Platform notification callbacks for reminders."""

import logging
import re
from typing import Any


logger = logging.getLogger(__name__)


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
    try:
        from winotify import Notification
    except ModuleNotFoundError as exc:
        if exc.name != "winotify":
            raise
        logger.warning("winotify is not installed; falling back to console reminder output")
        await console_print({**reminder, "text": text})
        return
    try:
        toast = Notification(
            app_id="Agent Platform",
            title="Agent 提醒",
            msg=text,
            duration="short",
        )
        toast.show()
    except Exception:
        # Notification delivery is best-effort: a failed toast must not
        # propagate into the reminder/schedule scheduler loops.
        logger.exception("windows toast notification failed; falling back to console")
        await console_print({**reminder, "text": text})


async def console_print(reminder: dict[str, Any]) -> None:
    """Original console logger (fallback)."""
    print(f"REMINDER: {reminder.get('text', '')}")


__all__ = ["console_print", "windows_toast"]
