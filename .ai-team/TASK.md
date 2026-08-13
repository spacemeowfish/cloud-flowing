# Current Task

- ID: `PC-COLLEAGUE-SETUP-001`
- Title: `同事 Fork 后一键准备 PC 测试环境与模型`
- Status: `active`
- Owner: `Codex`
- Next owner: `spacemeowfish/reviewer`

## Goal

让同事从自己的 GitHub Fork 获取云湃 Agent 后，通过一个 Windows PowerShell 脚本准备 Python、项目语音依赖、Ollama、Qwen2.5、LFM2.5 和 Faster-Whisper；按需下载 ZipVoice 与 vocoder，并使用本人或公司已授权参考音频完成 PC 内部测试。模型、音频、本机配置和测试数据必须留在 Git 之外。

本任务不制作或分发含第三方模型和音色的离线包，不扩展 Windows 安装器、托盘、自启动、唤醒词、常驻监听、会议录音、流式 TTS 或真实外部连接器。此前 `PC-OFFLINE-BUNDLE-001` 的实现与许可阻塞保留在 `docs/tasks/2026-08-13-windows-offline-internal-bundle.md` 和 `docs/releases/2026-08-13-windows-offline-local-validation.md`。

## Acceptance scenarios

- [x] 同事指南覆盖 Fork、Clone、`origin/upstream`、一键准备、启动、真实功能检查、问题记录和跨 Fork PR。
- [ ] PowerShell 脚本可重复执行，准备 Python 3.12、`.[dev,tts,voice]`、Ollama、`qwen2.5:3b`、`lfm2.5-thinking:1.2b` 和固定版本 Faster-Whisper small；`py.exe` 无 3.12 runtime 的回退修复仍需在报告问题的 Windows PC 上复验。
- [x] 可选 ZipVoice 流程使用固定官方 URL 和 SHA256 下载模型与 vocoder；安全选择性解压跳过上游 `test_wavs`，不保留、伪造或启用未经授权的参考音色。
- [x] 脚本把本机资产放入被忽略的 `.local-models/`，仅更新被忽略的 `.env`；模型、音频、密钥和个人路径不进入 Git。
- [x] 脚本 PowerShell 语法、`-PlanOnly` 无下载演练、专项测试、全量回归和 VibeCollab 检查全部通过。
- [ ] 当前代码、文档、测试和任务证据进入同一个 PR，并由仓库所有者审查合并。

## Invariants

- 同事自行下载不消除模型许可证条件；脚本必须在下载前提示并要求确认 Qwen 和 LFM 条款。
- Qwen、LFM、Faster-Whisper、ZipVoice、vocoder、参考 WAV、`.env`、数据库、日志及用户数据不得进入 Git。
- ZipVoice 默认保持禁用；只有测试人员配置了合法参考 WAV 和逐字匹配文本后才启用。
- 服务只监听 `127.0.0.1`；PC 测试不得提升为 RK3588、NPU、实体音响、远场麦克风、功耗、温控或长稳验收结论。
- Mock、Qwen、LFM、Faster-Whisper 和 ZipVoice 的结果分别记录，不能相互替代。

## Decisions

- 源码获取采用同事 Fork：`origin` 指向同事 Fork，`upstream` 指向 `spacemeowfish/cloud-flowing`。
- 一键脚本为 `scripts/Setup-PC-Test.ps1`；默认安装 Qwen、LFM 和 Faster-Whisper，`-IncludeZipVoice` 显式加入 ZipVoice 与 vocoder。
- Ollama 模型使用项目已经验证的标签；Faster-Whisper 和 ZipVoice 使用固定版本/URL及 SHA256，避免静默漂移。
- ZipVoice 不提供参考音色下载；同事使用本人录制或公司明确授权的单声道 PCM WAV，并提供逐字文本。
- ZipVoice 上游归档自带示例 WAV；脚本使用 Python 标准库选择性解压并跳过 `test_wavs`，随后删除归档，避免示例音色进入本机模型目录。
- `-PlanOnly` 用于不产生下载或配置修改的脚本路径验证，不代表真实模型下载和推理验收。

## Completed

- 2026-08-13 已从远端 `main` 合并提交 `f1adb8bc4c76f8c958734d8bafc7cb436cea87a2` 创建独立 worktree 和分支 `docs/colleague-pc-setup`。
- 已确认用户电脑当前离线验证构建中存在 ZipVoice 模型和 vocoder；旧 `.data\zipvoice` 路径目前不存在。具体本机绝对路径不写入 Git。
- 已核对仓库锁文件、现有本机资产哈希、Ollama 官方模型标签和 sherpa-onnx 官方下载入口。
- 已新增一键准备脚本、同事中文指南、专项契约测试和 `.local-models/` 忽略规则。
- 已用真实官方 ZipVoice 归档验证安全选择性解压：保留 359 个运行文件，`test_wavs` 目录和 WAV 文件均为 0，decoder SHA256 与锁定值一致；临时验证目录随后已删除。
- 另一台 Windows PC 真实测试发现：存在 `py.exe` 但无 Python 3.12 runtime 时，Python 探测产生终止错误，脚本未进入 `winget` 自动安装流程。
- 已最小修复 Python 探测错误处理，使该场景继续回退 `winget`，并补充执行实际函数路径的 PowerShell 回归测试。
- 已在同事指南中补充 `py.exe` 无 runtime 时回退 `winget` 的说明，并让回归测试覆盖这条文档约束。
- 已在同事指南中补充 `-IncludeZipVoice` 仍默认保持禁用、需要手动启用 ZipVoice 的说明，并让测试覆盖这条文档约束。
- 已修正 ZipVoice 默认禁用说明的测试归属：脚本测试验证 `TTS_PROVIDER=disabled` 行为，指南测试验证中文操作说明，避免把指南文案错误绑定到 PowerShell 脚本。
- PowerShell parser、`-PlanOnly -IncludeZipVoice`、6 项专项测试、407 项全量测试、Python 编译、前端语法、VibeCollab、私有路径及二进制状态扫描均通过。

## Pending

- 在报告问题的 Windows PC 上重新执行 `scripts/Setup-PC-Test.ps1`，确认真实 `py.exe` 无 runtime 场景可进入 `winget` 并继续完成环境准备。
- 将本次缺陷修复、回归测试、指南和 `TASK.md` 同步更新作为同一个提交追加到 PR #3；当前按用户要求不提交、不推送。
- 等待 PR #3 的 CI 与仓库所有者审查。
- 同事在另一台 Windows PC 实际下载和执行真实模型/ASR/TTS测试；这部分不能由本机 PlanOnly 代替。

## Next step

先在报告问题的 Windows PC 复验 Python 3.12 自动安装回退；通过后将代码、测试、指南和 `TASK.md` 一起提交并更新 PR #3，再由仓库所有者审查 CI 与改动。合并后继续真实模型、ASR 和 TTS 人工验收，并将其他问题通过独立分支和 PR 回传。

## Verification

- [x] PowerShell parser：`scripts/Setup-PC-Test.ps1`
- [x] `powershell -File scripts/Setup-PC-Test.ps1 -PlanOnly -IncludeZipVoice`：通过，且前后均未生成 `.env` 或 `.local-models/`
- [x] `python -m pytest -q tests/test_pc_test_setup_script.py -p no:cacheprovider`：6 项通过；因当前 `.venv` 启动器引用的基础 Python 已不存在，本次使用工作区提供的 Python 3.12.13 临时加载 `.venv` 中现有 pytest 依赖，并把 `--basetemp` 指向工作区内临时目录执行，未修改或安装依赖
- [x] `python -m pytest --collect-only -q -p no:cacheprovider`：收集 407 项；`python -m pytest -q -p no:cacheprovider`：407 项通过。本次与专项测试相同，使用工作区 Python 3.12.13 临时加载 `.venv` 中已有依赖并指定工作区 `--basetemp`
- [x] `python -m compileall -q agent_platform evaluation deployment packaging scripts`
- [x] `node --check agent_platform/static/app.js`
- [x] `git diff --check`
- [x] `node .ai-team/check.mjs --base origin/main`
- [x] 真实 ZipVoice 归档过滤：359 个运行文件、0 个 WAV、0 个 `test_wavs` 目录；decoder SHA256 匹配
- [x] 变更文件私有路径、密钥及二进制状态扫描

## Handoff note

- From: `Codex`
- To: `spacemeowfish/reviewer`
- Summary: 当前仍为 `active`，尚未重新 handoff。`py.exe` 无 Python 3.12 runtime 的回退缺陷已完成最小修复和自动化回归；先由报告问题的 Windows PC 复验，随后再将同一组代码、测试、指南与任务证据交给 reviewer 审查。真实模型推理、麦克风和合法音色 TTS 仍需独立验收，不能由本机自动化或 PlanOnly 代替。
