"""Deterministic D0-D3 detection, redaction, and outbound blocking."""

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from agent_platform.core.errors import SensitiveDataError
from agent_platform.core.interfaces import DataClassifier
from agent_platform.models import ClassificationResult, DataFinding, DataLevel


_LEVEL_ORDER = {DataLevel.D0: 0, DataLevel.D1: 1, DataLevel.D2: 2, DataLevel.D3: 3}


@dataclass(frozen=True)
class _Rule:
    name: str
    level: DataLevel
    pattern: re.Pattern[str]
    replacement: str


class DataClassificationService(DataClassifier):
    def __init__(self, rules_path: Path | None = None) -> None:
        path = rules_path or Path(__file__).parents[1] / "config" / "data_classification_rules.yaml"
        content = yaml.safe_load(path.read_text(encoding="utf-8"))
        self._rules = tuple(
            _Rule(item["name"], DataLevel(item["level"]), re.compile(item["pattern"]), item["replacement"])
            for item in content["rules"]
        )

    def classify(self, text: str) -> ClassificationResult:
        findings: list[DataFinding] = []
        occupied: list[tuple[int, int]] = []
        for rule in sorted(self._rules, key=lambda item: _LEVEL_ORDER[item.level], reverse=True):
            for match in rule.pattern.finditer(text):
                if any(match.start() < end and match.end() > start for start, end in occupied):
                    continue
                occupied.append((match.start(), match.end()))
                findings.append(
                    DataFinding(
                        level=rule.level,
                        kind=rule.name,
                        start=match.start(),
                        end=match.end(),
                        replacement=rule.replacement,
                    )
                )
        findings.sort(key=lambda item: item.start)
        redacted = text
        for finding in reversed(findings):
            redacted = redacted[: finding.start] + finding.replacement + redacted[finding.end :]
        level = max((item.level for item in findings), key=lambda item: _LEVEL_ORDER[item], default=DataLevel.D0)
        return ClassificationResult(level=level, findings=findings, redacted_text=redacted)

    def redact_for_model(self, text: str, *, cloud: bool = False) -> ClassificationResult:
        result = self.classify(text)
        if result.level == DataLevel.D3:
            return result
        if cloud and result.level == DataLevel.D2:
            return result
        return result

    def check_outbound(self, text: str) -> ClassificationResult:
        result = self.classify(text)
        if result.level == DataLevel.D3:
            raise SensitiveDataError("D3 data is forbidden from leaving the device")
        if result.level == DataLevel.D2:
            raise SensitiveDataError("D2 data is local-only by default")
        return result


__all__ = ["DataClassificationService"]

