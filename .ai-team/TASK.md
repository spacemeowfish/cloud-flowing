# Current Task

- ID: `CLI-EVALUATION-PATH-001`
- Title: `从项目根目录解析评测默认路径`
- Status: `handoff`
- Owner: `Codex`
- Next owner: `spacemeowfish/reviewer`

## Goal

让 `agent-platform evaluate` 在调用者没有传入 `--cases` 或 `--output` 时，始终从已安装项目的根目录解析固定评测集和默认报告路径，而不依赖当前 PowerShell 工作目录；当评测目录缺失或没有 JSON 用例时，返回包含实际路径和修复建议的明确错误。

本任务不运行真实模型，不修改评测集、评分逻辑、模型配置、TTS、ASR 或浏览器界面。

## Acceptance scenarios

- [x] 未传入路径时，评测用例解析到项目根目录下的 `evaluation/test_cases`。
- [x] 未传入路径时，报告解析到项目根目录下的 `evaluation/reports/latest.json`。
- [x] 显式传入 `--cases` 或 `--output` 时原值保持不变。
- [x] 用例目录不存在或没有 `*.json` 时，在模型调用前返回明确路径错误。
- [ ] 代码、回归测试和当前 TASK 进入同一个 PR，并由仓库所有者审查合并。

## Invariants

- 默认评测集仍为仓库固定用例，不改变用例内容、数量或评分门槛。
- 显式 CLI 参数优先于默认路径。
- 报告、模型输出和本机配置不得因本任务进入 Git。

## Decisions

- 使用 `Path(__file__).resolve().parents[1]` 识别项目根目录，避免依赖 `cwd`。
- 将默认路径解析抽成内部纯函数，直接覆盖默认值和显式值两类行为。
- 缺少数据集时先检查目录和 JSON 文件，再进入 `EvaluationService.load_cases`。

## Completed

- 已修复默认评测用例和报告路径对当前工作目录的依赖。
- 已补充评测目录缺失时的可操作错误信息。
- 已新增默认路径和显式路径单元测试。
- 专项测试 2 项、全量收集和回归 414 项、编译、前端语法、差异检查及仓库同步门禁均通过。

## Pending

- 提交 TASK 与测试，推送独立分支并创建 PR。
- 等待仓库所有者审查、CI 和合并。

## Next step

完成验证后把状态切换为 `handoff`，提交并推送 `codex/evaluation-path-resolution`，创建独立 PR 交由仓库所有者审查；合并后从最新 `main` 启动用户分组与双界面任务。

## Verification

- [x] `python -m pytest -q tests/test_cli.py -p no:cacheprovider`：2 项通过
- [x] `python -m pytest --collect-only -q -p no:cacheprovider`：收集 414 项
- [x] `python -m pytest -q -p no:cacheprovider`：414 项通过
- [x] `python -m compileall -q agent_platform evaluation deployment packaging scripts`
- [x] `node --check agent_platform/static/app.js`
- [x] `git diff --check`
- [x] `node .ai-team/check.mjs --base origin/main`

## Handoff note

- From: `Codex`
- To: `spacemeowfish/reviewer`
- Summary: 默认评测路径已改为基于项目根目录解析，并新增缺失数据集错误与回归测试；专项 2 项和全量 414 项通过，交由 reviewer 审查。
