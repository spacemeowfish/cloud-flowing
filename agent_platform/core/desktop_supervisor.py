"""Supervised Uvicorn loop used by the Windows desktop trial command."""

from __future__ import annotations

import threading
import time
import webbrowser
from datetime import UTC, datetime
from pathlib import Path

import uvicorn

from agent_platform.api.server import create_app
from agent_platform.config import get_settings
from agent_platform.core.desktop_settings import restore_env_backup
from agent_platform.models.admin import RestartStatus


class DesktopRestartController:
    supervised = True

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._server: uvicorn.Server | None = None
        self._restart_requested = False
        self._backup_path: Path | None = None
        self._status = RestartStatus(
            state="starting",
            supervised=True,
            message="桌面服务正在启动",
        )

    def bind(self, server: uvicorn.Server) -> None:
        with self._lock:
            self._server = server

    def request_restart(self, backup_path: Path | None) -> None:
        with self._lock:
            self._restart_requested = True
            self._backup_path = backup_path
            self._status = RestartStatus(
                state="restarting",
                supervised=True,
                requested_at=datetime.now(UTC).isoformat(),
                message="配置已保存，服务正在重启",
            )
            server = self._server

        if server is not None:
            timer = threading.Timer(0.25, self._stop_bound_server, args=(server,))
            timer.daemon = True
            timer.start()

    @staticmethod
    def _stop_bound_server(server: uvicorn.Server) -> None:
        server.should_exit = True

    def restart_requested(self) -> bool:
        with self._lock:
            return self._restart_requested

    def mark_ready(self) -> None:
        with self._lock:
            now = datetime.now(UTC).isoformat()
            self._restart_requested = False
            self._backup_path = None
            self._status = RestartStatus(
                state="ready",
                supervised=True,
                requested_at=self._status.requested_at,
                completed_at=now,
                message="桌面服务已就绪",
                rollback_performed=self._status.rollback_performed,
            )

    def rollback(self, error: Exception | str) -> bool:
        with self._lock:
            backup = self._backup_path
        restored = restore_env_backup(backup)
        with self._lock:
            self._restart_requested = restored
            self._backup_path = None
            self._status = RestartStatus(
                state="rolling_back" if restored else "failed",
                supervised=True,
                requested_at=self._status.requested_at,
                message=f"新配置启动失败：{error}",
                rollback_performed=restored,
            )
        return restored

    def status(self) -> RestartStatus:
        with self._lock:
            return self._status.model_copy(deep=True)


def _watch_ready(
    server: uvicorn.Server,
    controller: DesktopRestartController,
    url: str,
    *,
    open_browser: bool,
    browser_state: list[bool],
) -> None:
    while not server.started and not server.should_exit:
        time.sleep(0.05)
    if not server.started:
        return
    controller.mark_ready()
    if open_browser and not browser_state[0]:
        browser_state[0] = True
        webbrowser.open(url)


def run_desktop(*, open_browser: bool = True) -> None:
    controller = DesktopRestartController()
    browser_state = [False]
    while True:
        try:
            get_settings.cache_clear()
            settings = get_settings()
            app = create_app(settings, restart_controller=controller)
        except Exception as exc:
            if controller.rollback(exc):
                continue
            raise

        config = uvicorn.Config(
            app,
            host=settings.host,
            port=settings.port,
            reload=False,
            log_level="info",
        )
        server = uvicorn.Server(config)
        controller.bind(server)
        # Cookies are host-scoped (not port-scoped): the RuoYi login popup runs
        # on "localhost", so the workbench must too or the Admin-Token cookie
        # set there stays invisible to the 127.0.0.1 page. Still loopback-only.
        browser_host = "localhost" if settings.host == "127.0.0.1" else settings.host
        url = f"http://{browser_host}:{settings.port}/"
        watcher = threading.Thread(
            target=_watch_ready,
            args=(server, controller, url),
            kwargs={"open_browser": open_browser, "browser_state": browser_state},
            daemon=True,
        )
        watcher.start()
        try:
            server.run()
        except KeyboardInterrupt:
            break
        except SystemExit as exc:
            if controller.restart_requested() and controller.rollback(exc):
                continue
            raise
        except Exception as exc:
            if controller.rollback(exc):
                continue
            raise
        if controller.restart_requested():
            if not server.started and controller.rollback("应用启动阶段未完成"):
                continue
            continue
        break


__all__ = ["DesktopRestartController", "run_desktop"]
