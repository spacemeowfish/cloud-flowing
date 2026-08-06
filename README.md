# Agent Platform MVP

本项目实现 `开发内容/prompts` 中 F1-F8、T1-T5、I1-I3 定义的本地优先后端：统一任务状态、模型网关、工具执行、权限与数据分级、端云路由、离线队列、连接器、审计、七个业务工具、FastAPI/SSE 和自动化评测。当前还包含 RKLLM 上板前的协议、Adapter、模拟服务和部署准备物。

## 安装

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
```

Linux/ARM64 使用 Python 3.11 或更高版本执行同样的 `pip install -e ".[dev]"`。默认不下载 Embedding 模型、不调用外部 API、不打开桌面文件，只监听 `127.0.0.1`。

## 启动

```powershell
agent-platform serve
```

打开 `http://127.0.0.1:8000/` 使用 Web 功能操作台；`http://127.0.0.1:8000/docs` 是 API 文档。操作台的页面、测试流程和风险确认说明见 [`docs/操作台使用手册.md`](docs/操作台使用手册.md)。运行演示和评测：

```powershell
agent-platform demo
agent-platform evaluate --mode mock
pytest
```

## 演示知识库

项目自带 `demo_docs` 中的 7 份合成文档，可直接增量导入：

```powershell
agent-platform import-docs demo_docs
agent-platform import-docs demo_docs --force
```

导入器支持 UTF-8、UTF-8 BOM、GB18030 的 `.txt`/`.md` 和 `.docx`，按文件修改时间跳过未变化内容；失败文件会单独列出，不影响其他文档。可尝试“产品保修期多久”“年假有几天”“出差住宿标准”等查询，无相关依据时固定返回“未找到相关信息”。

## 模型对比评测

本机 Ollama 模型优先使用原生 Provider。它会关闭 thinking、强制 JSON 输出，并自动绕过本机系统代理：

```powershell
$env:MODEL_PROVIDER="ollama"
$env:MODEL_NAME="qwen2.5:3b"
$env:OLLAMA_BASE_URL="http://127.0.0.1:11434"
$env:OLLAMA_THINKING_ENABLED="false"
agent-platform evaluate --mode ollama --detailed --expected-total 60
```

验证其他 Ollama 模型时只需替换 `MODEL_NAME`。协议可用不代表 Agent 质量达标，仍需比较固定评测集中的 Schema、意图、参数和端到端指标。

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

开发前基线为 230 项自动化测试和 60 条固定中文评测用例；当前实际数量以 `pytest --collect-only -q` 为准。覆盖状态恢复、乐观锁、取消、幂等、数据脱敏、权限矩阵、六类路由、离线 FIFO、七工具、动态确认、完整审计、REST、SSE、RKLLM 线协议与响应式 Web 界面。

## 安全默认值

- `MODEL_PROVIDER=mock`；云端和 RKLLM 适配器使用各自冻结的 OpenAI-compatible 契约。
- RKLLM 默认 `127.0.0.1`、单并发和有界排队；云回退默认关闭，启用后也只允许 D0/D1 的可重试模型错误。
- `AGENT_FILE_OPEN_ENABLED=false`；只索引配置白名单目录。
- API 仅监听本机。暴露到局域网前必须接入外部认证代理。
- D3 数据禁止进入模型、日志、离线队列或云端；D2 默认不上云。
- 任务与审计默认保留 30 天，可通过环境变量调整。

真实 RKLLM Runtime、NPU、温控、性能和长稳仍必须在目标 RK3588 上按验收表验证；PC Mock 结果不得代替真机报告。真实天气/票务服务也不在默认验证范围内。
