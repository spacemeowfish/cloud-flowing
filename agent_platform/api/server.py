"""FastAPI application factory."""

from contextlib import asynccontextmanager
import logging
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from agent_platform.api.admin_routes import router as admin_router
from agent_platform.api.auth import require_developer, router as auth_router
from agent_platform.api.container import ApplicationContainer
from agent_platform.api.developer_routes import router as developer_router
from agent_platform.api.middleware import AuthenticationContextMiddleware, register_error_handlers
from agent_platform.api.routes import router
from agent_platform.api.voice_routes import router as voice_router
from agent_platform.config import Settings, get_settings
from agent_platform.core.desktop_settings import PassiveRestartController, RestartController
from agent_platform.core.recent_logs import RecentLogHandler


def create_app(
    settings: Settings | None = None,
    *,
    restart_controller: RestartController | None = None,
) -> FastAPI:
    application_settings = settings or get_settings()
    controller = restart_controller or PassiveRestartController()
    recent_logs = RecentLogHandler(secrets=(application_settings.ruoyi_jwt_secret,))
    access_logger = logging.getLogger("agent_platform.api.access")
    access_logger.setLevel(logging.INFO)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        container = ApplicationContainer.build(application_settings)
        app.state.container = container
        app.state.ruoyi_authenticator = container.ruoyi_auth
        logging.getLogger().addHandler(recent_logs)
        await container.initialize()
        try:
            yield
        finally:
            await container.close()
            logging.getLogger().removeHandler(recent_logs)

    app = FastAPI(
        title="Agent Platform MVP",
        version="0.1.0",
        description="Local-first task orchestration API",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.add_middleware(AuthenticationContextMiddleware)
    register_error_handlers(app)
    app.state.restart_controller = controller
    app.state.recent_logs = recent_logs
    app.include_router(auth_router)
    app.include_router(router)
    app.include_router(admin_router)
    app.include_router(voice_router)
    app.include_router(developer_router)
    static_directory = Path(__file__).parents[1] / "static"

    @app.get("/openapi.json", include_in_schema=False, dependencies=[Depends(require_developer)])
    async def protected_openapi() -> JSONResponse:
        return JSONResponse(app.openapi())

    @app.get("/docs", include_in_schema=False, dependencies=[Depends(require_developer)])
    async def protected_docs():
        return get_swagger_ui_html(openapi_url="/openapi.json", title=f"{app.title} - Swagger UI")

    @app.get("/developer", include_in_schema=False)
    @app.get("/developer/", include_in_schema=False)
    async def developer_console(request: Request) -> Response:
        if request.state.role != "developer":
            return RedirectResponse(url="/", status_code=303)
        return FileResponse(static_directory / "developer.html")

    app.mount("/", StaticFiles(directory=static_directory, html=True), name="static")
    return app


__all__ = ["create_app"]
