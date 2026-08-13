# Agent Platform MVP

本项目实现 `开发内容/prompts` 中 F1-F8、T1-T5、I1-I3 定义的本地优先后端：统一任务状态、模型网关、工具执行、权限与数据分级、端云路由、离线队列、连接器、审计、八个工具、FastAPI/SSE 和自动化评测。当前还包含 llama.cpp ARM64 CPU PoC 与 RKLLM 上板前的协议、Adapter、模拟服务和部署准备物。

## 团队开发入口

本仓库使用 VibeCollab 管理跨开发者和 AI 工具的共享上下文。开始开发前先阅读 `AGENTS.md`、`.ai-team/PROJECT.md`、`.ai-team/TASK.md` 和 `.ai-team/SKILL.md`；代码与任务进度必须放在同一个分支和 Pull Request 中。提交前执行：

```powershell
node .ai-team/check.mjs --base origin/main
```

当前活动任务是第一轮 PC 内部测试，测试记录位于 [`docs/testing/PC-INTERNAL-TEST-001.md`](docs/testing/PC-INTERNAL-TEST-001.md)。安装包、托盘、开机自启、唤醒词、常驻监听、会议录音、流式 TTS 和真实外部连接器暂不进入本轮内测。

同事从 Fork 准备 Windows PC 环境、下载 Qwen/LFM/Faster-Whisper/ZipVoice、执行完整测试并提交 PR 的流程见 [`docs/testing/COLLEAGUE-PC-SETUP.md`](docs/testing/COLLEAGUE-PC-SETUP.md)。

## 安装

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
```

Windows 安装会同时安装 `winotify`，用于提醒和日程到期时的系统通知。如果只运行不涉及通知的本地评测，即使该包暂时缺失，程序也会退回控制台输出；推荐仍按上述命令在当前项目目录重新安装，避免调用旧目录中的全局 `agent-platform.exe`。

Linux/ARM64 使用 Python 3.11 或更高版本执行同样的 `pip install -e ".[dev]"`。默认不下载 Embedding 模型、不调用外部 API、不打开桌面文件，只监听 `127.0.0.1`。

需要 ZipVoice TTS 时额外安装可选依赖；模型不会被复制到本项目或 Qwen/LFM 镜像：

```powershell
python -m pip install -e ".[dev,tts]"
```

Windows 桌面试用还需要麦克风和 Faster-Whisper 依赖：

```powershell
python -m pip install -e ".[dev,tts,voice]"
```

Faster-Whisper 和 ZipVoice 模型仍放在仓库外，通过设置页或项目 `.env` 指向实际目录。

## 启动

以下命令均建议在本 checkout 根目录执行。若 PowerShell 已经位于项目根目录，可以跳过
`Set-Location`；否则先切换到实际项目目录。为避免调用其他目录里旧版本的全局命令，使用模块入口最稳妥：

```powershell
Set-Location '<项目目录>'
python -m agent_platform.cli desktop
```

打开 `http://127.0.0.1:8000/` 使用 Web 功能操作台；`http://127.0.0.1:8000/docs` 是 API 文档。操作台的页面、测试流程和风险确认说明见 [`docs/操作台使用手册.md`](docs/操作台使用手册.md)。运行演示和评测：

```powershell
python -m agent_platform.cli demo
python -m agent_platform.cli evaluate --mode mock
pytest
```

`desktop` 是 Windows 本机试用的推荐入口：它会打开操作台，并在设置页保存后优雅重启服务。`serve` 保留为开发模式，保存设置后需要手动重启。外部进程环境变量优先于项目 `.env`，被环境变量锁定的字段会在设置页显示为只读。

设置页可切换 `mock/ollama`、发现本机 Ollama 模型、管理授权目录和知识索引、启停文件打开、配置 ZipVoice 四音色及 Faster-Whisper 麦克风。API 密钥不会在页面返回或被页面覆盖；`.env` 原子更新前保留最近 5 份本地备份，新配置启动失败时自动恢复上一份。

按键说话位于“通用任务”输入框：按住麦克风按钮录音，松开后本地转写；转写文本只回填输入框，不会自动提交。录音最长 30 秒，同一时刻只允许一条录音，PCM 在完成、取消、异常或超时后立即清空。语音输入默认关闭，启用前需在设置页指定外部 Faster-Whisper 模型目录。

## 演示知识库

项目自带 `demo_docs` 中的 7 份合成文档，可直接增量导入：

```powershell
agent-platform import-docs demo_docs
agent-platform import-docs demo_docs --force
```

导入器支持 UTF-8、UTF-8 BOM、GB18030 的 `.txt`/`.md` 和 `.docx`，按文件修改时间跳过未变化内容；失败文件会单独列出，不影响其他文档。可尝试“产品保修期多久”“年假有几天”“出差住宿标准”等查询，无相关依据时固定返回“未找到相关信息”。

## 使用本地模型运行 Agent

不启动大模型时，默认使用 `mock`，适合验证操作台、工具、权限、确认流程和本地数据读写：

```powershell
Set-Location '<项目目录>'
$env:MODEL_PROVIDER = 'mock'
python -m agent_platform.cli serve
```

接入本机 Ollama 前，先确认 Ollama 服务已启动并且模型已经下载：

```powershell
Invoke-RestMethod http://127.0.0.1:11434/api/tags
```

使用 Ollama 运行 Agent 可以直接在 `desktop` 设置页切换，也可用环境变量锁定：

```powershell
Set-Location '<项目目录>'
$env:MODEL_PROVIDER = 'ollama'
$env:MODEL_NAME = 'qwen2.5:3b'
$env:OLLAMA_BASE_URL = 'http://127.0.0.1:11434'
$env:OLLAMA_THINKING_ENABLED = 'false'
python -m agent_platform.cli desktop
```

当前已验证的本机模型标签包括 `qwen2.5:3b`、`qwen3:1.7b` 和 `lfm2.5-thinking:1.2b`。设置页切换模型会自动重启；若使用外部环境变量，则需停止当前服务后修改并重启：

```powershell
Ctrl+C
$env:MODEL_NAME = 'qwen3:1.7b' # 或 lfm2.5-thinking:1.2b
python -m agent_platform.cli desktop
```

也可以把这些变量写入项目根目录的 `.env`，这样每次启动自动读取；不要把 API 密钥等敏感值提交到 Git。`MODEL_PROVIDER` 可选 `mock`、`ollama`、`llamacpp`、`cloud`、`rkllm`；后三者还需要对应的服务地址、认证或板端配置。

`general_chat` 负责数学、常识、闲聊和翻译等不属于业务工具的请求。简单算术由本地确定性解析器直接计算；其他通用问题交给当前模型，不落业务库，也不伪造知识库来源。明确查询本地文档、公司制度或要求来源时，知识库无命中仍返回“未找到相关信息”；只有误分到知识库的普通问题才会受控回退一次到通用问答。

## ZipVoice TTS

ZipVoice 是任务完成后的输出适配器，不属于第九个 Agent 工具，也不改变大模型选择。知识问答、通用问答和文本处理等任务只要产生可见文本，操作台结果区就会显示播放、停止和重新生成按钮。首次点击播放时按需生成 WAV；重新生成会创建新的音频版本。

模型、vocoder 和参考音频存放在项目之外，通过 `.env` 引用：

```dotenv
TTS_PROVIDER=zipvoice
TTS_OUTPUT_DIR=./data/tts
ZIPVOICE_MODEL_DIR=D:/models/sherpa-onnx-zipvoice-distill-int8-zh-en-emilia
ZIPVOICE_VOCODER_PATH=D:/models/vocos_24khz.onnx
ZIPVOICE_REFERENCE_AUDIO_PATH=D:/models/reference.wav
ZIPVOICE_REFERENCE_TEXT=参考音频中实际说出的完整文本
ZIPVOICE_VOICES=[{"id":"news-female1","label":"news-female1","reference_audio_path":"D:/models/news-female.wav","reference_text":"参考音频中实际说出的完整文本"},{"id":"male1","label":"male1","reference_audio_path":"D:/models/male1.wav","reference_text":"参考音频中实际说出的完整文本"},{"id":"female1","label":"female1","reference_audio_path":"D:/models/female1.wav","reference_text":"参考音频中实际说出的完整文本"},{"id":"female2","label":"female2","reference_audio_path":"D:/models/female2.wav","reference_text":"参考音频中实际说出的完整文本"}]
ZIPVOICE_DEFAULT_VOICE_ID=news-female1
ZIPVOICE_NUM_THREADS=4
ZIPVOICE_SPEED=1.0
ZIPVOICE_NUM_STEPS=4
```

`ZIPVOICE_VOICES` 是一行 JSON 音色列表；每项包含稳定 `id`、操作台名称、参考 WAV 和逐字文本。`ZIPVOICE_DEFAULT_VOICE_ID` 决定操作台默认选择。旧的单个 `ZIPVOICE_REFERENCE_*` 配置仍兼容，但只显示“默认音色”。参考 WAV 支持单声道 PCM16 或 PCM24，并将原采样率交给 ZipVoice；参考文本必须与参考音频逐字匹配，否则音色和清晰度会明显下降。修改配置后重启 Agent，然后在 `/health` 中确认 `tts.ready=true`。交换机没有声卡时，仍可由浏览器播放服务返回的 WAV；RK3588 上的速度和内存需另做 ARM64 真机验收。

## RK3588 llama.cpp CPU PoC

两个 ARM64 镜像分别包含 Qwen2.5-3B-Instruct Q4_K_M 或 LFM2.5-1.2B-Instruct Q4_K_M，不同时加载。线程、上下文、输出上限、批大小和并发均由环境变量控制，修改配置不需要重建镜像：

```text
LLAMACPP_THREADS
LLAMACPP_CONTEXT_SIZE
LLAMACPP_MAX_TOKENS
LLAMACPP_BATCH_SIZE
LLAMACPP_PARALLEL
```

模型准备、双镜像构建、真机安装、4/6/8 线程自动对比、8192 压力档和结果文件说明见 [`deployment/rk3588/docker/README.md`](deployment/rk3588/docker/README.md)。2048/256 只是首次启动档；4096 稳定时使用真机自动选出的性能档。没有目标交换机生成的 `benchmark-report.json` 时，不得宣称已通过 RK3588 性能验收。

PC 侧实现范围、本机代理模型结果、已验证项与尚未执行的板端边界见 [`docs/releases/2026-08-08-rk3588-dual-model-cpu-poc.md`](docs/releases/2026-08-08-rk3588-dual-model-cpu-poc.md)。

## 模型评测

本机 Ollama 模型优先使用原生 Provider。它会关闭 thinking、强制 JSON 输出，并自动绕过本机系统代理：

```powershell
$env:MODEL_PROVIDER="ollama"
$env:MODEL_NAME="qwen2.5:3b"
$env:OLLAMA_BASE_URL="http://127.0.0.1:11434"
$env:OLLAMA_THINKING_ENABLED="false"
python -m agent_platform.cli evaluate --mode ollama --detailed --cases evaluation/test_cases --expected-total 60
```

验证其他 Ollama 模型时只需替换 `MODEL_NAME` 后重跑。这里真正决定 Provider 的是 `MODEL_PROVIDER=ollama`；`--mode ollama` 仅用于提示/检查两者是否一致。协议可用不代表 Agent 质量达标，仍需比较固定评测集中的 Schema、意图、参数和端到端指标。三模型专项结果见 [`docs/releases/2026-08-07-three-model-affected-functional-validation.md`](docs/releases/2026-08-07-three-model-affected-functional-validation.md)。

准备好 `.env.deepseek`、`.env.qwen`，并确保 Ollama 已在 `127.0.0.1:11434` 加载 `qwen2.5:3b` 后执行：

```powershell
.\scripts\run_comparison.ps1
```

脚本自动检查 60 条固定用例与 Ollama 模型，依次完成 DeepSeek、Qwen 评测并生成 `evaluation/reports/deepseek.json`、`qwen.json` 和 `comparison.md`。任务被外部终端中断时，可用 `-Resume` 复用结构完整的 60 条报告；无参数执行始终重新跑两轮。无论成功或失败，脚本都会停止自己启动的服务并恢复 `.env.deepseek`。

只针对 Qwen 做提示/路由 A/B 时，使用固定的 v2.3 报告和 raw 快照：

```powershell
.\scripts\run_qwen_ab.ps1
```

脚本会确认当前 60 条用例的 ID 和输入哈希与基线 raw 快照完全一致，从 Ollama `/api/tags` 读取当前 `qwen2.5:3b` digest，并生成带模型摘要、提示版本、数据集摘要、基线文件摘要和逐例调用轨迹的 v3.1 报告。

## RKLLM 上板前开发

启动只监听本机的官方协议模拟服务：

```powershell
python -m agent_platform.devtools.rkllm_mock_server
```

另一个终端使用 RKLLM Provider 跑固定评测：

```powershell
$env:MODEL_PROVIDER="rkllm"
$env:RKLLM_SERVER_URL="http://127.0.0.1:8081/v1"
agent-platform evaluate --mode rkllm --detailed --output evaluation/reports/rkllm-mock.json
```

也可以在模拟服务已启动时运行本机开发服务；该入口会强制 `127.0.0.1`、关闭云回退并使用 `work/rkllm-live` 的隔离数据库：

```powershell
python -m agent_platform.devtools.local_rkllm_agent
```

模拟服务只验证 `/v1/chat/completions` 协议、结构化解析、背压和 Agent 集成，不代表真实 RKLLM 模型或 NPU 性能。W8A8 校准、模型导出、官方 Server 准备、systemd 和真机验收步骤见 [`deployment/rk3588/README.md`](deployment/rk3588/README.md)。

## 确认流程

Web 端会按任务状态实时更新，并在执行前展示对应确认控件：

- “打开项目周报”：从 `demo_files` 的真实候选中选择，不允许模型虚构路径。
- “提醒我明天开会”：补充具体时间后继续创建。
- “删除全部提醒”：提升为 R3，不可撤销，必须明确确认；拒绝会写入审计链。

## API

| 方法 | 路径 | 用途 |
|---|---|---|
| `POST` | `/tasks` | 创建任务并立即返回 `received`，后台继续处理 |
| `GET` | `/tasks` | 查询当前会话的最近任务，支持 `limit` 参数 |
| `GET` | `/tasks/{id}` | 查询持久化状态 |
| `POST` | `/tasks/{id}/confirm` | 补充参数、选择候选或批准 R2/R3 操作 |
| `POST` | `/tasks/{id}/cancel` | 取消任务并传播取消信号 |
| `GET` | `/tasks/{id}/audit` | 获取当前会话的脱敏审计链 |
| `GET` | `/tasks/{id}/events` | 通过 SSE 订阅状态变化 |
| `GET` | `/health` | 服务与连接器健康状态 |
| `GET` | `/meta/capabilities` | 获取工具 Schema、风险/数据等级与非敏感运行配置 |

外部认证代理可注入 `X-Agent-Role` 与 `X-Session-Id`。未提供时分别使用 `user` 和 `default`；API 不自行实现账号认证。

## 模块边界

- F1-F8：`agent_platform/models`、`core`、`adapters` 和 `config`。
- T1-T5：`agent_platform/tools`，分别对应文件、知识库、提醒、短文本和会议纪要。
- I1-I2：`core/agent_core.py` 与 `api`。
- I3：`evaluation/test_cases`、`evaluation/runner.py` 和报告生成器。

知识库默认采用 256 维字符 n-gram 哈希向量，仅用于零下载 MVP 和回归测试。需要更强语义召回时，实现 `Embedder` 接口并替换 `HashingEmbedder`，不需要修改 Agent Core。

## 验证

开发前基线为 230 项自动化测试和 60 条固定中文评测用例；当前实际数量以 `pytest --collect-only -q` 为准。覆盖状态恢复、乐观锁、取消、幂等、数据脱敏、权限矩阵、六类路由、离线 FIFO、八工具、动态确认、完整审计、REST、SSE、本地模型协议与响应式 Web 界面。

## 安全默认值

- `MODEL_PROVIDER=mock`；云端和 RKLLM 适配器使用各自冻结的 OpenAI-compatible 契约。
- RKLLM 默认 `127.0.0.1`、单并发和有界排队；云回退默认关闭，启用后也只允许 D0/D1 的可重试模型错误。
- `AGENT_FILE_OPEN_ENABLED=false`；只索引配置白名单目录。
- API 仅监听本机。暴露到局域网前必须接入外部认证代理。
- D3 数据禁止进入模型、日志、离线队列或云端；D2 默认不上云。
- 任务与审计默认保留 30 天，可通过环境变量调整。

真实 RKLLM Runtime、NPU、温控、性能和长稳仍必须在目标 RK3588 上按验收表验证；PC Mock 结果不得代替真机报告。真实天气/票务服务也不在默认验证范围内。
