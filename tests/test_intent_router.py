import pytest

from agent_platform.core.intent_router import pre_route_intent


@pytest.mark.parametrize(
    ("text", "intent"),
    [
        (r"整理会议纪要 C:\docs\周会.txt", "meeting_process"),
        ("找会议记录", "file_open"),
        ("待办：1小时后检查服务", "reminder_create"),
        ("添加待办 检查服务", "todo_manage"),
        ("每周一上午9点提醒我开会", "reminder_create"),
        ("创建日程 每周一上午9点开会", "schedule_manage"),
        ("总结这段：完成三个项目", "text_polish"),
        ("调整为正式语气：本季度完成了三个项目，分别覆盖知识库、工作流和接口验证。", "text_polish"),
        ("调整为正式语气：麻烦大家记得下午一点开会", "text_polish"),
        ("查询产品保修期", "knowledge_query"),
        ("1+1等于多少？", "general_chat"),
        ("十二加八等于多少", "general_chat"),
        ("把你好翻译成英文", "general_chat"),
        ("什么是局域网？", "general_chat"),
        ("什么是产品经理？", "general_chat"),
    ],
)
def test_pre_router_only_selects_high_confidence_intents(text, intent):
    decision = pre_route_intent(text)
    assert decision is not None
    assert decision.intent == intent


def test_pre_router_leaves_ambiguous_request_for_model_classification():
    assert pre_route_intent("帮我处理一下这个事情") is None
