"""Patch a pinned official RKLLM Flask demo for localhost-safe systemd use."""

from __future__ import annotations

import argparse
import ast
import hashlib
from pathlib import Path


HOST_EXPRESSION = 'os.environ.get("RKLLM_SERVER_HOST", "127.0.0.1")'
PORT_EXPRESSION = 'int(os.environ.get("RKLLM_SERVER_PORT", "8080"))'
FREQ_EXPRESSION = 'subprocess.run(command, shell=True) if os.environ.get("RKLLM_ALLOW_INPROCESS_FREQ", "0") == "1" else None'


def _position_offset(source: str, line: int, column: int) -> int:
    lines = source.splitlines(keepends=True)
    return sum(len(item) for item in lines[: line - 1]) + column


def _span(source: str, node: ast.AST) -> tuple[int, int]:
    if not hasattr(node, "end_lineno") or node.end_lineno is None or node.end_col_offset is None:
        raise ValueError("Python runtime does not expose AST source spans")
    return (
        _position_offset(source, node.lineno, node.col_offset),
        _position_offset(source, node.end_lineno, node.end_col_offset),
    )


def patch_server_source(source: str) -> str:
    tree = ast.parse(source)
    imports_os = any(
        isinstance(node, ast.Import) and any(alias.name == "os" for alias in node.names)
        for node in tree.body
    )
    if not imports_os:
        raise ValueError("official server source must import os")

    app_runs: list[ast.Call] = []
    frequency_calls: list[ast.Call] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if isinstance(node.func.value, ast.Name) and node.func.value.id == "app" and node.func.attr == "run":
                app_runs.append(node)
            if isinstance(node.func.value, ast.Name) and node.func.value.id == "subprocess" and node.func.attr == "run":
                frequency_calls.append(node)
    if len(app_runs) != 1 or len(frequency_calls) != 1:
        raise ValueError("expected exactly one app.run and one subprocess.run in the pinned official server")

    keywords = {keyword.arg: keyword.value for keyword in app_runs[0].keywords if keyword.arg}
    if "host" not in keywords or "port" not in keywords:
        raise ValueError("official app.run must define host and port keywords")
    replacements = [
        (*_span(source, keywords["host"]), HOST_EXPRESSION),
        (*_span(source, keywords["port"]), PORT_EXPRESSION),
        (*_span(source, frequency_calls[0]), FREQ_EXPRESSION),
    ]
    patched = source
    for start, end, replacement in sorted(replacements, reverse=True):
        patched = patched[:start] + replacement + patched[end:]
    ast.parse(patched)
    if HOST_EXPRESSION not in patched or FREQ_EXPRESSION not in patched:
        raise ValueError("patched server did not preserve required safety expressions")
    return patched


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source = args.source.read_text(encoding="utf-8")
    patched = patch_server_source(source)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(patched, encoding="utf-8")
    print(
        f"source_sha256={hashlib.sha256(source.encode('utf-8')).hexdigest()}\n"
        f"output_sha256={hashlib.sha256(patched.encode('utf-8')).hexdigest()}\n"
        f"output={args.output}"
    )


if __name__ == "__main__":
    main()


__all__ = ["FREQ_EXPRESSION", "HOST_EXPRESSION", "PORT_EXPRESSION", "patch_server_source"]
