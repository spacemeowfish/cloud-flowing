# Project Context

本文件记录所有开发者和 AI 共享的长期稳定事实。当前任务进度写入 `.ai-team/TASK.md`；历史实施细节保留在 `docs/tasks/`、`docs/releases/`、ADR、代码、测试和 Git 历史中。

## Goal

交付云湃 AI 音响的 PC 完备基线：在 Windows PC 上完成并验证当前约定范围内所有不依赖 RK3588 板卡或实体音响硬件的产品能力，同时为后续上板验收保留稳定契约、部署准备和可追溯证据。

“PC 完备”指下面当前 PC 范围内的每一项都已经实现并验证。尚未开始内部测试的扩展能力作为“当前阶段暂缓项”单独记录，不计入本次里程碑完成门禁；它们也不因此成为永久非目标。PC 完备不代表 RK3588、NPU、温控、远场音频或实体设备已经验收通过。

## Scope

### PC 产品基线范围

- 通过 Windows 桌面监督进程、浏览器操作台、FastAPI API、SSE 任务事件、健康接口和 Swagger 文档运行本地优先 Agent。
- 支持当前八类能力：通用问答、知识查询、授权文件查找与打开确认、提醒管理、待办管理、日程管理、文本处理、从授权文本生成会议纪要。
- 使用 Mock 验证确定性平台行为，使用 Ollama 本地模型验证真实模型行为。PC 默认模型为 `qwen2.5:3b`；`qwen3:1.7b` 和 `lfm2.5-thinking:1.2b` 作为对比模型，并保留各自真实限制。
- 支持 Windows 按键说话和 Faster-Whisper 本地转写；文本回填输入框，由用户检查后再提交任务。
- 支持 ZipVoice 作为已完成任务的语音输出适配器，包括多参考音色、WAV 生成、播放、停止和重新生成。
- 支持本地设置、受控重启与失败回滚、知识索引重建、Windows 通知、授权目录管理、文件打开确认、审计和本地持久化。
- 完成 PC 侧 RKLLM 与 llama.cpp 准备：冻结 HTTP 契约、Adapter、Mock 服务、部署脚本、校准与构建元数据模板、ARM64 镜像构建准备、健康检查和真机验收说明。
- 维护自动化测试、固定评测集、真实模型报告、PC 音频报告、发布记录、ADR 和可复现命令。
- 浏览器界面分为免登录普通任务页和密码解锁的开发者控制台；本版本只提供 `user/developer` 两种界面模式，不建设完整多用户认证系统。
- 默认仅监听回环地址；受信任开发网络上的板端预览可显式监听非回环地址，但必须同时配置仓库外的开发者密码。

### 必须由目标硬件验证的范围

- 在真实执行前，不得宣称 RKLLM Runtime、`.rkllm` 模型、RKNPU/NPU、ARM64 依赖或板端服务已经可用。
- 不得用 PC 证据宣称板端 TTFT、tokens/s、峰值内存、OOM、温度、降频、功耗、并发、100 次稳定性、8 小时长稳、systemd 恢复或异常断电恢复已经通过。
- 不得用 Windows 测试宣称实体扬声器、麦克风阵列、声卡、远场识别、声学回声消除、唤醒词或板端完整语音闭环已经验收。

### 当前阶段暂缓项

- Windows 安装包、托盘程序和开机自启动。
- 唤醒词、Vosk 常驻监听、会议录音转写和流式 TTS。
- 真实天气、票务、日历、消息发送或其他生产级外部连接器。
- 将模型权重、私人参考音频、API 凭据或用户数据打入仓库或默认分发包。
- 把 API 暴露到公网，或把开发板局域网预览能力宣称为生产级网络安全方案。

前五类扩展能力等待当前版本内部测试后再决定优先级；测试期间发现的阻塞缺陷优先于这些扩展项。如果要启动其中一项，先创建新的 `TASK.md`，写清目标、验收和非目标，再开始编码。模型权重、秘密与未经认证的网络暴露继续属于安全边界，不因后续规划而自动进入范围。

## Architecture

- `agent_platform/api/` 负责 FastAPI 边界、任务接口、SSE、管理设置、语音接口、会话隔离和依赖容器。
- 普通浏览器会话和开发者会话均由服务端生成的 HttpOnly Cookie 标识；调用者提供的角色或会话请求头不是授权事实。
- 开发者密码来自仓库外环境变量，登录令牌仅保存在服务端内存中；服务重启会使开发者登录失效。
- `agent_platform/core/` 负责任务生命周期、确定性路由、参数归一化、Schema 校验、策略、数据分级、确认、审计、取消、幂等、离线行为以及模型与工具编排。
- `agent_platform/tools/` 负责业务行为和本地数据变更。模型可以解释请求，但不得绕过工具契约、权限、确认或结果校验。
- `agent_platform/adapters/` 负责模型、平台、连接器、通知和 ZipVoice 集成；`ModelGateway` 向 Core 提供稳定的模型边界。
- 意图理解采用分阶段路由：确定性规则处理已知高置信表达，其余请求由当前模型完成意图与参数抽取，最后仍由确定性代码校验和执行。
- 语音输入是可选的 PC 本地适配器：麦克风 PCM 仅保存在有上限的内存中，Faster-Whisper 完成转写，页面要求用户检查后再提交。
- ZipVoice 是 `SpeechSynthesizer` 输出适配器，不是第九个 Agent 工具。它只消费已完成任务的用户可见文本，不读取隐藏提示或模型思考过程。
- SQLite 和授权本地目录保存任务、提醒、待办、日程、知识、审计和生成产物；所有访问继续受会话和策略约束。
- `evaluation/`、`tests/`、`docs/tasks/`、`docs/releases/` 和 `docs/adr/` 保存可执行检查与长期证据；`deployment/rk3588/` 保存上板准备和独立真机验收合同。

## Domain Terms

- **PC 完备（PC-complete）**：当前约定的非硬件范围全部在 Windows PC 基线上实现并验收。
- **平台验证**：使用 Mock 验证状态、策略、工具、API 和失败路径；不代表真实模型质量。
- **真实模型验证**：用确定的本地模型和固定输入观察 Agent 业务输出；不代表 RK3588 结果。
- **PC 语音验证**：在 Windows 上观察麦克风、ASR 或 ZipVoice 行为；不代表实体 AI 音响验收。
- **上板就绪（Board-ready）**：PC 侧契约、脚本、清单和说明已经准备；不代表板卡通过。
- **真机验收（Board-accepted）**：在明确的 RK3588 硬件和冻结的软件/模型栈上按验收表生成了证据。

## Invariants

- PC、Mock、真实模型和 RK3588 证据必须分别标注，任何低层级证据都不得提升为更高层级的验收结论。
- 默认 PC 模型是 `qwen2.5:3b`，除非当前任务正式修改该决策。对比模型的已知质量失败必须保留，不能通过放松安全门禁把它伪装成通过。
- 模型负责意图识别、参数抽取、澄清、工具选择和短文本生成。确定性代码负责 Schema、授权、数据分级、确认、执行、幂等、取消、审计和结果校验。
- D3 数据不得进入模型、日志、离线队列或云端；D2 默认不得云回退。取消、Schema 错误和不可重试故障不得触发云回退。
- 文件访问只能发生在授权根目录内；多候选必须明确选择，破坏性或高风险操作必须经过 R2/R3 确认。
- 设置 API 不得返回 API 密钥或其他秘密；模型权重和私人参考音频必须保留在仓库外，通过本地配置引用。
- 未登录用户只能访问自己的普通任务能力；管理设置、完整能力信息、任务审计、日志和 API 文档必须要求有效开发者会话。
- 非回环监听地址必须同时配置开发者密码；该门禁只支持受信任开发网络预览，不替代 HTTPS、反向代理或生产认证。
- 原始麦克风 PCM 不落盘，并在完成、取消、超时或失败后释放；转写结果不得自动提交任务。
- TTS 故障不得阻止文本 Agent 启动；TTS 只能读取完成任务的可见文本，音频读取必须再次校验会话权限。
- Git 提交、代码、测试、当前报告和当前用户请求的优先级高于 AI 自述与 Session 历史。
- 只有全部验收项和验证项都有真实证据时，任务才能标记为 `done`。

## Authoritative Evidence

- 当前 Windows PC 基线：`docs/releases/2026-08-12-windows-desktop-trial.md`。
- 当前操作与人工验收流程：`docs/操作台使用手册.md`。
- 模型与平台契约：`docs/contracts/model-adapters.md` 和 `docs/adr/`。
- PC 机器可读报告：`evaluation/reports/2026-08-12-*.json`。
- RK3588 验收边界：`deployment/rk3588/acceptance-checklist.md`。
- 当前测试数量必须通过 `.\.venv\Scripts\python.exe -m pytest --collect-only -q` 读取，不把旧测试数字当作永久事实。

## Commands

- 创建本地环境：`py -3.12 -m venv .venv`。
- 安装 PC 开发及语音依赖：`.\.venv\Scripts\python.exe -m pip install -e ".[dev,tts,voice]"`。
- 启动 Windows 桌面监督模式：`.\.venv\Scripts\python.exe -m agent_platform.cli desktop`。
- 运行全量自动化测试：`.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider`。
- 执行 Python 与前端语法检查：`.\.venv\Scripts\python.exe -m compileall -q agent_platform evaluation deployment` 和 `node --check agent_platform/static/app.js`。
- 运行 Mock 评测：`.\.venv\Scripts\python.exe -m agent_platform.cli evaluate --mode mock --detailed --cases evaluation/test_cases --expected-total 60`。
- 运行真实 Ollama 评测前，必须记录 Provider、模型名、模型 digest、数据集版本和独立报告路径。
- 安装 VibeCollab 后运行仓库同步检查：`node .ai-team/check.mjs --base origin/main`。
