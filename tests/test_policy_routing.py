import json

import pytest

from agent_platform.core.data_classification import DataClassificationService
from agent_platform.core.edge_cloud_router import EdgeCloudRouter
from agent_platform.core.errors import SensitiveDataError
from agent_platform.core.policy_engine import PolicyEngine
from agent_platform.core.resource_monitor import ResourceMonitor
from agent_platform.models import DataLevel, ExecutionTarget, PolicyContext, RiskLevel, RoutingRequest


D0_SAMPLES = [
    "今天天气很好", "打开年度报告", "查询产品说明", "会议下午开始", "设备运行正常", "hello world", "项目进展顺利",
    "提醒我喝水", "这是一段普通文本", "版本号 v1.2.3", "价格待确认", "联系人信息未提供", "公开新闻摘要", "本地任务",
    "文件名 report.txt", "百分比待定", "数字一二三", "短文本润色", "会议纪要", "普通用户名张三", "API 接口说明",
    "tokenization 是技术术语", "密码学基础", "secretary is a word", "邮箱地址未填写", "手机号未知", "身份证明流程",
    "202x is not a date", "库存充足", "设备重启方法",
]
SENSITIVE_SAMPLES = [
    ("电话 13800138000", DataLevel.D2),
    ("邮箱 user@example.com", DataLevel.D2),
    ("内部资料禁止外传", DataLevel.D2),
    ("confidential plan", DataLevel.D2),
    ("身份证 11010519491231002X", DataLevel.D3),
    ("password=abc123", DataLevel.D3),
    ("token: abcdefgh", DataLevel.D3),
    ("api_key=supersecret", DataLevel.D3),
    ("密钥 sk-abcdefghijklmnop", DataLevel.D3),
    ("AK-abcdefghijklmnop", DataLevel.D3),
    ("联系 13900000000", DataLevel.D2),
    ("mail a.b+c@company.cn", DataLevel.D2),
    ("机密项目", DataLevel.D2),
    ("secret = 123456", DataLevel.D3),
    ("passwd:qwerty", DataLevel.D3),
    ("token=longtokenvalue", DataLevel.D3),
    ("API-Key: value12345", DataLevel.D3),
    ("身份证号 320311770706001", DataLevel.D0),
    ("电话 12800138000", DataLevel.D0),
    ("email user@invalid", DataLevel.D0),
]


@pytest.mark.parametrize("text", D0_SAMPLES)
def test_normal_text_not_highly_classified(text):
    assert DataClassificationService().classify(text).level in {DataLevel.D0, DataLevel.D1}


@pytest.mark.parametrize("text,level", SENSITIVE_SAMPLES)
def test_sensitive_classification(text, level):
    assert DataClassificationService().classify(text).level == level


def test_d3_and_d2_outbound_blocked():
    service = DataClassificationService()
    with pytest.raises(SensitiveDataError):
        service.check_outbound("password=abc123")
    with pytest.raises(SensitiveDataError):
        service.check_outbound("13800138000")


@pytest.mark.parametrize(
    "role,domain,risk,allowed,confirmation",
    [
        ("user", "personal", RiskLevel.R0, True, False),
        ("user", "personal", RiskLevel.R1, True, False),
        ("user", "personal", RiskLevel.R2, True, True),
        ("user", "personal", RiskLevel.R3, False, False),
        ("user", "enterprise", RiskLevel.R0, False, False),
        ("admin", "enterprise", RiskLevel.R3, True, True),
        ("unknown", "personal", RiskLevel.R0, False, False),
    ],
)
def test_policy_matrix(role, domain, risk, allowed, confirmation):
    decision = PolicyEngine().evaluate(
        PolicyContext(role=role, data_domain=domain, risk_level=risk, data_level=DataLevel.D0, action="test")
    )
    assert decision.allowed is allowed
    assert decision.requires_confirmation is confirmation


def test_dynamic_delete_all_policy_promotes_risk_and_allows_user_confirmation():
    engine = PolicyEngine()
    arguments = {"action": "delete_all"}
    assert engine.resolve_risk("reminder_create", arguments, RiskLevel.R1) == RiskLevel.R3
    decision = engine.evaluate(
        PolicyContext(
            role="user",
            data_domain="personal",
            risk_level=RiskLevel.R3,
            data_level=DataLevel.D1,
            action="reminder_create",
            arguments=arguments,
        )
    )
    assert decision.allowed is True
    assert decision.requires_confirmation is True
    assert "全部提醒" in decision.confirmation.content


def test_dynamic_todo_delete_policy_requires_confirmation_with_target_id():
    engine = PolicyEngine()
    arguments = {"action": "delete", "id": 12}
    assert engine.resolve_risk("todo_manage", arguments, RiskLevel.R1) == RiskLevel.R2
    decision = engine.evaluate(
        PolicyContext(
            role="user",
            data_domain="personal",
            risk_level=RiskLevel.R2,
            data_level=DataLevel.D1,
            action="todo_manage",
            arguments=arguments,
        )
    )
    assert decision.allowed is True
    assert decision.requires_confirmation is True
    assert "12" in decision.confirmation.content
    assert decision.confirmation.reversible is False


def test_dynamic_schedule_cancel_policy_requires_confirmation_with_target_id():
    engine = PolicyEngine()
    arguments = {"action": "cancel", "id": 8}
    assert engine.resolve_risk("schedule_manage", arguments, RiskLevel.R1) == RiskLevel.R2
    decision = engine.evaluate(
        PolicyContext(
            role="user",
            data_domain="personal",
            risk_level=RiskLevel.R2,
            data_level=DataLevel.D1,
            action="schedule_manage",
            arguments=arguments,
        )
    )
    assert decision.requires_confirmation is True
    assert "8" in decision.confirmation.content


@pytest.mark.parametrize(
    "routing_request,mode,target",
    [
        (RoutingRequest(tool_name="x", local_tool_available=True, data_level=DataLevel.D0), "normal", ExecutionTarget.LOCAL),
        (RoutingRequest(tool_name="x", local_tool_available=False, data_level=DataLevel.D0), "normal", ExecutionTarget.CLOUD),
        (RoutingRequest(tool_name="x", local_tool_available=False, data_level=DataLevel.D2), "normal", ExecutionTarget.REJECTED),
        (RoutingRequest(tool_name="x", local_tool_available=True, data_level=DataLevel.D0), "high_load", ExecutionTarget.CLOUD),
        (RoutingRequest(tool_name="x", local_tool_available=False, data_level=DataLevel.D0, network_available=False), "normal", ExecutionTarget.QUEUE),
        (RoutingRequest(tool_name="x", local_tool_available=True, data_level=DataLevel.D0, user_preference=ExecutionTarget.CLOUD), "normal", ExecutionTarget.CLOUD),
        (RoutingRequest(tool_name="x", local_tool_available=True, data_level=DataLevel.D2, user_preference=ExecutionTarget.CLOUD), "normal", ExecutionTarget.LOCAL),
        (RoutingRequest(tool_name="x", local_tool_available=True, data_level=DataLevel.D0, network_available=False), "normal", ExecutionTarget.LOCAL),
        (RoutingRequest(tool_name="x", local_tool_available=True, data_level=DataLevel.D0, network_available=False), "throttled", ExecutionTarget.QUEUE),
    ],
)
def test_routing_scenarios(routing_request, mode, target):
    classifier = DataClassificationService()
    decision = EdgeCloudRouter(classifier).decide(routing_request, ResourceMonitor(mode).get_metrics())
    assert decision.target == target
