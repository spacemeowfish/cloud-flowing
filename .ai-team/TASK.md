# Current Task

- ID: `PC-COLLEAGUE-SETUP-002`
- Title: `回传 PC 实测问题：winget DO 下载器卡死 + check.mjs 门禁解析缺陷 + ZipVoice espeak-ng-data 非 ASCII 路径崩溃`
- Status: `handoff`
- Owner: `qkx-yytj`
- Next owner: `spacemeowfish/reviewer`

## Goal

同事在 Windows PC 按指南完成真实下载和人工功能验收时，发现三个问题并通过独立分支和 PR 回传：1) `winget` 默认 DeliveryOptimization（DO）下载器在代理环境下无法完成 GitHub 下载——Ollama/Python 安装卡在接近 100% 并产出全零文件，需要在 `winget install` 前切换 WinINet 下载器；2) `.ai-team/check.mjs` 的 `section()` 正则把 TASK.md 每个 section 截断到第一行，导致门禁的"验收/验证完整性"校验失效，需要修复；3) ZipVoice TTS 在非 ASCII（中文）路径下崩溃——sherpa-onnx 捆绑的 espeak-ng（C 代码）无法读取含非 ASCII 字符的 espeak-ng-data 路径（`Illegal byte sequence`），且应用未设置 `ESPEAK_DATA_PATH`，需要适配器把 espeak-ng-data 解析到 ASCII 临时目录。模型、音频、本机配置和测试数据必须留在 Git 之外。

本任务不制作或分发含第三方模型和音色的离线包，不扩展 Windows 安装器、托盘、自启动、唤醒词、常驻监听、会议录音、流式 TTS 或真实外部连接器。

## Acceptance scenarios

- [x] `scripts/Setup-PC-Test.ps1` 新增 `Enable-WinGetWinINetDownloader`，并在 `Install-PythonIfMissing`（Python 3.12）与 `Install-OllamaIfMissing`（Ollama）的 `winget install` 之前调用，把下载器配置为 WinINet。
- [x] 修复 `.ai-team/check.mjs` 的 `section()` 正则截断缺陷（`(?=^## |$)` → `(?=^## |(?![\\s\\S]))`），完整解析 TASK.md 每个 section；修复前后验收项 1/1 → 6 项、验证项 1/1 → 10 项。
- [x] 修复 ZipVoice 在非 ASCII 路径下的崩溃：`zipvoice_tts.py` 新增 `_espeak_data_dir()`（检测非 ASCII 路径 → 复制 espeak-ng-data 到 ASCII 临时目录并按源路径 hash 缓存，加载引擎前设置 `ESPEAK_DATA_PATH` + `data_dir`）；本机 API 端到端生成成功（24 秒出 WAV，有声音）。
- [x] 新增专项测试：winget WinINet 内容断言（两处 winget 安装前先启用 WinINet）、Ollama winget 集成回归（真实 PowerShell 执行并校验 `settings.json`）、指南条目断言、espeak-data 路径解析（ASCII 直用 / 非 ASCII 复制）；并把新函数加入既有 Python 回退 harness 的函数提取列表。
- [x] 同事指南 `docs/testing/COLLEAGUE-PC-SETUP.md` 常见问题节补充 DO 下载器卡死说明与 WinINet 配置路径。
- [x] PowerShell parser、`-PlanOnly` 演练、专项测试、全量回归 412 项、compileall、前端语法、`git diff --check`、check.mjs 门禁两向验证（先错后对）全部通过。
- [ ] 当前代码、文档、测试和任务证据进入同一个 PR，并由仓库所有者审查合并。

## Invariants

- Qwen、LFM、Faster-Whisper、ZipVoice、vocoder、参考 WAV、`.env`、数据库、日志及用户数据不得进入 Git。
- 服务只监听 `127.0.0.1`；PC 测试不得提升为 RK3588、NPU、实体音响、远场麦克风、功耗、温控或长稳验收结论。
- 对比模型（lfm2.5-thinking:1.2b）的已知质量失败必须保留，不能通过放松安全门禁伪装成通过。
- 代码改动必须与 `.ai-team/TASK.md` 更新在同一个 PR；check.mjs 门禁在只改代码时会拒绝。

## Decisions

- 本机已存在 `.venv` 与 Ollama，winget 修复通过专项测试与真实 PowerShell harness 验证，不在本机实际重跑 winget 安装（避免破坏现有环境）；真实安装路径由后续未装环境复验。
- WinINet 配置写入 `%LOCALAPPDATA%\Packages\Microsoft.DesktopAppInstaller_8wekyb3d8bbwe\LocalState\settings.json`，`{"network":{"downloader":"wininet"}}`，UTF-8 无 BOM（与脚本写 `.env` 的方式一致）。
- check.mjs 修复采用 JS 惯用绝对末尾 `(?![\\s\\S])` 替代 `$`（`\z` 在 JS 正则中不受支持，已排除）。
- 开发前已同步最新上游（`nannncy` 的 PR #4 已合并，测试 407 项），本修复基于最新 `main` 的 `fix/pc-test-winget-do-downloader` 分支。

## Completed

- 已复现 winget DO 下载器问题：`winget install` 拉取 GitHub 托管包实测 4 次全部卡在接近 99%，产出文件魔数 `0000`（全零）。
- 已新增 `Enable-WinGetWinINetDownloader` 并在两处 `winget install` 前调用。
- 已修复 `.ai-team/check.mjs` `section()` 正则截断缺陷，并用 node 对比测试验证修复前后解析差异。
- 已新增 3 项专项测试（`test_setup_script_forces_winget_wininet_downloader`、`test_ollama_winget_install_forces_wininet_downloader`、`test_colleague_guide_mentions_winget_wininet_downloader`），并把 `Enable-WinGetWinINetDownloader` 加入既有 Python 回退 harness 的函数提取列表。
- 已定位并修复 ZipVoice 非 ASCII 路径崩溃：真实参考 WAV（单声道 PCM16 16kHz 30s）+ 逐字文本配置合法且 `tts.ready=true`，但生成崩溃；日志定位为 espeak-ng-data 路径问题，经纯 ASCII 路径复制实验确认根因（espeak-ng C 代码无法读中文路径）。已新增 `_espeak_data_dir()` + 2 项单元测试，本机 API 端到端生成成功。
- 已同步最新上游（PR #4 合并后 407 项基线），专项 + 全量 412 项回归通过。
- 已完成 check.mjs 门禁两向验证：仅改代码 → `Result: blocked`（`Code or product files changed without updating .ai-team/TASK.md in the same PR`）；代码 + TASK.md 同分支 → `Result: valid`。

## Pending

- 等待仓库所有者审查本 PR（`fix/pc-test-winget-do-downloader`）、运行 CI 并合并。
- 本机已有 Ollama，无法在本机完整复现 winget 安装路径；WinINet 修复需在另一台无环境的 Windows PC 上复验真实下载。
- 麦克风转写与合法音色 TTS 已在本机完成实测；其他 Windows PC 的真实模型验收与 TTS 音质评估仍属后续独立验收。

## Next step

将本分支 `fix/pc-test-winget-do-downloader` 推送至同事 Fork，并向 `spacemeowfish/cloud-flowing:main` 创建 PR；仓库所有者审查合并后，本问题修复进入上游。后续继续其他 Windows PC 的真实模型验收，并将其他问题继续通过独立分支和 PR 回传。

## Verification

- [x] PowerShell parser：`scripts/Setup-PC-Test.ps1`
- [x] `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/Setup-PC-Test.ps1 -PlanOnly`：通过，且无 `.env`/`.local-models/` 改动
- [x] `python -m pytest -q tests/test_pc_test_setup_script.py -p no:cacheprovider`：9 项通过
- [x] `python -m pytest -q tests/test_speech_output.py -p no:cacheprovider`：8 项通过（含 espeak-data 路径解析 2 项新增）
- [x] `python -m pytest -q -p no:cacheprovider`：412 项通过（`--collect-only` 收集 412 项）
- [x] `python -m compileall -q agent_platform evaluation deployment packaging scripts`
- [x] `node --check agent_platform/static/app.js`
- [x] `git diff --check`
- [x] `node .ai-team/check.mjs --base upstream/main`（仅改代码）：`Result: blocked`，验证门禁强制"代码与 TASK.md 同 PR"
- [x] `node .ai-team/check.mjs --base upstream/main`（代码 + TASK.md）：`Result: valid`
- [x] ZipVoice API 端到端：`POST /tasks/{id}/speech` 生成成功（24 秒出 WAV，单声道 24kHz，有声音）
- [x] 变更文件私有路径、密钥及二进制状态扫描

## Handoff note

- From: `qkx-yytj`
- To: `spacemeowfish/reviewer`
- Summary: 同事在 Windows PC 真实验收时发现三个问题并回传：① winget DO 下载器在代理环境无法完成 GitHub 下载（已在 Python/Ollama 两处 `winget install` 前切换 WinINet）；② check.mjs `section()` 门禁解析截断（已修复并验证解析完整性）；③ ZipVoice 在非 ASCII 路径下 espeak-ng-data 崩溃（已新增 ASCII 临时目录解析并设置 `ESPEAK_DATA_PATH`，本机 API 端到端生成成功）。麦克风转写与 TTS 已实测。专项/全量测试（412 项）、`-PlanOnly` 演练与门禁两向验证均通过，请审查 PR 并合并。
