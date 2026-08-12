# Current Task

- ID: `PC-OFFLINE-BUNDLE-001`
- Title: `交付 Windows x64 完整离线内部测试包`
- Status: `active`
- Owner: `spacemeowfish`
- Next owner: `unassigned`

## Goal

把已经完成的云湃 Windows PC 源码能力和经许可核验的本地模型依赖制作成同事可解压即用的离线内部测试包。包内提供固定运行时、相对路径配置、启动、停止、自检、模型切换和真实冒烟脚本；模型二进制、参考音频和构建产物始终留在 Git 历史之外。

本任务交付便携 ZIP，不开发 Windows 安装器、托盘、开机自启、唤醒词、常驻监听、会议录音、流式 TTS 或真实外部连接器。第一轮人工 PC 内测任务 `PC-INTERNAL-TEST-001` 仍未完成，不因本任务自动关闭。

## Acceptance scenarios

- [ ] 总门禁：所有必需资产通过来源和再分发审查；完整 ZIP 在无项目环境依赖的隔离目录通过真实安装冒烟；代码、说明、TASK 和证据已进入同一 PR。
- [ ] Windows x64 包包含当前应用源码、便携 Python 运行时、固定版本运行依赖、启动、停止、自检和模型切换脚本。
- [ ] 包内实际引用 Qwen2.5-3B-Instruct Q4_K_M 和 LFM2.5-1.2B-Instruct Q4_K_M，并使用固定版本 llama.cpp CPU 服务串行加载。
- [ ] 包内包含 Faster-Whisper small、ZipVoice 模型和 vocoder；四个音色仅在来源及再分发权明确时随包分发，否则提供受校验的导入步骤并将完整交付标记为 blocked。
- [ ] 模板配置不含密钥、本机用户名或绝对路径；首次启动自动生成只引用包内相对位置的本地配置。
- [ ] 中文 `INSTALL.md` 覆盖系统要求、解压、自检、启动、访问、模型切换、麦克风、四音色、核心测试、停止、重装、日志和常见故障。
- [ ] 生成 `SHA256SUMS`、文件清单、总大小和资产许可证清单；普通 Git 历史不包含模型、音频、运行时、`.env`、数据库、日志或 ZIP。
- [ ] 在隔离目录验证自检、服务和 `/health`；Qwen 与 LFM 各完成真实模型请求，Agent 不以 Mock 冒充成功；Faster-Whisper 完成真实推理；ZipVoice 四音色各生成有效 WAV。
- [ ] 仅当许可和 GitHub 单资产限制允许时上传 Release 资产；否则保留本地 dist 并明确记录阻塞原因和可执行替代步骤。

## Invariants

- PC 离线包证据不得提升为 RK3588、NPU、实体音响、远场麦克风、功耗、温控或长稳验收。
- 模型只负责模型协议内工作；Schema、授权、确认、幂等、审计和结果校验仍由确定性 Agent 代码负责。
- 包内服务默认只监听 `127.0.0.1`，不得开放到局域网或公网。
- 模型权重、运行时二进制、参考音频、生成音频、私有路径和秘密不得进入 Git。
- 未证明允许再分发的资产不得进入公开 Release；用户提供但权属未证实的音频也必须显式标注。
- 构建和测试只写独立 worktree 与独立 dist；共享 checkout 中现有 `.reasonix/`、`dist/`、`models/` 和 `reasonix.toml` 不得修改。
- 只有实际执行并留有证据的测试才能勾选；Mock、直接模型请求、Agent 请求、ASR 和 TTS 结果必须分别标注。

## Decisions

- 离线运行时采用便携 Python 3.12、Windows x64 CPU 版 llama.cpp 和包内已安装依赖；同事无需预装 Python、Ollama 或编译器。
- 两个 GGUF 串行加载，通过脚本切换；默认模型为 Qwen2.5，避免同时占用内存。
- 分发形态为便携 ZIP，不是 MSI/EXE 安装器；重装方式为保留或备份 `data` 后重新解压。
- 工作分支暂以 `1053a53` 为父。PR #1 已合并为 `cf0f0c35`，Git HTTPS 临时不可用；已由 GitHub API确认 merge tree 等同 `1053a53` 项目树。传输恢复后必须在提交 PR 前 rebase 到 `origin/main`。
- GitHub Release 是条件交付：任何许可证不明或单资产超过平台限制时，不上传不合规资产。

## Completed

- 2026-08-13 已从 `1053a53` 读取并遵循 `AGENTS.md`、`.ai-team/PROJECT.md`、`.ai-team/TASK.md` 和 `.ai-team/SKILL.md`。
- GitHub API确认 PR #1 已合并到 `main`，merge commit 为 `cf0f0c35c9cf0ce98ec58b2382e11ffb03816d3c`，两项 Actions 均成功。
- 已在 `D:\\my new work\\cloud-flowing-pc-offline` 创建独立 worktree 和 `codex/pc-offline-test-bundle` 分支；共享 checkout 未被修改。
- 已确认两份 GGUF、Faster-Whisper small、ZipVoice 模型、vocoder 和候选四音色资产在本机存在；许可和精确来源仍在核验。

## Pending

- 完成所有模型、运行时和参考音频的官方来源、版本、许可证与再分发结论。
- 实现可复现构建、相对配置、启动、停止、自检、切换和真实冒烟脚本。
- 构建完整包并在隔离目录运行全部真实验收。
- 生成清单、哈希、中文说明、实测报告和 Release 结论。
- 网络恢复后 rebase 到 `origin/main`，执行全量回归及 VibeCollab 检查，提交并创建 PR。

## Next step

完成资产来源与许可表，同时固定便携 Python 和 llama.cpp 运行时版本；许可明确后再把对应二进制复制进独立 dist。

## Verification

- [ ] 总门禁：下列命令及真实隔离冒烟全部通过，或失败已形成明确阻塞记录。
- [ ] `python -m pytest -q -p no:cacheprovider`
- [ ] `python -m compileall -q agent_platform evaluation deployment packaging`
- [ ] `node --check agent_platform/static/app.js`
- [ ] `git diff --check`
- [ ] `node .ai-team/check.mjs --base origin/main`
- [ ] 构建产物隐私、路径、密钥和 Git 大文件扫描
- [ ] 隔离目录 `self-check.ps1`
- [ ] Qwen、LFM、Agent、Faster-Whisper 和 ZipVoice 四音色真实冒烟
- [ ] ZIP 解压后 SHA256 与文件清单复核

## Handoff note

- From: `spacemeowfish`
- To: `unassigned`
- Summary: 当前为单写入者实施阶段。下一位只能从 `Next step` 继续，并必须保留许可阻塞、Git/模型分离和 PC/RK3588 证据边界。
