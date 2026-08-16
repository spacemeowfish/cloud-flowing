from pathlib import Path

import agent_platform.cli as cli


def test_evaluation_paths_default_to_project_root() -> None:
    project_root = Path(cli.__file__).resolve().parents[1]

    cases, output = cli._resolve_evaluation_paths(None, None)

    assert cases == project_root / "evaluation" / "test_cases"
    assert output == project_root / "evaluation" / "reports" / "latest.json"


def test_evaluation_paths_preserve_explicit_values(tmp_path: Path) -> None:
    cases = tmp_path / "cases"
    output = tmp_path / "report.json"

    assert cli._resolve_evaluation_paths(cases, output) == (cases, output)
