"""Configuration-driven role, domain, risk, and confirmation policy."""

from pathlib import Path

import yaml

from agent_platform.core.interfaces import Policy
from agent_platform.models import ConfirmationRequest, DataLevel, PolicyContext, PolicyDecision, RiskLevel


_RISK_ORDER = {RiskLevel.R0: 0, RiskLevel.R1: 1, RiskLevel.R2: 2, RiskLevel.R3: 3}


class PolicyEngine(Policy):
    def __init__(self, policy_path: Path | None = None, rules_path: Path | None = None) -> None:
        path = policy_path or Path(__file__).parents[1] / "config" / "policies.yaml"
        self._config = yaml.safe_load(path.read_text(encoding="utf-8"))
        action_path = rules_path or Path(__file__).parents[1] / "config" / "policy_rules.yaml"
        rules = yaml.safe_load(action_path.read_text(encoding="utf-8")).get("rules", [])
        self._rules_by_action: dict[str, tuple[dict[str, object], ...]] = {}
        for rule in rules:
            action = str(rule["action"])
            self._rules_by_action[action] = (*self._rules_by_action.get(action, ()), rule)

    def _matching_rule(self, context: PolicyContext) -> dict[str, object] | None:
        for rule in self._rules_by_action.get(context.action, ()):
            conditions = dict(rule.get("argument_conditions", {}))
            if all(context.arguments.get(key) == value for key, value in conditions.items()):
                return rule
        return None

    def resolve_risk(
        self,
        action: str,
        arguments: dict[str, object],
        default: RiskLevel,
    ) -> RiskLevel:
        context = PolicyContext(
            role="user",
            data_domain="personal",
            risk_level=default,
            data_level=DataLevel.D0,
            action=action,
            arguments=arguments,
        )
        rule = self._matching_rule(context)
        return RiskLevel(str(rule["risk_level"])) if rule else default

    def evaluate(self, context: PolicyContext) -> PolicyDecision:
        rule = self._matching_rule(context)
        role = self._config["roles"].get(context.role)
        if role is None:
            return PolicyDecision(allowed=False, reason="unknown_role")
        domains = role["domains"]
        if "*" not in domains and context.data_domain not in domains:
            return PolicyDecision(allowed=False, reason="data_domain_not_allowed")
        max_risk = RiskLevel(role["max_risk"])
        if _RISK_ORDER[context.risk_level] > _RISK_ORDER[max_risk]:
            allowed_roles = set(rule.get("allowed_roles", [])) if rule else set()
            if context.role not in allowed_roles:
                return PolicyDecision(allowed=False, reason="risk_exceeds_role_limit")
        if context.data_level == DataLevel.D3 and context.action.startswith("cloud:"):
            return PolicyDecision(allowed=False, reason="d3_cloud_forbidden")

        requires_confirmation = bool(rule and rule.get("requires_confirmation")) or (
            context.risk_level.value in self._config.get("confirm_risks", [])
        )
        confirmation = None
        if requires_confirmation:
            def render(field: str, default: str) -> str:
                template = str(rule.get(field, default)) if rule else default
                try:
                    return template.format(**context.arguments)
                except (KeyError, ValueError):
                    return template

            confirmation = ConfirmationRequest(
                title=render("title", "确认执行高风险操作"),
                target=context.action,
                content=render("message", f"将执行 {context.action}"),
                impact=render("impact", f"风险等级 {context.risk_level.value}"),
                reversible=bool(rule.get("reversible", context.risk_level != RiskLevel.R3)) if rule else context.risk_level != RiskLevel.R3,
            )
        return PolicyDecision(
            allowed=True,
            reason="allowed",
            requires_confirmation=requires_confirmation,
            confirmation=confirmation,
        )


__all__ = ["PolicyEngine"]
