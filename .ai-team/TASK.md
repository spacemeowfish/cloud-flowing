# Current Task

- ID: `PC-COLLEAGUE-SETUP-001`
- Title: `同事 Fork 后一键准备 PC 测试环境与模型`
- Status: `handoff`
- Owner: `Codex`
- Next owner: `spacemeowfish/reviewer`

## Goal

让同事从自己的 GitHub Fork 获取云湃 Agent 后，通过一个 Windows PowerShell 脚本准备 Python、项目语音依赖、Ollama、Qwen2.5、LFM2.5 和 Faster-Whisper；按需下载 ZipVoice 与 vocoder，并使用本人或公司已授权参考音频完成 PC 内部测试。模型、音频、本机配置和测试数据必须留在 Git 之外。

本任务不制作或分发含第三方模型和音色的离线包，不扩展 Windows 安装器、托盘、自启动、唤醒词、常驻监听、会议录音、流式 TTS 或真实外部连接器。此前 `PC-OFFLINE-BUNDLE-001` 的实现与许可阻塞保留在 `docs/tasks/2026-08-13-windows-offline-internal-bundle.md` 和 `docs/releases/2026-08-13-windows-offline-local-validation.md`。

## Acceptance scenarios

- [x] 同事指南覆盖 Fork、Clone、`origin/upstream`、一键准备、启动、真实功能检查、问题记录和跨 Fork PR。
- [x] PowerShell 脚本可重复执行，准备 Python 3.12、`.[dev,tts,voice]`、Ollama、`qwen2.5:3b`、`lfm2.5-thinking:1.2b` 和固定版本 Faster-Whisper small。
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
- PowerShell parser、`-PlanOnly -IncludeZipVoice`、5 项专项测试、406 项全量测试、Python 编译、前端语法、VibeCollab、私有路径及二进制状态扫描均通过。
- 已提交并推送实现提交 `07430e4`，创建 PR #3：`https://github.com/spacemeowfish/cloud-flowing/pull/3`。

## Pending

- 等待 PR #3 的 CI 与仓库所有者审查。
- 同事在另一台 Windows PC 实际下载和执行真实模型/ASR/TTS测试；这部分不能由本机 PlanOnly 代替。

## Next step

仓库所有者审查 PR 与 CI；合并后由同事按指南在另一台 Windows PC 执行真实下载和人工功能验收，并将问题通过独立分支和 PR 回传。

## Verification

- [x] PowerShell parser：`scripts/Setup-PC-Test.ps1`
- [x] `powershell -File scripts/Setup-PC-Test.ps1 -PlanOnly -IncludeZipVoice`：通过，且前后均未生成 `.env` 或 `.local-models/`
- [x] `python -m pytest -q tests/test_pc_test_setup_script.py -p no:cacheprovider`：5 项通过
- [x] `python -m pytest -q -p no:cacheprovider`：406 项通过
- [x] `python -m compileall -q agent_platform evaluation deployment packaging scripts`
- [x] `node --check agent_platform/static/app.js`
- [x] `git diff --check`
- [x] `node .ai-team/check.mjs --base origin/main`
- [x] 真实 ZipVoice 归档过滤：359 个运行文件、0 个 WAV、0 个 `test_wavs` 目录；decoder SHA256 匹配
- [x] 变更文件私有路径、密钥及二进制状态扫描

## Handoff note

- From: `Codex`
- To: `spacemeowfish/reviewer`
- Summary: 一键准备脚本、同事测试说明和安全解压防护已完成本地验证。下一位审查并合并 PR；另一台电脑的真实下载、模型推理、麦克风和合法音色 TTS 仍是后续独立验收，不能由本机 PlanOnly 代替。
