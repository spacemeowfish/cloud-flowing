"""Run isolated post-hardening workflows against one local Ollama model.

The fixed evaluator measures the model contract in a dry-run container.  This
script complements it with real tool execution while keeping every database,
authorized file, and meeting output under a temporary directory.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import tempfile
from pathlib import Path
from typing import Any

from agent_platform.api.container import ApplicationContainer
from agent_platform.config import Settings
from agent_platform.core.parameter_normalizer import normalize_arguments
from agent_platform.models import TaskConfirmation, TaskCreate, TaskRecord, TaskState


def _scrub(value: Any, root: Path) -> Any:
    """Make temporary paths stable before writing the evidence JSON."""

    if isinstance(value, str):
        return value.replace(str(root), "<isolated>")
    if isinstance(value, dict):
        return {str(key): _scrub(item, root) for key, item in value.items()}
    if isinstance(value, list):
        return [_scrub(item, root) for item in value]
    return value


def _view(task: TaskRecord | None, root: Path) -> dict[str, Any] | None:
    if task is None:
        return None
    return _scrub(
        {
            "id": str(task.id),
            "state": task.state.value,
            "error": task.error,
            "risk_level": task.risk_level.value,
            "context": task.context,
            "result": task.result,
        },
        root,
    )


def _receipt_output(task: TaskRecord | dict[str, Any] | None) -> dict[str, Any]:
    if task is None:
        return {}
    result = task.result if isinstance(task, TaskRecord) else task.get("result")
    if not isinstance(result, dict) or not result:
        return {}
    receipt = result.get("receipt") if result.get("type") == "candidate_confirmation" else result
    if not isinstance(receipt, dict):
        return {}
    output = receipt.get("output")
    return output if isinstance(output, dict) else {}


def _item_id(task: TaskRecord | None, key: str = "item") -> int | None:
    item = _receipt_output(task).get(key)
    if isinstance(item, dict) and isinstance(item.get("id"), int):
        return int(item["id"])
    return None


async def run_model(model: str, digest: str, base_url: str) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="agent-platform-three-model-") as temporary:
        root = Path(temporary)
        authorized = root / "authorized_files"
        knowledge = root / "knowledge"
        meeting_output = root / "meeting_notes"
        authorized.mkdir()
        knowledge.mkdir()
        meeting_output.mkdir()

        (knowledge / "产品保修政策.txt").write_text(
            "产品保修政策\n本产品整机保修期为两年，售后联系电话为 400-123-4567。\n",
            encoding="utf-8",
        )
        for name in ("项目周报_20260801.txt", "项目周报_20260802.md", "项目周报_归档.txt"):
            (authorized / name).write_text(f"{name}\n项目进展正常。\n", encoding="utf-8")
        meeting_source = authorized / "项目评审会议.txt"
        meeting_source.write_text(
            "张三：确认八月八日发布。\n李四：负责发布检查，截止明天完成。\n",
            encoding="utf-8",
        )

        settings = Settings(
            model_provider="ollama",
            model_name=model,
            model_digest=digest,
            ollama_base_url=base_url,
            ollama_thinking_enabled=False,
            ollama_timeout_seconds=180.0,
            ollama_max_new_tokens=512,
            database_path=root / "agent_platform.db",
            audit_dir=root / "audit",
            authorized_file_roots=[authorized],
            knowledge_roots=[knowledge],
            meeting_output_dir=meeting_output,
            file_open_enabled=False,
            network_available=True,
        )
        container = ApplicationContainer.build(settings)
        await container.initialize()
        cases: list[dict[str, Any]] = []

        async def run_case(
            name: str,
            prompt: str,
        ) -> TaskRecord | None:
            initial: TaskRecord | None = None
            final: TaskRecord | None = None
            error: str | None = None
            try:
                initial = await container.agent.submit(
                    TaskCreate(text=prompt, session_id=f"validation-{model}")
                )
                final = initial
            except Exception as exc:  # Keep later function probes running.
                error = f"{type(exc).__name__}: {exc}"
            cases.append(
                {
                    "name": name,
                    "prompt": prompt,
                    "initial": _view(initial, root),
                    "final": _view(final, root),
                    "exception": error,
                }
            )
            return final

        async def confirm_case(
            name: str,
            source: TaskRecord,
            prompt: str,
            arguments: dict[str, Any] | None = None,
        ) -> TaskRecord | None:
            """Approve an existing confirmation without sending a second model request."""

            final: TaskRecord | None = None
            error: str | None = None
            try:
                final = await container.agent.confirm(
                    source.id,
                    TaskConfirmation(arguments=arguments or {}, approved=True),
                )
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
            cases.append(
                {
                    "name": name,
                    "prompt": prompt,
                    "initial": _view(source, root),
                    "final": _view(final, root),
                    "exception": error,
                }
            )
            return final

        def can_approve(task: TaskRecord | None) -> bool:
            """Only approve a real risk/candidate preview, never a missing-field stop."""

            return bool(task and task.state == TaskState.AWAITING_CONFIRMATION and task.result and task.result.get("type") in {"risk_confirmation", "candidate_confirmation"})

        # Knowledge and authorized-file flows.
        knowledge_task = await run_case("knowledge_query", "查询知识库：产品保修期是多久？")
        general_math = await run_case("general_chat_math", "1+1等于多少？")
        general_common = await run_case("general_chat_common", "请用一句话说明局域网是什么？")
        general_translation = await run_case("general_chat_translation", "把你好翻译成英文")
        file_task = await run_case("file_search_candidates", "查找并打开文件：项目周报")
        candidates = _receipt_output(file_task).get("candidates", [])
        selected_path = candidates[0].get("path") if candidates and isinstance(candidates[0], dict) else None
        if selected_path and can_approve(file_task):
            await confirm_case(
                "file_candidate_confirmation",
                file_task,
                "确认打开项目周报候选",
                {"selected_path": selected_path},
            )

        # Reminder CRUD and human-readable body/query behavior.
        reminder_one = await run_case("reminder_create_one", "提醒我明天上午九点提交三模型报告")
        reminder_two = await run_case("reminder_create_two", "后天下午两点提醒我复核回归结果")
        reminder_query = await run_case("reminder_query_multiple", "查看未来7天提醒")
        reminder_one_id = _item_id(reminder_one)
        reminder_two_id = _item_id(reminder_two)
        if reminder_one_id:
            await run_case("reminder_complete_by_id", f"完成提醒 ID {reminder_one_id}")
        if reminder_two_id:
            await run_case("reminder_cancel_by_id", f"取消提醒 {reminder_two_id}")
        delete_all = await run_case("reminder_delete_all_preview", "清空全部提醒")
        if can_approve(delete_all):
            await confirm_case(
                "reminder_delete_all_confirmed",
                delete_all,
                "确认清空全部提醒",
            )
        await run_case("reminder_query_after_delete", "查看未来7天提醒")

        # Todo CRUD, status filters, and ID-addressed update/delete.
        todo_one = await run_case("todo_create_one", "添加待办 提交三模型报告")
        todo_two = await run_case("todo_create_two", "添加待办 回归测试，高优先级")
        await run_case("todo_query_all", "查看全部待办")
        todo_one_id = _item_id(todo_one)
        todo_two_id = _item_id(todo_two)
        if todo_one_id:
            await run_case("todo_update_status", f"更新待办 ID {todo_one_id} 为进行中")
        if todo_two_id:
            await run_case("todo_complete_by_id", f"完成待办 ID {todo_two_id}")
        await run_case("todo_query_in_progress", "查看进行中的待办")
        await run_case("todo_query_completed", "查看已完成待办")
        if todo_one_id:
            delete_todo = await run_case("todo_delete_preview", f"删除待办 {todo_one_id}")
            if can_approve(delete_todo):
                await confirm_case("todo_delete_confirmed", delete_todo, "确认删除待办")
        await run_case("todo_query_after_delete", "查看全部待办")

        # Schedule parsing/query/cancellation, including financial Chinese numerals.
        schedule = await run_case(
            "schedule_create_uppercase_numerals",
            "创建日程 二〇二六年八月十八日上午九点到上午十点 产品评审",
        )
        await run_case("schedule_query_by_title", "查询日程 产品评审")
        schedule_id = _item_id(schedule)
        if schedule_id:
            cancel_schedule = await run_case("schedule_cancel_preview", f"取消日程 {schedule_id}")
            if can_approve(cancel_schedule):
                await confirm_case("schedule_cancel_confirmed", cancel_schedule, "确认取消日程")

        # User-reported text fixtures: three inputs x five operations.
        text_fixtures = {
            "date_budget": "项目将在2026年8月1日上线，预算为300万元。",
            "three_projects": "本季度完成了三个项目，分别覆盖知识库、工作流和接口验证。",
            "submit_materials": "请尽快提交材料。",
        }
        operations = {
            "polish": "润色",
            "summarize": "总结这段",
            "formal": "调整为正式语气",
            "casual": "调整为轻松语气",
            "draft": "草拟",
        }
        text_case_names: list[str] = []
        for fixture, source_text in text_fixtures.items():
            for operation, prefix in operations.items():
                name = f"text_{fixture}_{operation}"
                text_case_names.append(name)
                await run_case(name, f"{prefix}：{source_text}")

        # Ten serial mixed requests include repeated mutations so stability also
        # proves the executor's idempotency cache prevents duplicate side effects.
        stability_prompts = (
            "1+1等于多少？",
            "查询知识库：产品保修期是多久？",
            "润色：请尽快提交材料。",
            "查找并打开文件：项目周报",
            "明天下午四点提醒我执行稳定性检查",
            "明天下午四点提醒我执行稳定性检查",
            "添加待办 稳定性检查",
            "添加待办 稳定性检查",
            "把你好翻译成英文",
            "请用一句话说明局域网是什么？",
        )
        stability_names: list[str] = []
        for index in range(10):
            name = f"stability_{index + 1:02d}"
            stability_names.append(name)
            await run_case(name, stability_prompts[index])

        # Meeting permission boundary, confirmation, and Markdown artifact.
        meeting = await run_case("meeting_process_preview", f"整理会议纪要 {meeting_source}")
        if can_approve(meeting):
            await confirm_case("meeting_process_confirmed", meeting, "确认生成会议纪要")

        def completed(name: str) -> bool:
            matching = [item for item in cases if item["name"] == name]
            return bool(matching and matching[-1]["final"] and matching[-1]["final"]["state"] == "completed")

        def final_result(name: str) -> dict[str, Any]:
            matching = [item for item in cases if item["name"] == name]
            return matching[-1]["final"] if matching else {}

        knowledge_output = _receipt_output(knowledge_task)
        knowledge_ok = (
            completed("knowledge_query")
            and "两年" in str(knowledge_output.get("answer", ""))
            and bool(knowledge_output.get("sources"))
        )
        general_results = [general_math, general_common, general_translation]
        general_answers = [str(_receipt_output(item).get("answer", "")) for item in general_results]
        general_ok = (
            all(item is not None and item.state == TaskState.COMPLETED for item in general_results)
            and "2" in general_answers[0]
            and bool(general_answers[1])
            and bool(general_answers[2])
            and all("<FACT_" not in answer and "占位符" not in answer for answer in general_answers)
        )
        file_ok = bool(candidates) and any(
            item["name"] == "file_candidate_confirmation"
            and item["final"]
            and item["final"]["state"] == "completed"
            for item in cases
        )
        reminder_items = _receipt_output(reminder_query).get("items", [])
        reminder_texts = [str(item.get("text", "")) for item in reminder_items if isinstance(item, dict)]
        reminder_delete = next((item for item in cases if item["name"] == "reminder_delete_all_confirmed"), None)
        reminder_delete_output = _receipt_output(reminder_delete.get("final") if reminder_delete else None)
        reminder_after_delete = next((item for item in cases if item["name"] == "reminder_query_after_delete"), None)
        reminder_after_items = _receipt_output(reminder_after_delete.get("final") if reminder_after_delete else None).get("items", [])
        reminder_ok = (
            len(reminder_items) >= 2
            and all("提醒我" not in text for text in reminder_texts)
            and completed("reminder_complete_by_id")
            and completed("reminder_cancel_by_id")
            and reminder_delete_output.get("deleted_count") == 2
            and completed("reminder_delete_all_confirmed")
            and completed("reminder_query_after_delete")
            and reminder_after_items == []
        )
        todo_query_all = next((item for item in cases if item["name"] == "todo_query_all"), None)
        todo_items = _receipt_output(todo_query_all.get("final") if todo_query_all else None).get("items", [])
        update_case = next((item for item in cases if item["name"] == "todo_update_status"), None)
        update_item = _receipt_output(update_case.get("final") if update_case else None).get("item", {})
        complete_case = next((item for item in cases if item["name"] == "todo_complete_by_id"), None)
        complete_item = _receipt_output(complete_case.get("final") if complete_case else None).get("item", {})
        todo_in_progress = next((item for item in cases if item["name"] == "todo_query_in_progress"), None)
        todo_completed = next((item for item in cases if item["name"] == "todo_query_completed"), None)
        delete_case = next((item for item in cases if item["name"] == "todo_delete_confirmed"), None)
        after_todo = next((item for item in cases if item["name"] == "todo_query_after_delete"), None)
        after_todo_items = _receipt_output(after_todo.get("final") if after_todo else None).get("items", [])
        todo_ok = (
            len(todo_items) >= 2
            and completed("todo_update_status")
            and isinstance(update_item, dict)
            and update_item.get("status") == "in_progress"
            and completed("todo_complete_by_id")
            and isinstance(complete_item, dict)
            and complete_item.get("status") == "completed"
            and len(_receipt_output(todo_in_progress.get("final") if todo_in_progress else None).get("items", [])) == 1
            and len(_receipt_output(todo_completed.get("final") if todo_completed else None).get("items", [])) == 1
            and completed("todo_delete_confirmed")
            and len(after_todo_items) == 1
        )
        schedule_output = _receipt_output(schedule)
        schedule_item = schedule_output.get("item")
        schedule_ok = (
            completed("schedule_create_uppercase_numerals")
            and isinstance(schedule_item, dict)
            and str(schedule_item.get("start_at", "")).startswith("2026-08-18T09:00")
            and str(schedule_item.get("end_at", "")).startswith("2026-08-18T10:00")
            and completed("schedule_query_by_title")
            and completed("schedule_cancel_confirmed")
        )
        text_results = {name: final_result(name) for name in text_case_names}
        text_failures: list[dict[str, str]] = []
        for name, result in text_results.items():
            task_result = result.get("result") or {}
            task_output = task_result.get("output") or {}
            output = str(task_output.get("text", "")).strip()
            fixture = next(key for key in text_fixtures if name.startswith(f"text_{key}_"))
            operation = name.rsplit("_", 1)[-1]
            reason = ""
            if result.get("state") != "completed" or not output:
                reason = f"terminal={result.get('state')}"
            elif any(marker in output for marker in ("<FACT_", "FACT_", "占位符", "提示词", "【草稿】", "ext{FACT")):
                reason = "internal_marker"
            elif re.search(r"(?:确保|以便|从而|流程的|并且|同时)[，、 ]*$", output):
                reason = "truncated_sentence"
            elif re.search(r"[A-Za-z]{4,}\s+[A-Za-z]{4,}", output) and not re.search(r"[\u4e00-\u9fff]", output):
                reason = "language_drift"
            elif fixture == "date_budget" and ("2026年8月1日" not in output or "300万元" not in output):
                reason = "lost_date_or_budget"
            elif fixture == "three_projects" and not all(term in output for term in ("三个项目", "知识库", "工作流", "接口验证")):
                reason = "lost_project_fact"
            elif operation == "casual" and output == text_fixtures[fixture]:
                reason = "tone_unchanged"
            if reason:
                text_failures.append({"case": name, "reason": reason, "output": output})
        text_ok = not text_failures
        stability_results = [final_result(name) for name in stability_names]
        stability_failures = [
            {"case": name, "state": result.get("state"), "error": result.get("error")}
            for name, result in zip(stability_names, stability_results, strict=True)
            if result.get("state") not in {"completed", "awaiting_confirmation"} or result.get("error")
        ]
        stability_reminders = [
            item for item in container.reminders.query("next_7_days")
            if item.get("text") == "执行稳定性检查"
        ]
        stability_todos = (
            await container.todos.execute(
                {"action": "query", "status": "all", "title_query": "稳定性检查"}
            )
        ).output.get("items", [])
        side_effects_ok = len(stability_reminders) == 1 and len(stability_todos) == 1
        meeting_ok = any(
            item["name"] == "meeting_process_confirmed"
            and item["final"]
            and item["final"]["state"] == "completed"
            for item in cases
        ) and any(meeting_output.glob("*-会议纪要.md"))

        # A direct tool-layer control separates deterministic parser behavior
        # from model field extraction quality.
        direct_schedule = await container.schedules.execute(
            {
                "action": "create",
                "title": "确定性结束时间控制",
                "start_text": "贰零贰陆年捌月拾捌日上午玖点到十点",
            }
        )
        direct_item = direct_schedule.output.get("item", {})
        controls = {
            "schedule_uppercase_parser": {
                "ok": str(direct_item.get("start_at", "")).startswith("2026-08-18T09:00")
                and str(direct_item.get("end_at", "")).startswith("2026-08-18T10:00"),
                "start_at": direct_item.get("start_at"),
                "end_at": direct_item.get("end_at"),
            },
            "reminder_clear_alias": {
                "ok": normalize_arguments(
                    intent="reminder_create", arguments={}, request_text="清空全部提醒"
                ).arguments
                == {"action": "delete_all"},
            },
        }
        summary = {
            "knowledge_query": {"ok": knowledge_ok, "sources": knowledge_output.get("sources", []), "answer": knowledge_output.get("answer")},
            "general_chat": {"ok": general_ok, "answers": general_answers},
            "file_open": {"ok": file_ok, "candidate_count": len(candidates), "file_open_enabled": False},
            "reminder_create_query_mutation": {"ok": reminder_ok, "query_count_before_mutation": len(reminder_items), "texts": reminder_texts},
            "todo_crud_status_update": {"ok": todo_ok, "query_count_before_mutation": len(todo_items)},
            "schedule_create_query_cancel": {"ok": schedule_ok, "item": schedule_item},
            "text_processing": {"ok": text_ok, "case_count": len(text_results), "failures": text_failures},
            "meeting_process": {"ok": meeting_ok, "output_count": len(list(meeting_output.glob("*-会议纪要.md")))},
        }
        await container.close()
        return {
            "model": model,
            "model_digest": digest,
            "provider": "ollama",
            "thinking_enabled": False,
            "isolated": True,
            "cases": cases,
            "summary": summary,
            "controls": controls,
            "stability": {
                "ok": not stability_failures and side_effects_ok,
                "request_count": len(stability_results),
                "failures": stability_failures,
                "reminder_count": len(stability_reminders),
                "todo_count": len(stability_todos),
                "duplicate_side_effects": not side_effects_ok,
            },
            "pass_count": sum(bool(item["ok"]) for item in summary.values()),
            "function_count": len(summary),
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--digest", default="unknown")
    parser.add_argument("--base-url", default="http://127.0.0.1:11434")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = asyncio.run(run_model(args.model, args.digest, args.base_url))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"model": args.model, "summary": result["summary"], "pass_count": result["pass_count"], "function_count": result["function_count"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
