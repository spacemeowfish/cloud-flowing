from __future__ import annotations

import builtins

import pytest

from agent_platform.adapters.notifications import _clean_reminder_text, windows_toast


def test_clean_reminder_text_removes_command_prefix() -> None:
    assert _clean_reminder_text("提醒我：开会") == "开会"
    assert _clean_reminder_text("普通提醒") == "普通提醒"


@pytest.mark.asyncio
async def test_windows_toast_falls_back_when_winotify_is_missing(monkeypatch, capsys) -> None:
    original_import = builtins.__import__

    def import_without_winotify(name, *args, **kwargs):
        if name == "winotify":
            raise ModuleNotFoundError("No module named 'winotify'", name="winotify")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", import_without_winotify)

    await windows_toast({"text": "提醒我：开会"})

    assert "REMINDER: 开会" in capsys.readouterr().out
