"""Container health check for both internal model and public Agent API."""

from urllib.request import urlopen


for endpoint in ("http://127.0.0.1:8080/health", "http://127.0.0.1:8000/health"):
    with urlopen(endpoint, timeout=3) as response:
        if response.status != 200:
            raise SystemExit(1)
