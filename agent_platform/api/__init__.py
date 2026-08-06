"""ASGI application export."""

from agent_platform.api.server import create_app

app = create_app()

__all__ = ["app", "create_app"]

