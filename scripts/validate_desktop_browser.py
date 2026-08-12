"""Validate the desktop workbench through system Edge's DevTools protocol."""

from __future__ import annotations

import argparse
import base64
import json
import socket
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

import requests
import websocket


EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")


class DevTools:
    def __init__(self, url: str) -> None:
        self._socket = websocket.create_connection(url, timeout=10)
        self._counter = 0

    def call(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self._counter += 1
        request_id = self._counter
        self._socket.send(json.dumps({"id": request_id, "method": method, "params": params or {}}))
        while True:
            response = json.loads(self._socket.recv())
            if response.get("id") == request_id:
                if "error" in response:
                    raise RuntimeError(f"{method}: {response['error']}")
                return response.get("result", {})

    def evaluate(self, expression: str) -> Any:
        result = self.call(
            "Runtime.evaluate",
            {"expression": expression, "awaitPromise": True, "returnByValue": True},
        )
        value = result.get("result", {})
        if value.get("subtype") == "error":
            raise RuntimeError(value.get("description", "browser evaluation failed"))
        return value.get("value")

    def close(self) -> None:
        self._socket.close()


def _port() -> int:
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        return int(server.getsockname()[1])


def _wait_target(port: int) -> str:
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        try:
            targets = requests.get(f"http://127.0.0.1:{port}/json/list", timeout=1).json()
            page = next((target for target in targets if target.get("type") == "page"), None)
            if page:
                return str(page["webSocketDebuggerUrl"])
        except (requests.RequestException, ValueError, StopIteration):
            pass
        time.sleep(0.1)
    raise TimeoutError("Edge DevTools endpoint did not start")


def _wait(devtools: DevTools, expression: str, timeout: float = 15.0) -> Any:
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        last = devtools.evaluate(expression)
        if last:
            return last
        time.sleep(0.1)
    raise TimeoutError(f"browser condition did not pass: {expression}; last={last!r}")


def _navigate(devtools: DevTools, url: str, selector: str) -> None:
    devtools.call("Page.navigate", {"url": url})
    _wait(devtools, "document.readyState === 'complete'")
    _wait(devtools, f"Boolean(document.querySelector({json.dumps(selector)}))")
    time.sleep(0.3)


def _viewport(devtools: DevTools, width: int, height: int) -> None:
    devtools.call(
        "Emulation.setDeviceMetricsOverride",
        {"width": width, "height": height, "deviceScaleFactor": 1, "mobile": width < 500},
    )


def _metrics(devtools: DevTools) -> dict[str, Any]:
    return devtools.evaluate(
        """(() => {
          const html=document.documentElement, body=document.body, save=document.querySelector('.settings-save');
          const sidebar=document.querySelector('.sidebar'), inspector=document.querySelector('.inspector'), page=document.querySelector('.page-root');
          const presets=[...document.querySelectorAll('.voice-preset')];
          const boxes=[...document.querySelectorAll('input,textarea,select,button')].map(node=>node.getBoundingClientRect());
          const visible=boxes.filter(box=>box.right > 0 && box.left < innerWidth);
          const escaped=visible.filter(box=>box.left < -0.5 || box.right > innerWidth + 0.5).length;
          const rect=node=>{const box=node.getBoundingClientRect();return {left:box.left,right:box.right,width:box.width}};
          return {viewport:[innerWidth,innerHeight],html:[html.clientWidth,html.scrollWidth],body:[body.clientWidth,body.scrollWidth],presetCount:presets.length,escapedControls:escaped,save:save?{left:save.getBoundingClientRect().left,right:save.getBoundingClientRect().right,bottom:save.getBoundingClientRect().bottom}:null,sidebar:rect(sidebar),inspector:rect(inspector),page:rect(page),overflow:html.scrollWidth>html.clientWidth || body.scrollWidth>body.clientWidth || escaped>0};
        })()"""
    )


def _screenshot(devtools: DevTools, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = devtools.call("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False})["data"]
    path.write_bytes(base64.b64decode(encoded))


def run(base_url: str, screenshot_dir: Path) -> dict[str, Any]:
    if not EDGE.is_file():
        raise FileNotFoundError(f"system Edge not found: {EDGE}")
    port = _port()
    with tempfile.TemporaryDirectory(prefix="cloud-flowing-edge-") as profile:
        command = [
            str(EDGE),
            "--headless=new",
            "--disable-gpu",
            "--no-first-run",
            "--disable-default-apps",
            "--remote-allow-origins=*",
            f"--remote-debugging-port={port}",
            f"--user-data-dir={profile}",
            "about:blank",
        ]
        process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        devtools: DevTools | None = None
        try:
            devtools = DevTools(_wait_target(port))
            devtools.call("Page.enable")
            devtools.call("Runtime.enable")

            _viewport(devtools, 1440, 900)
            _navigate(devtools, f"{base_url}/#settings", "#settingsForm")
            desktop = _metrics(devtools)
            _screenshot(devtools, screenshot_dir / "desktop-settings-1440x900.png")

            _viewport(devtools, 390, 844)
            _navigate(devtools, f"{base_url}/#settings", "#settingsForm")
            mobile = _metrics(devtools)
            _screenshot(devtools, screenshot_dir / "desktop-settings-390x844.png")

            _navigate(devtools, f"{base_url}/#console", "#voiceButton")
            _wait(devtools, "!document.querySelector('#voiceButton').disabled")
            before = devtools.evaluate(
                "Promise.all([fetch('/tasks').then(r=>r.json()),fetch('/voice/status').then(r=>r.json())]).then(([tasks,voice])=>({taskCount:tasks.length,input:document.querySelector('#consoleText').value,voice}))"
            )
            devtools.evaluate("document.querySelector('#voiceButton').click(); true")
            recording = _wait(
                devtools,
                "fetch('/voice/status').then(r=>r.json()).then(v=>v.state==='recording' ? v : null)",
            )
            devtools.evaluate("document.querySelector('#voiceCancel').click(); true")
            cancelled = _wait(
                devtools,
                "fetch('/voice/status').then(r=>r.json()).then(v=>v.state==='idle' ? v : null)",
            )
            devtools.evaluate(
                """(() => {
                  window.__desktopValidationFetch = window.fetch;
                  window.fetch = (input, init={}) => {
                    if (String(input).endsWith('/voice/recordings') && init.method === 'POST') {
                      return Promise.resolve(new Response(JSON.stringify({code:'voice_device_unavailable',message:'麦克风设备不可用'}), {status:409,headers:{'content-type':'application/json'}}));
                    }
                    return window.__desktopValidationFetch(input, init);
                  };
                  document.querySelector('#voiceButton').click();
                  return true;
                })()"""
            )
            error_message = _wait(
                devtools,
                "document.querySelector('#voiceState').textContent === '麦克风设备不可用' ? document.querySelector('#voiceState').textContent : null",
            )
            devtools.evaluate("window.fetch=window.__desktopValidationFetch;delete window.__desktopValidationFetch;true")
            after = devtools.evaluate(
                "Promise.all([fetch('/tasks').then(r=>r.json()),fetch('/voice/status').then(r=>r.json())]).then(([tasks,voice])=>({taskCount:tasks.length,input:document.querySelector('#consoleText').value,voice}))"
            )
            voice = {
                "recording_state": recording["state"],
                "cancelled_state": cancelled["state"],
                "task_count_before": before["taskCount"],
                "task_count_after": after["taskCount"],
                "input_unchanged": before["input"] == after["input"],
                "error_message": error_message,
                "ok": recording["state"] == "recording"
                and cancelled["state"] == "idle"
                and before["taskCount"] == after["taskCount"]
                and before["input"] == after["input"]
                and error_message == "麦克风设备不可用",
            }
            mobile_drawers_hidden = mobile["sidebar"]["right"] <= 0 and mobile["inspector"]["left"] >= 390
            checks = [
                not desktop["overflow"],
                desktop["presetCount"] == 4,
                not mobile["overflow"] and mobile_drawers_hidden and mobile["page"]["width"] >= 389,
                voice["ok"],
            ]
            return {
                "browser": "Microsoft Edge system executable via CDP",
                "desktop": desktop,
                "mobile": mobile,
                "voice": voice,
                "screenshots": [
                    str(screenshot_dir / "desktop-settings-1440x900.png"),
                    str(screenshot_dir / "desktop-settings-390x844.png"),
                ],
                "pass_count": sum(checks),
                "check_count": len(checks),
            }
        finally:
            if devtools is not None:
                try:
                    devtools.call("Browser.close")
                except Exception:
                    pass
                devtools.close()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.terminate()
                process.wait(timeout=5)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8124")
    parser.add_argument("--screenshot-dir", type=Path, default=Path("work/browser-validation"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run(args.base_url, args.screenshot_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"pass_count": report["pass_count"], "check_count": report["check_count"]}))


if __name__ == "__main__":
    main()
