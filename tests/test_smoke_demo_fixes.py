"""Regression tests for the manual smoke defect fixes S1-S8 (SMOKE-FIXPLAN.md)."""

import asyncio
from pathlib import Path

import httpx
import pytest
from pydantic import JsonValue

from agent_platform.adapters.platform import DisabledFileOpener
from agent_platform.api.server import create_app
from agent_platform.config import Settings
from agent_platform.tools.file_search_tool import FileSearchTool


def _settings(tmp_path, **updates):
    values = {
        "_env_file": None,
        "model_provider": "mock",
        "database_path": tmp_path / "agent.db",
        "audit_dir": tmp_path / "audit",
        "authorized_file_roots": [tmp_path / "files"],
        "knowledge_roots": [tmp_path / "knowledge"],
        "document_roots": [tmp_path / "documents"],
        "meeting_output_dir": tmp_path / "meeting",
        "developer_password": "dev-pass-123",
        "audit_flush_size": 1,
    }
    values.update(updates)
    return Settings(**values)


async def _wait_for_state(client, task_id, expected, timeout=3.0):
    states = {expected} if isinstance(expected, str) else set(expected)
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        response = await client.get(f"/tasks/{task_id}")
        assert response.status_code == 200
        task = response.json()
        if task["state"] in states:
            return task
        await asyncio.sleep(0.02)
    raise AssertionError(f"task {task_id} did not reach {states}")


# ---------------------------------------------------------------------------
# S6: disabled file opener must be reported honestly.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_file_open_reports_disabled_configuration(tmp_path):
    root = tmp_path / "documents"
    root.mkdir()
    target = root / "会议纪要_需求评审.txt"
    target.write_text("内容", encoding="utf-8")
    tool = FileSearchTool([root], DisabledFileOpener())

    receipt = await tool.execute({"query": "会议纪要", "selected_path": str(target)})

    assert receipt.success is True
    assert receipt.output["process_status"] == "disabled_by_configuration"
    assert "已在配置中禁用" in receipt.output_summary
    assert "AGENT_FILE_OPEN_ENABLED=false" in receipt.output_summary
    assert "文件处理完成" not in receipt.output_summary


@pytest.mark.asyncio
async def test_file_open_summary_unchanged_when_opener_active(tmp_path):
    class _ActiveOpener:
        async def open(self, path):
            return {"path": str(path), "process_status": "shell_request_accepted"}

    root = tmp_path / "documents"
    root.mkdir()
    target = root / "会议纪要_需求评审.txt"
    target.write_text("内容", encoding="utf-8")
    tool = FileSearchTool([root], _ActiveOpener())

    receipt = await tool.execute({"query": "会议纪要", "selected_path": str(target)})

    assert receipt.success is True
    assert receipt.output_summary == f"文件处理完成：{target.name}"


# ---------------------------------------------------------------------------
# S8: zero-hit file search must degrade instead of returning nothing.
# ---------------------------------------------------------------------------


def _weekly_report_root(tmp_path):
    root = tmp_path / "documents"
    root.mkdir()
    names = [
        "项目周报_20260714.txt",
        "项目周报_20260721.txt",
        "项目周报_20260728.txt",
        "项目周报_20260804.txt",
        "项目周报模板.txt",
        "IT安全规范.md",
    ]
    for name in names:
        (root / name).write_text("内容", encoding="utf-8")
    return root


def test_search_degrades_modified_keyword_to_hits(tmp_path):
    root = _weekly_report_root(tmp_path)
    tool = FileSearchTool([root], DisabledFileOpener())

    hits = tool.search("这周的项目周报")

    assert {Path(hit["path"]).name for hit in hits} == {
        "项目周报_20260714.txt",
        "项目周报_20260721.txt",
        "项目周报_20260728.txt",
        "项目周报_20260804.txt",
        "项目周报模板.txt",
    }


def test_search_whole_sentence_wrapper_fallback(tmp_path):
    root = _weekly_report_root(tmp_path)
    tool = FileSearchTool([root], DisabledFileOpener())

    hits = tool.search("帮我找一下周报")

    assert len(hits) == 5
    assert all("周报" in Path(hit["path"]).name for hit in hits)


def test_search_bare_keyword_hits_unchanged(tmp_path):
    root = _weekly_report_root(tmp_path)
    tool = FileSearchTool([root], DisabledFileOpener())

    hits = tool.search("周报")
    bare_names = [Path(hit["path"]).name for hit in hits]

    assert len(bare_names) == 5
    assert "IT安全规范.md" not in bare_names
    degraded = tool.search("这周的项目周报")
    assert [Path(hit["path"]).name for hit in degraded] == bare_names


def test_search_bigram_fallback_matches_scattered_pairs(tmp_path):
    root = tmp_path / "documents"
    root.mkdir()
    (root / "分级据分数据.txt").write_text("内容", encoding="utf-8")
    (root / "会议纪要_需求评审.txt").write_text("内容", encoding="utf-8")
    tool = FileSearchTool([root], DisabledFileOpener())

    # 顺序子序列匹配失败，但全部相邻二元组都在文件名中出现，bigram 兜底应命中。
    hits = tool.search("数据分级")

    assert [Path(hit["path"]).name for hit in hits] == ["分级据分数据.txt"]
