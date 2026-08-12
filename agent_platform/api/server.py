"""FastAPI application factory."""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from agent_platform.api.admin_routes import router as admin_router
from agent_platform.api.container import ApplicationContainer
from agent_platform.api.middleware import AuthenticationContextMiddleware, register_error_handlers
from agent_platform.api.routes import router
from agent_platform.api.voice_routes import router as voice_router
from agent_platform.config import Settings, get_settings
from agent_platform.core.desktop_settings import PassiveRestartController, RestartController


def create_app(
    settings: Settings | None = None,
    *,
    restart_controller: RestartController | None = None,
) -> FastAPI:
    application_settings = settings or get_settings()
    controller = restart_controller or PassiveRestartController()

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
    app.state.restart_controller = controller
    app.include_router(router)
    app.include_router(admin_router)
    app.include_router(voice_router)
    static_directory = Path(__file__).parents[1] / "static"
    app.mount("/", StaticFiles(directory=static_directory, html=True), name="static")
    return app


__all__ = ["create_app"]
