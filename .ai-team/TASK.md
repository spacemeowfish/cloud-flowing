# Current Task

- ID: `PC-INTERNAL-TEST-001`
- Title: `执行云湃 AI 音响第一轮 PC 内部测试`
- Status: `active`
- Owner: `spacemeowfish`
- Next owner: `unassigned`

## Goal

在当前 Windows PC 源码桌面版本上完成第一轮内部测试，覆盖核心文字与语音用户链路，记录可复现缺陷和用户体验问题，并把结果分类为当前阻塞缺陷、普通缺陷、已知限制或内部测试后的暂缓扩展。测试期间优先修复阻塞当前核心流程的问题，不启动安装包、托盘、开机自启、唤醒词、常驻监听、会议录音、流式 TTS 或真实外部连接器开发。

## Acceptance scenarios

- [ ] 总门禁：下面所有内部测试子项均已执行；阻塞缺陷已经修复并回归，或已明确标记为 `blocked`；测试记录已由 Owner 审阅。只有满足该条件时才勾选本项。

### 内部测试子项

- [x] 给定当前 checkout，当在 Python 3.12 上运行全量自动化测试时，收集到的 394 项测试全部通过。
- [x] 给定当前源码，当运行 Python 编译、浏览器 JavaScript 语法和 Git 空白检查时，所有命令退出码为 0。
- [ ] 启动 `desktop` 后，总览、健康接口、设置页、接口测试中心和任务历史可以正常访问，页面无明显报错或阻塞性布局问题。
- [ ] 在 Mock 模式下，知识、文件、提醒、待办、日程、文本处理和会议纪要的代表性流程符合 `docs/操作台使用手册.md`，R2/R3 操作在执行前停留于确认状态。
- [ ] 切换至 PC 默认模型 `qwen2.5:3b` 后，通用问答和至少一个工具调用成功；设置保存触发受控重启，失败时能够恢复原配置。
- [ ] 真实用户完成按键说话，检查 Faster-Whisper 转写后手动提交一个代表性 Agent 请求；原始 PCM 不落盘，转写不会自动提交。
- [ ] 对已完成任务选择一个 ZipVoice 音色，完成生成、播放、停止和重新生成；记录首播等待、音质、发音和失败情况。
- [ ] Windows 测试通知的正文得到目视确认；授权文件打开后，默认应用窗口得到目视确认，并区分“系统接受请求”和“用户看见窗口”。
- [ ] 发现的问题全部记录复现步骤、预期、实际、环境、严重性和证据路径；修复任何缺陷时，代码、回归测试和本文件在同一 PR 中更新。
- [ ] 第一轮测试结束后，安装包、托盘、开机自启、唤醒词、常驻监听、会议录音、流式 TTS 和真实外部连接器仍作为暂缓扩展，除非 Owner 新建独立任务正式改变优先级。

## Invariants

- 本任务不得宣称 RK3588、NPU、ARM64 音频、实体扬声器、远场麦克风、功耗、温控或长稳已经验收。
- Mock 只证明平台行为，真实 Ollama 只证明该 PC 上指定模型的行为，PC 音频只证明本次 Windows 音频链路。
- 内部测试发现的阻塞缺陷优先于暂缓扩展；不得在缺陷尚未分类时扩大产品范围。
- 不提交 `.env`、凭据、模型权重、私人参考音频、原始麦克风录音、生成数据库或未经审查的私人会话记录。
- 只有实际执行并留有证据的测试才能勾选；历史报告可以作为基线，但不能代替本轮人工测试。

## Decisions

- 当前交付形态是 Windows 源码桌面版本；安装包不属于第一轮内部测试前置条件。
- PC 默认模型为 `qwen2.5:3b`；`qwen3:1.7b` 和 `lfm2.5-thinking:1.2b` 只在需要对比或复现既有问题时测试。
- ZipVoice 保持输出适配器，Faster-Whisper 保持用户检查后的按键说话输入；二者不改变八工具意图空间。
- 每个缺陷单独建立可复现记录；同一时刻只指定一个代码写入者。若缺陷范围较大，先把本任务切换为对应修复任务或新建后续任务。
- RK3588 工作将在独立任务中按 `deployment/rk3588/acceptance-checklist.md` 执行，不混入本次 PC 内部测试。

## Completed

- 当前分支 `codex/desktop-v003` 与 `origin/main` 同在 `1cab0b7`；2026-08-13 检查时工作树无改动。
- 2026-08-13 执行 `py -3.12 -m pytest -q -p no:cacheprovider`，收集到的 394 项测试全部通过。
- 2026-08-13 执行 `py -3.12 -m compileall -q agent_platform evaluation deployment`、`node --check agent_platform/static/app.js` 和 `git diff --check`，退出码均为 0。
- 仓库已有 Windows 桌面、浏览器、配置、ASR、ZipVoice、三个模型的自动化/脚本验证报告，可作为本轮内部测试基线。

## Pending

- 安装并合入 VibeCollab 协作文件，完成 `repo-task-sync` 基线检查。
- 按 `docs/操作台使用手册.md` 执行第一轮 PC 内部测试，并填写 `docs/testing/PC-INTERNAL-TEST-001.md`。
- 对内部测试发现的问题进行分类；阻塞问题进入当前修复链，普通问题进入后续任务。
- 测试结束后更新 `Completed`、`Pending`、验收总门禁、验证总门禁和准确的 `Next step`。

## Next step

启动 `.\.venv\Scripts\python.exe -m agent_platform.cli desktop`，从健康检查与设置页开始执行 `docs/testing/PC-INTERNAL-TEST-001.md`，并把每个发现按模板记录。不要在测试开始前开发暂缓扩展。

## Verification

- [ ] 总门禁：下面所有本轮必需验证都已通过，或者失败已形成带复现证据的缺陷记录；只有满足该条件时才勾选本项。

### 验证明细

- [x] `py -3.12 -m pytest --collect-only -q -p no:cacheprovider` -> 2026-08-13 收集 394 项测试。
- [x] `py -3.12 -m pytest -q -p no:cacheprovider` -> 2026-08-13 退出码 0。
- [x] `py -3.12 -m compileall -q agent_platform evaluation deployment` -> 2026-08-13 退出码 0。
- [x] `node --check agent_platform/static/app.js` -> 2026-08-13 退出码 0。
- [x] `git diff --check` -> 2026-08-13 退出码 0。
- [x] GitHub Actions YAML 解析 -> 2026-08-13 退出码 0。
- [x] `node .ai-team/check.mjs --base origin/main` -> 2026-08-13 任务有效，Functional 0/1，私有 Session disabled。
- [ ] `docs/testing/PC-INTERNAL-TEST-001.md` -> 本轮人工测试记录尚未完成。

## Handoff note

- From: `unassigned`
- To: `unassigned`
- Summary: 尚未发生交接。下一位写入者只能从 `Next step` 继续，并必须保持自动化、人工 PC 测试与 RK3588 证据边界。
