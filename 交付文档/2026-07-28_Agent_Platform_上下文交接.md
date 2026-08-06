# Agent Platform 上下文交接文档

交接日期：2026-07-28  
工作目录：`D:\my new work\cloud flowing`  
当前阶段：PC 无硬件 MVP 已完成；模型对比完成；下一步是参数契约优化

## 1. 项目目标

构建面向 RK3588 终端的本地优先 Agent 平台。Qwen2.5-3B-Instruct 负责受约束的意图识别、参数提取、工具选择、澄清和短文本处理；确定性本地模块负责权限、Schema、执行、幂等、审计和风险确认；复杂推理、长上下文和实时外部数据通过 DeepSeek 或其他云服务回退。

当前实现是 Windows PC 验证版本，不是 RK3588 交付版本。

## 2. 当前状态快照

- Python 虚拟环境：`.venv`，Python 3.12。
- 当前 `.env` 已恢复为 DeepSeek：`MODEL_PROVIDER=cloud`、`MODEL_NAME=deepseek-v4-flash`。
- `.env.deepseek` 包含云模型配置；不得在日志、文档或提交中输出 `MODEL_API_KEY`。
- `.env.qwen` 使用 `http://127.0.0.1:11434/v1` 和 `qwen2.5:3b`。
- 当前没有 `agent-platform serve` 或 `agent-platform evaluate` 残留进程。
- Ollama 服务可访问，但模型可能按空闲策略卸载；脚本会在评测前预热。
- 50 条 DeepSeek 和 Qwen 报告均已完成，`comparison.md` 已生成。
- 自动化测试共 184 项，最后一次全量运行全部通过。
- 当前目录不是 Git 仓库，不能依赖 `git status/diff/log` 获取改动历史。

## 3. 主要目录与职责

| 路径 | 职责 |
|---|---|
| `agent_platform/models` | 任务、模型、策略、工具、审计和评测数据协议 |
| `agent_platform/adapters` | Mock、DeepSeek/Ollama OpenAI-compatible、RKLLM 接口和平台适配 |
| `agent_platform/core` | Agent Core、状态机、策略、路由、执行、审计、会话和评测 |
| `agent_platform/tools` | 文件、知识库、提醒、短文本、会议纪要工具 |
| `agent_platform/api` | FastAPI、REST、SSE、中间件和应用容器 |
| `static/index.html` | 零依赖单页 Web 任务中心 |
| `demo_docs` | 7 份虚构知识库演示文档 |
| `demo_files` | 3 份文件候选演示数据 |
| `evaluation/test_cases` | 5 类意图、共 50 条固定中文评测用例 |
| `evaluation/reports` | DeepSeek、Qwen 和对比报告 |
| `evaluation/compare_reports.py` | 同构校验、失败用例关联和 Markdown 对比生成 |
| `scripts/run_comparison.ps1` | 两轮模型评测的一键自动化脚本 |
| `tests` | 184 项自动化测试 |
| `开发内容` | 原始架构、模块提示词和阶段需求 |
| `交付文档` | 管理报告和本交接文档 |

## 4. 已实现能力

### Agent Core

- API 创建任务后立即返回 `received`，后台继续理解、校验、路由和执行。
- 状态经 SQLite 持久化并通过 SSE 推送。
- 支持取消信号、乐观锁、幂等、超时、恢复和终态保留。

### 模型与路由

- Mock 模式用于离线测试。
- DeepSeek V4 Flash 通过 OpenAI-compatible CloudAdapter 调用。
- Ollama `qwen2.5:3b` 复用同一 CloudAdapter。
- D2 默认不上云，D3 禁止进入模型、日志、离线队列和持久化确认参数。

### 工具

- 文件：白名单索引、模糊搜索、真实候选、确认后处理；默认不打开桌面文件。
- 知识库：TXT/MD/DOCX、UTF-8/BOM/GB18030、增量导入、来源引用和拒答。
- 提醒：中文时间、周期提醒、查询、取消、完成和 R3 全量删除。
- 短文本：润色、摘要、草拟、语气调整，保留数字、日期和联系方式等事实。
- 会议纪要：从白名单文字稿生成可追溯 Markdown。

### Web 与确认

- 单文件 `static/index.html`，大小 15,248 字节。
- 桌面和手机响应式布局已通过浏览器实测。
- 支持候选文件、缺失时间和 R3 风险确认。
- 确认批准/拒绝、任务取消和结果交付均进入审计链。

## 5. 常用命令

在项目根目录执行：

```powershell
# 安装/更新开发环境
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"

# 启动 Web/API
agent-platform serve
# Web:  http://127.0.0.1:8000/
# API:  http://127.0.0.1:8000/docs

# 导入演示知识库
agent-platform import-docs demo_docs
agent-platform import-docs demo_docs --force

# 离线测试
pytest -q

# 完整重跑 DeepSeek/Qwen 对比
.\scripts\run_comparison.ps1

# 外部终端中断后复用完整报告
.\scripts\run_comparison.ps1 -Resume
```

## 6. 模型评测结果

| 指标 | DeepSeek V4 Flash | Qwen2.5-3B 本地 |
|---|---:|---:|
| 意图准确率 | 96.0% | 94.0% |
| 参数提取准确率 | 96.0% | 68.0% |
| 工具选择准确率 | 96.0% | 94.0% |
| 外层 Schema 合规率 | 100.0% | 100.0% |
| P50 | 1549.1 ms | 532.8 ms |
| P95 | 3852.0 ms | 641.6 ms |
| 失败用例 | 2 | 16 |

Qwen 的 16 条失败中，3 条为意图/工具错误，13 条为参数问题。完整表见 `evaluation/reports/comparison.md`。

## 7. 已知问题与踩坑记录

### 7.1 参数 Schema 过宽

`agent_platform/models/model.py` 中 `INTENT_RESPONSE_SCHEMA.arguments` 目前只是普通 object，没有按意图限制字段。因此 `question`、`text` 等错误字段也能获得 100% 外层 Schema 合规率。

### 7.2 评测精确匹配偏严

`EvaluationService` 使用预期参数子集的精确值比较。“公司报销标准是什么”被缩为“公司报销标准”时，实际检索可能有效，但会被判参数失败。后续需要拆分“契约正确”和“语义等价”。

### 7.3 失败报告没有实际参数

当前 JSON 失败项只记录 `actual_intent` 和失败维度，不记录 `actual_arguments`。本次为解释 Qwen 失败原因进行了同配置诊断复跑，但诊断结果未写入正式报告。下一步应直接在评测报告保存脱敏后的实际参数。

### 7.4 模型错误会中断整轮评测

当前 `EvaluationService.run` 没有按用例捕获 `ModelError`。Ollama 或云模型出现一次 502/超时会中止整轮，而不是记录单条失败。脚本通过预热和前置检查降低概率，但尚未实现真正的按用例容错。

### 7.5 SQLite 单进程锁

服务和 `agent-platform evaluate` 不能同时使用同一个任务数据库。对比脚本为健康检查服务注入独立临时数据库，评测进程继续使用默认数据库，避免 `DatabaseInUseError`。

### 7.6 本地代理导致 Ollama 502

Python `httpx` 默认继承代理环境，本地 `127.0.0.1:11434` 曾被代理拦截并返回空 502。脚本仅在 Qwen 子进程范围内临时追加 `NO_PROXY=127.0.0.1,localhost,::1`，结束后恢复原环境。

### 7.7 Ollama 冷启动

Agent `/health` 不会触发模型加载。首次正式请求可能在模型未就绪时失败，因此脚本在 Qwen 评测前执行最小 JSON 推理预热，最多检查三次。

### 7.8 Windows PowerShell 兼容

- 项目路径包含空格，传给 `Start-Process` 的报告路径必须显式加引号。
- Windows PowerShell 5.1 对无 BOM UTF-8 脚本不稳定，因此 `run_comparison.ps1` 的运行日志使用 ASCII；生成的 Markdown 仍为 UTF-8 中文。

## 8. 下一步开发顺序

### P0：参数契约优化

1. 将 `INTENT_RESPONSE_SCHEMA` 改为按意图区分的严格结构，或分两阶段先判意图再使用工具专属 Schema。
2. 在 CloudAdapter 分类提示词中加入当前失败模式的少量高质量示例。
3. 从原始用户文本确定性提取 Windows 路径，模型输出只作为候选。
4. 新增按意图白名单的参数归一化，不允许跨意图随意改键。
5. 对提醒动作和文本操作增加明确规则；`delete_all` 只能由明确全量删除短语触发。
6. 修改评测报告，保存脱敏后的实际参数和模型错误。
7. 为知识查询增加可配置语义容差，同时保留路径、ID、风险动作的严格匹配。

### P0 验收门槛

- 50 条固定集意图准确率 ≥95%。
- 参数提取准确率 ≥90%。
- 工具选择准确率 ≥98%。
- Schema 合规率 100%，且改为工具参数级合规。
- “取消提醒”不得再映射 `delete_all`；所有 R3 操作必须 100% 进入确认。
- 184 项现有测试继续通过，并为上述失败模式增加回归测试。

### P1：模型规格决策

工程优化后先复测 Qwen2.5-3B-Instruct。只有仍未达到门槛时，再比较 Qwen2.5-7B-Instruct。7B 不能替代权限、Schema、确定性执行和确认机制。

### P2：RK3588 验证

在目标板卡和最终量化格式上测量 TTFT、tokens/s、峰值内存、温升、连续运行、并发和 UI 响应。当前 Windows/Ollama Q4_K_M 数据不能作为 RKLLM W8A8 的性能承诺。8GB 只建议串行原型验证，16GB 更适合作为标准配置候选。

## 9. 关键安全边界

- 不读取、打印或提交 `.env` 中的 API Key。
- 不将 D3 凭据发送给模型或写入持久化、日志和离线队列。
- 不恢复或推断用户真实持仓、企业私有资料或历史敏感数据。
- 文件操作必须在配置白名单中；真实打开默认关闭。
- 删除、支付、交易、身份验证和其他高影响操作必须显式确认或由授权系统接管。

## 10. 验证与证据文件

- `evaluation/reports/deepseek.json`
- `evaluation/reports/qwen.json`
- `evaluation/reports/comparison.md`
- `work/comparison/*-evaluate.stdout.log`
- `work/comparison/*-evaluate.stderr.log`
- `tests/test_comparison_report.py`
- `README.md`
- `交付文档/2026-07-28_Agent_Platform_开发总结报告.md`

## 11. 接手检查清单

- [ ] 确认工作目录是 `D:\my new work\cloud flowing`。
- [ ] 确认 `.env` 当前为 DeepSeek，且不输出 API Key。
- [ ] 运行 `pytest -q`，基线应为 184 项通过。
- [ ] 阅读 `evaluation/reports/comparison.md` 和 16 条 Qwen 失败用例。
- [ ] 先修改参数契约和评测记录，再考虑扩大模型参数量。
- [ ] 完成优化后重新运行 `run_comparison.ps1`，不要只使用 `-Resume` 旧报告。
- [ ] 进入硬件阶段前确认目标板卡内存规格和量化格式。

