"""FastAPI application factory."""

from contextlib import asynccontextmanager
import html
import logging
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse, JSONResponse
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

DEFAULT_LOGIN_URL = "/#/login"


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

    def page_shell(name: str) -> HTMLResponse:
        """Serve a static page shell with the login bootstrap config injected.

        The pages themselves stay anonymous (contract §5); the config only
        tells the frontend where the RuoYi login page and logout endpoint
        live for this deployment topology.
        """

        text = (static_directory / name).read_text(encoding="utf-8")
        replacements = {
            "__RUOYI_LOGIN_URL__": application_settings.ruoyi_login_url or DEFAULT_LOGIN_URL,
            "__RUOYI_LOGOUT_URL__": application_settings.ruoyi_logout_url,
        }
        for placeholder, value in replacements.items():
            text = text.replace(placeholder, html.escape(value, quote=True))
        return HTMLResponse(text)

    @app.get("/", include_in_schema=False)
    @app.get("/index.html", include_in_schema=False)
    async def console_shell() -> HTMLResponse:
        return page_shell("index.html")

    @app.get("/developer.html", include_in_schema=False)
    async def developer_shell_asset() -> HTMLResponse:
        # Static-mount copy of the developer shell: same anonymous page, but
        # with the gateway config injected instead of raw placeholders.
        return page_shell("developer.html")

    @app.get("/developer", include_in_schema=False)
    @app.get("/developer/", include_in_schema=False)
    async def developer_console() -> HTMLResponse:
        # Anonymous page shell (contract §5): browsers cannot attach the
        # Authorization header to a navigation, so the console page loads like
        # any other shell and app.js enforces login + developer role client
        # side; all data endpoints remain behind the server-side JWT gate.
        return page_shell("developer.html")

    app.mount("/", StaticFiles(directory=static_directory, html=True), name="static")
    return app


__all__ = ["create_app"]
