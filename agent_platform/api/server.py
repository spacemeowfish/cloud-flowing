"""FastAPI application factory."""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from agent_platform.api.container import ApplicationContainer
from agent_platform.api.middleware import AuthenticationContextMiddleware, register_error_handlers
from agent_platform.api.routes import router
from agent_platform.config import Settings, get_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    application_settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        container = ApplicationContainer.build(application_settings)
        app.state.container = container
        await container.initialize()
        try:
            yield
        finally:
            await container.close()

    app = FastAPI(
        title="Agent Platform MVP",
        version="0.1.0",
        description="Local-first task orchestration API",
        lifespan=lifespan,
    )
    app.add_middleware(AuthenticationContextMiddleware)
    register_error_handlers(app)
    app.include_router(router)
    static_directory = Path(__file__).parents[2] / "static"
    app.mount("/", StaticFiles(directory=static_directory, html=True), name="static")
    return app


__all__ = ["create_app"]
