"""Regression tests for the routing-boundary review fixes."""

from pathlib import Path

import pytest

from agent_platform.core.agent_core import _capability_boundary
from agent_platform.core.intent_router import pre_route_intent
from agent_platform.core.parameter_normalizer import deterministic_pre_route_arguments
from agent_platform.core.voice_input import VoiceInputService
from agent_platform.tools.file_search_tool import FileSearchTool


class _Noop:
    def open(self, path):  # pragma: no cover - never reached
        raise AssertionError("opener must not be called in search tests")


def _file_tool(tmp_path: Path) -> FileSearchTool:
    (tmp_path / "项目周报_20260714.txt").write_text("d", encoding="utf-8")
    (tmp_path / "项目周报_20260804.txt").write_text("d", encoding="utf-8")
    (tmp_path / "待办任务清单_本周.txt").write_text("d", encoding="utf-8")
    (tmp_path / "员工请假制度.md").write_text("d", encoding="utf-8")
    return FileSearchTool([tmp_path], _Noop())  # type: ignore[arg-type]


class TestKnowledgeQuestionExemption:
    def test_content_question_with_completion_word_is_not_rejected(self):
        assert (
            _capability_boundary(
                "knowledge_query", "项目周报_20260804中完成了什么", {"query": "项目周报_20260804中完成了什么"}
            )
            is None
        )

    def test_action_word_without_question_marker_still_rejected(self):
        boundary = _capability_boundary("knowledge_query", "查询会议室使用规则并预约一下", {"query": "会议室使用规则"})
        assert boundary is not None and boundary[0] == "unsupported"

    @pytest.mark.parametrize(
        "question",
        [
            "周报里提到哪些风险",
            "请假制度怎么规定的",
            "报告说明了如何整改吗",
            "文档里有多少条流程",
        ],
    )
    def test_question_forms_pass(self, question):
        assert _capability_boundary("knowledge_query", question, {"query": question}) is None


class TestFileQueryCleaning:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("查看项目周报", "项目周报"),
            ("待办清单文件在哪", "待办清单"),
            ("查找文件：员工请假制度", "员工请假制度"),
            ("打开 项目周报_20260804", "项目周报_20260804"),
            ("帮我看看会议室使用规则文件", "会议室使用规则"),
        ],
    )
    def test_wrapper_strips_command_words(self, text, expected):
        arguments = deterministic_pre_route_arguments("file_open", text)
        assert arguments == {"query": expected}


class TestFileSearchMatching:
    def test_spoken_query_matches_filename_with_extra_words(self, tmp_path):
        tool = _file_tool(tmp_path)
        names = [candidate["name"] for candidate in tool.search("待办清单")]
        assert names == ["待办任务清单_本周.txt"]

    def test_cleaned_query_matches_dated_reports(self, tmp_path):
        tool = _file_tool(tmp_path)
        names = [candidate["name"] for candidate in tool.search("项目周报")]
        assert set(names) == {"项目周报_20260714.txt", "项目周报_20260804.txt"}

    def test_unrelated_files_are_not_matched_by_subsequence(self, tmp_path):
        tool = _file_tool(tmp_path)
        assert tool.search("会议纪要") == []


class TestMeetingRoomBooking:
    def test_booking_prefix_routes_to_schedule(self):
        decision = pre_route_intent("预约 A301 会议室")
        assert decision is not None and decision.intent == "schedule_manage"

    def test_booking_without_space_routes_to_schedule(self):
        decision = pre_route_intent("预约A301会议室")
        assert decision is not None and decision.intent == "schedule_manage"

    def test_booking_deterministic_arguments_keep_location(self):
        arguments = deterministic_pre_route_arguments("schedule_manage", "预约 A301 会议室")
        assert arguments is not None
        assert arguments["action"] == "create"
        assert arguments["location"] == "A301"
        # 裸预约句式无时刻，start_text 留空交给 schema 预检转中文补充闸门。
        assert "start_text" not in arguments

    def test_roomless_booking_has_no_location(self):
        arguments = deterministic_pre_route_arguments("schedule_manage", "帮我预约会议室")
        assert arguments is not None and "location" not in arguments

    def test_query_wording_still_goes_to_knowledge(self):
        decision = pre_route_intent("查询会议室使用规则")
        assert decision is not None and decision.intent == "knowledge_query"


class _FakeTranscriber:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.prewarmed = False

    def transcribe(self, samples):  # pragma: no cover - unused
        raise AssertionError

    def prewarm(self) -> None:
        self.prewarmed = True
        if self.fail:
            raise RuntimeError("model missing")


class TestVoicePrewarm:
    def test_prewarm_loads_transcriber_model(self, tmp_path):
        transcriber = _FakeTranscriber()
        service = VoiceInputService.__new__(VoiceInputService)
        service._settings = type("S", (), {"voice_enabled": True, "voice_model_dir": tmp_path})()
        service._backend = None
        service._transcriber = transcriber
        service._lock = None
        service._active = None
        assert service.prewarm() is True
        assert transcriber.prewarmed is True

    def test_prewarm_swallows_loader_failure(self, tmp_path):
        transcriber = _FakeTranscriber(fail=True)
        service = VoiceInputService.__new__(VoiceInputService)
        service._settings = type("S", (), {"voice_enabled": True, "voice_model_dir": tmp_path})()
        service._backend = None
        service._transcriber = transcriber
        service._lock = None
        service._active = None
        assert service.prewarm() is False

    def test_prewarm_skips_when_disabled(self, tmp_path):
        transcriber = _FakeTranscriber()
        service = VoiceInputService.__new__(VoiceInputService)
        service._settings = type("S", (), {"voice_enabled": False, "voice_model_dir": tmp_path})()
        service._backend = None
        service._transcriber = transcriber
        service._lock = None
        service._active = None
        assert service.prewarm() is False
        assert transcriber.prewarmed is False
