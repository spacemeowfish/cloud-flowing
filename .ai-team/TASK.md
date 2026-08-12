# Current Task

- ID: `PC-OFFLINE-BUNDLE-001`
- Title: `交付 Windows x64 完整离线内部测试包`
- Status: `blocked`
- Owner: `spacemeowfish`
- Next owner: `legal/project owner`

## Goal

把已经完成的云湃 Windows PC 源码能力和经许可核验的本地模型依赖制作成同事可解压即用的离线内部测试包。包内提供固定运行时、相对路径配置、启动、停止、自检、模型切换和真实冒烟脚本；模型二进制、参考音频和构建产物始终留在 Git 历史之外。

本任务交付便携 ZIP，不开发 Windows 安装器、托盘、开机自启、唤醒词、常驻监听、会议录音、流式 TTS 或真实外部连接器。第一轮人工 PC 内测任务 `PC-INTERNAL-TEST-001` 仍未完成，不因本任务自动关闭。

## Acceptance scenarios

- [ ] 总门禁：所有必需资产通过来源和再分发审查；完整 ZIP 在无项目环境依赖的隔离目录通过真实安装冒烟；代码、说明、TASK 和证据已进入同一 PR。技术冒烟已通过，但资产再分发审查未通过，故总门禁保持未完成。
- [x] Windows x64 本机验证包包含当前应用源码、便携 Python 运行时、固定版本运行依赖、启动、停止、自检和模型切换脚本。
- [x] 本机验证包实际引用 Qwen2.5-3B-Instruct Q4_K_M 和 LFM2.5-1.2B-Instruct Q4_K_M，并使用固定版本 llama.cpp CPU 服务串行加载。
- [ ] 同事分发包包含 Faster-Whisper small、ZipVoice 模型和 vocoder，并合法提供四个音色。Faster-Whisper 可再分发；ZipVoice、vocoder 和四个参考 WAV 的再分发权尚未闭环。
- [x] 模板配置不含密钥、本机用户名或绝对路径；首次启动使用包内相对位置。
- [x] 中文 `INSTALL.md` 覆盖系统要求、解压、自检、启动、访问、模型切换、麦克风、四音色、核心测试、停止、重装、日志和常见故障。
- [x] 本机构建生成 `SHA256SUMS`、文件清单、总大小和资产许可证清单；普通 Git 历史不包含模型、音频、运行时、`.env`、数据库、日志或 ZIP。
- [x] 从最终源码提交构建，并在全新独立安装目录完成真实运行验证：Self-Check 22 项通过、0 项失败、1 项预期的不可分发警告；Qwen 与 LFM 各 4/4；Faster-Whisper 3/3；ZipVoice 6/6；停止后相关监听端口为 0。
- [ ] GitHub Release 资产上传。因许可证和参考音频授权阻塞，本机验证包不得分享，也不得上传 Release。

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
- 工作分支已正式 rebase 到 PR #1 的远程 merge commit `cf0f0c35c9cf0ce98ec58b2382e11ffb03816d3c`；当前首个实现提交为 `daab8a4`，不再采用临时父提交方案。
- 完整本机构建只能标记为 `NON_DISTRIBUTABLE_LOCAL_VALIDATION`。它仅用于当前所有者本机验证，不得发送给同事或上传 GitHub Release。
- GitHub Release 是条件交付：任何许可证不明或单资产超过平台限制时，不上传不合规资产。
- GitHub 当前要求每个 Release 资产小于 2 GiB；本机验证 ZIP 为 `3,636,131,116` bytes，因此即使未来许可闭环，也必须分卷或改用其他受控分发渠道，不能原样上传为单个资产。

## Completed

- 2026-08-13 已读取并遵循 `AGENTS.md`、`.ai-team/PROJECT.md`、`.ai-team/TASK.md` 和 `.ai-team/SKILL.md`。
- PR #1 已合并到 `main`，merge commit 为 `cf0f0c35c9cf0ce98ec58b2382e11ffb03816d3c`；工作分支已正式 rebase 到该基线。
- 已在独立 worktree 和独立 dist 中实施；共享 checkout 未被修改。
- 已实现便携运行时、相对配置、启动、停止、自检、模型切换、资产导入和真实冒烟脚本。
- 已完成资产来源、版本、SHA256 和许可证审查，并将阻塞项写入包状态与发布报告。
- 已从源码提交 `a08a51a17a6015daa6812d172b0ef6ea4ab9d52b` 构建完整本机验证目录：`4,699` 个文件、`3,851,008,890` bytes；初始负载清单为 `4,696` 个文件、`3,849,540,929` bytes。依赖位于较短的 `runtime/packages`，最长相对路径为 108 字符，运行后未生成 `.pyc`。该目录不具备再分发资格。
- 已在全新独立安装目录完成最终源码构建的真实验收：Self-Check `22 pass / 0 fail / 1 expected warning`；Qwen `4/4`；LFM `4/4`；ASR `3/3`；TTS `6/6`；停止后 `8000/8080` 监听端口均为 `0`。
- 已生成 Zip64 本机验证归档 `cloud-flowing-windows-x64-offline-local-validation.zip`，大小 `3,636,131,116` bytes，SHA256 `d72d50291efacc1ffb86709de7367e06bce10ab9d160cc8aa372e05da6f8b92e`；ZIP 完整性检查 `4,699` 个条目、0 个损坏项。
- 已将归档解压到另一个全新深路径目录复核：包内 `SHA256SUMS` 共 `4,694` 条、0 错误，自检仍为 `22 pass / 0 fail / 1 expected warning`，最长完整路径 235 字符。

## Pending

- 取得 Qwen 商业内部测试/再分发授权，或把 Qwen 改为使用方自行导入且不得随包传播。
- 由公司确认 LFM Open License 1.0 的年收入低于 USD 10M 条件是否满足，并留存书面依据。
- 补齐 ZipVoice 所含 eSpeak 组件的固定版本、COPYING 和对应源代码义务，并处理 Emilia 数据来源限制。
- 取得 exact vocoder ONNX 导出的许可依据；取得四个参考 WAV 的录音、音色身份和再分发授权，或换成明确授权资产。
- 当前本机验证归档不得交给同事；许可闭环后必须重新以 `distributable` 模式构建、重新生成清单和哈希并再次验收。
- 全量回归与 VibeCollab 检查已通过；提交任务记录与脱敏验证摘要并创建 PR。受限二进制、音频、运行日志和本地归档不得进入 Git。

## Next step

法务或项目负责人先对五项许可阻塞给出书面结论。工程侧可并行完成代码回归、PR 和本机归档校验，但在授权闭环前不得把完整包发给同事或上传 GitHub Release。

## Verification

- [ ] 总门禁：技术验证已通过，但再分发许可阻塞尚未解除。
- [x] `python -m pytest -q -p no:cacheprovider`：401 项通过；离线构建/冒烟专项 22 项通过
- [x] `python -m compileall -q agent_platform evaluation deployment packaging`
- [x] `node --check agent_platform/static/app.js`
- [x] `git diff --check`
- [x] `node .ai-team/check.mjs --base origin/main`
- [x] 构建产物隐私、路径、密钥和 Git 大文件扫描
- [x] 最终独立安装目录 `Self-Check.ps1`：22 项通过、0 项失败、1 项预期不可分发警告
- [x] Qwen 模型/Agent 冒烟：4/4
- [x] LFM 模型/Agent 冒烟：4/4
- [x] Faster-Whisper 真实推理：3/3
- [x] ZipVoice 四音色真实生成及音频校验：6/6
- [x] 停止服务后相关监听端口：0
- [x] 最终 ZIP 完整性及解压后 `SHA256SUMS` 复核：4,699 个 ZIP 条目无损坏，4,694 条内容哈希 0 错误，自检 22/22

## Handoff note

- From: `spacemeowfish`
- To: `legal/project owner`
- Summary: Windows 本机完整链路已真实跑通，但产物是不可分发的本机验证包。下一位应先闭环 Qwen、LFM、ZipVoice、exact vocoder ONNX 和四个参考 WAV 的许可条件；不得把本机成功描述为同事交付完成、公开 Release 完成或 RK3588 验收完成。
