"""Start the Agent against the localhost RKLLM simulator for manual verification."""

from __future__ import annotations

import os
from pathlib import Path

import uvicorn


def main() -> None:
    root = Path("work/rkllm-live")
    root.mkdir(parents=True, exist_ok=True)
    os.environ["MODEL_PROVIDER"] = "rkllm"
    os.environ["RKLLM_SERVER_URL"] = os.environ.get("RKLLM_DEV_SERVER_URL", "http://127.0.0.1:8081/v1")
    os.environ["RKLLM_MODEL_NAME"] = os.environ.get("RKLLM_DEV_MODEL_NAME", "rkllm-mock")
    os.environ["MODEL_FALLBACK_ENABLED"] = "false"
    os.environ["AGENT_HOST"] = "127.0.0.1"
    os.environ["AGENT_PORT"] = os.environ.get("RKLLM_DEV_AGENT_PORT", "8000")
    os.environ["AGENT_DATABASE_PATH"] = str(root / "agent.db")
    os.environ["AGENT_AUDIT_DIR"] = str(root / "audit")
    os.environ["AGENT_FILE_OPEN_ENABLED"] = "false"
    uvicorn.run(
        "agent_platform.api:app",
        host="127.0.0.1",
        port=int(os.environ["AGENT_PORT"]),
        reload=False,
    )


if __name__ == "__main__":
    main()


__all__ = ["main"]
