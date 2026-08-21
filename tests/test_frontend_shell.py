"""Phase 4 frontend login integration: page-shell gateway config injection.

The console shells must load anonymously (contract §5) and carry the RuoYi
login/logout bootstrap config (settings RUOYI_LOGIN_URL / RUOYI_LOGOUT_URL) so
the frontend knows where to send unauthenticated visitors, independent of the
deployment topology (standalone loopback vs reverse-proxy /agent-api prefix).
"""

from __future__ import annotations

import httpx
import pytest

from agent_platform.api.server import create_app
from agent_platform.config import Settings
from tests.ruoyi_support import TEST_JWT_SECRET_B64, enable_gateway


def _settings(tmp_path, **overrides) -> Settings:
    allowed = tmp_path / "allowed"
    knowledge = tmp_path / "knowledge"
    allowed.mkdir(exist_ok=True)
    knowledge.mkdir(exist_ok=True)
    base = dict(
        model_provider="mock",
        database_path=tmp_path / "agent.db",
        audit_dir=tmp_path / "audit",
        authorized_file_roots=[allowed],
        knowledge_roots=[knowledge],
        meeting_output_dir=tmp_path / "meeting",
        audit_flush_size=1,
        ruoyi_jwt_secret=TEST_JWT_SECRET_B64,
        # Pinned so a developer's local .env overrides (e.g. a dev-proxy
        # RUOYI_LOGOUT_URL) cannot leak into these contract assertions.
        ruoyi_login_url="",
        ruoyi_logout_url="/prod-api/logout",
    )
    base.update(overrides)
    return Settings(**base)


async def _client(app):
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


@pytest.mark.asyncio
async def test_console_shell_serves_defaults_anonymously(tmp_path):
    app = create_app(_settings(tmp_path))
    async with app.router.lifespan_context(app):
        async with await _client(app) as client:
            response = await client.get("/")
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/html")
            # Reverse-proxy topology defaults: RuoYi is the site root.
            assert 'data-login-url="/#/login"' in response.text
            assert 'data-logout-url="/prod-api/logout"' in response.text
            # Assets referenced relatively so the shell works under a prefix.
            assert 'src="app.js"' in response.text
            # The retired password-gate dialog is gone.
            assert "developerLogin" not in response.text


@pytest.mark.asyncio
async def test_console_shell_injects_configured_urls(tmp_path):
    app = create_app(
        _settings(
            tmp_path,
            ruoyi_login_url="http://localhost:8081/#/login",
            ruoyi_logout_url="/dev-api/logout",
        )
    )
    async with app.router.lifespan_context(app):
        async with await _client(app) as client:
            shell = await client.get("/")
            assert shell.status_code == 200
            assert 'data-login-url="http://localhost:8081/#/login"' in shell.text
            assert 'data-logout-url="/dev-api/logout"' in shell.text
            # Every HTML entry point is served through the injecting routes,
            # so raw placeholders never reach the browser.
            for path in ("/index.html", "/developer.html"):
                copy = await client.get(path)
                assert copy.status_code == 200
                assert "__RUOYI_LOGIN_URL__" not in copy.text


@pytest.mark.asyncio
async def test_developer_shell_gated_and_injected(tmp_path):
    app = create_app(_settings(tmp_path))
    async with app.router.lifespan_context(app):
        gateway = enable_gateway(app)
        async with await _client(app) as client:
            # Anonymous navigation: the shell loads (browsers cannot attach
            # Authorization headers to navigations); app.js's login gate and
            # role check take over client-side.
            anonymous = await client.get("/developer")
            assert anonymous.status_code == 200
            assert 'data-login-url="/#/login"' in anonymous.text
            assert 'data-logout-url="/prod-api/logout"' in anonymous.text
            client.headers["Authorization"] = f"Bearer {gateway.issue(username='dev1', user_id=101, role_keys=('developer',))}"
            page = await client.get("/developer")
            assert page.status_code == 200
            assert 'data-login-url="/#/login"' in page.text
            assert 'data-logout-url="/prod-api/logout"' in page.text
