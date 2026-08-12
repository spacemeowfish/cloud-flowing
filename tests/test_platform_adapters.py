import os
from pathlib import Path

import pytest

from agent_platform.adapters.platform import SystemFileOpener


@pytest.mark.asyncio
@pytest.mark.skipif(os.name != "nt", reason="Windows shell-open receipt")
async def test_windows_file_open_receipt_does_not_claim_visible_window(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "report.txt"
    target.write_text("test", encoding="utf-8")
    calls = []
    monkeypatch.setattr(
        "agent_platform.adapters.platform.os.startfile",
        lambda path, action: calls.append((path, action)),
        raising=False,
    )

    receipt = await SystemFileOpener().open(target)

    assert calls == [(str(target.resolve()), "open")]
    assert receipt["process_status"] == "shell_request_accepted"
    assert receipt["visibility"] == "manual_confirmation_required"
    assert receipt["file_name"] == "report.txt"
    assert receipt["pid"] is None
