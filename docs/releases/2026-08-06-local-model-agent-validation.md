# 云湃 AI 音响项目 v0.02

## 本机大模型速度与 Agent 接入验证报告

- 测试日期：2026-08-06
- 测试工作区：`D:\my new work\cloud-flowing_0806`
- 测试方式：本机 Ollama，单模型串行加载
- 重要说明：本文的“吐词速度”指文本生成速度（token/s），不是语音合成或播放速度。

## 1. 结论先行

本次已在测试进程中打开 `MODEL_PROVIDER=cloud`，通过本机 Ollama 的 `/v1/chat/completions` 接入 Agent。当前可作为 Agent 默认本地模型的是 `qwen2.5:3b`：固定 60 条评测集的意图准确率、工具准确率、Schema 合规率均为 100%，归一化后的端到端 dry-run 准确率为 96.67%。

`qwen3:1.7b` 和 `lfm2.5-thinking:1.2b` 的裸生成速度更高，但没有与当前结构化输出适配器兼容，不能因为 token/s 更高就作为当前 Agent 的替代模型。

本次没有修改项目默认 `.env`。这样离线测试仍保持 `mock` 默认行为；需要复现本报告时使用文中的进程级环境变量。

## 2. 测试环境与模型

- Ollama：`0.32.5`
- 地址：`http://127.0.0.1:11434`
- GPU：AMD Radeon RX 6700 XT
- Agent 端点：本机 Ollama OpenAI-compatible `/v1/chat/completions`
- Agent 适配器：项目现有 `CloudModelAdapter`

| 模型 | 大小 | Ollama digest 前缀 |
|---|---:|---|
| `qwen2.5:3b` | 1,929,912,432 bytes | `357c53fb659c` |
| `qwen3:1.7b` | 1,359,293,444 bytes | `8f68893c685c` |
| `lfm2.5-thinking:1.2b` | 731,163,903 bytes | `95bd9d45385f` |

测试时每次只保留一个模型，避免三个模型同时驻留造成 GPU/runner 资源竞争和 502。速度测试先 warmup，再固定请求重复 5 次；Agent 测试使用固定 60 条评测集和 `--detailed`，评测容器使用临时数据库，未产生真实工具副作用。

## 3. 本机文本生成速度

速度来自 Ollama 原生 `/api/chat` 的 `eval_count / eval_duration`，固定 `temperature=0`、`num_predict=128`、`think=false`。均值和中位数均只统计 warmup 后的 5 次重复。

| 模型 | 平均生成速度 | 中位数 | 平均请求墙钟 | 平均生成 token | 结束原因 | 判读 |
|---|---:|---:|---:|---:|---|---|
| `qwen2.5:3b` | 135.52 token/s | 135.60 | 722.95 ms | 79 | stop | 输出长度和结束状态正常 |
| `qwen3:1.7b` | 212.17 token/s | 212.29 | 251.90 ms | 26 | stop | 裸生成速度较快 |
| `lfm2.5-thinking:1.2b` | 290.24 token/s | 290.26 | 515.37 ms | 128 | length | 达到 token 上限，输出没有自然结束，速度不可直接等同于有效响应速度 |

速度结果是文本模型基准，不包含 ASR、TTS、声卡播放和唤醒词链路。本项目当前没有在本次测试中测量音频吐词时延。

## 4. 接入 Agent 后的固定 60 条功能结果

### 4.1 总体指标

| 模型 | 意图准确率 | 参数准确率 | 工具准确率 | Schema 合规 | 归一化契约 | 端到端 dry-run | P50 / P95 |
|---|---:|---:|---:|---:|---:|---:|---:|
| `qwen2.5:3b` | 100.00% | 90.00% | 100.00% | 100.00% | 100.00% | 96.67% | 319.83 / 627.54 ms |
| `qwen3:1.7b` | 25.00% | 23.33% | 25.00% | 25.00% | 25.00% | 21.67% | 1,167.80 / 2,115.74 ms |
| `lfm2.5-thinking:1.2b` | 0.00% | 0.00% | 0.00% | 0.00% | 0.00% | 0.00% | 842.58 / 1,070.21 ms |

### 4.2 qwen2.5:3b 的功能覆盖

以下是 dry-run 的端到端通过情况。它验证了意图识别、参数抽取、参数归一化、策略/路由、工具选择及高风险确认分支；不会真的打开文件、删除记录或发送通知。

| 功能意图 | 评测条数 | 端到端结果 | 说明 |
|---|---:|---:|---|
| 文件打开 `file_open` | 10 | 8 条通过，2 条需要复核 | 2 条测试没有可用于语义判定的期望参数，不是工具执行失败 |
| 知识库查询 `knowledge_query` | 10 | 10/10 | 真实知识库检索副作用未执行 |
| 会议处理 `meeting_process` | 10 | 10/10 | 真实音频/转写文件处理未执行 |
| 提醒 `reminder_create` | 10 | 10/10 | 真实通知发送未执行 |
| 日程 `schedule_manage` | 5 | 5/5 | 删除/取消分支验证了确认要求 |
| 文本处理 `text_polish` | 10 | 10/10 | 只验证结构化任务参数，不代表润色文本质量 |
| 待办 `todo_manage` | 5 | 5/5 | 高风险删除分支进入确认状态 |

qwen2.5 的 6 条原始参数不完全匹配（`knowledge-03/05`、`schedule-02/04`、`text-04`、`todo-04`）都被项目已有归一化规则修正，归一化契约准确率仍为 100%。

### 4.3 qwen3:1.7b 与 lfm2.5-thinking:1.2b 的失败形态

- Qwen3：60 条中 45 条被判定为 `Cloud model returned invalid structured JSON`；只有部分预路由请求能生成可解析 JSON。其有效内容常为空，推理文本出现在响应的 `reasoning` 字段，当前适配器只读取 `message.content`。
- LFM2.5 Thinking：60 条全部结构化输出无效；同样返回了推理内容而不是 `message.content` 中的 JSON。
- 这不是网络不通：在相同的 `NO_PROXY` 条件下，两个模型都能返回 HTTP 200。失败点是当前 Agent 的结构化响应协议和模型输出格式不兼容。

## 5. 运行中的关键条件与问题

### 本地代理

Windows 系统代理开启时，Python `httpx` 默认会把 `127.0.0.1` 请求送入代理，项目请求表现为 502。复现本报告必须先设置：

```powershell
$env:NO_PROXY = "127.0.0.1,localhost"
$env:no_proxy = "127.0.0.1,localhost"
```

这是原始 `CloudModelAdapter` 的运行环境条件，不是 Ollama 模型服务故障。新增的 `OllamaModelAdapter` 使用原生 `/api/chat`，对回环地址自动关闭代理读取，不再依赖该环境变量。

### Thinking 模型兼容性

速度脚本使用 Ollama 原生接口的 `think=false`，所以测到的是可见正文生成速度；项目的 OpenAI-compatible `CloudModelAdapter` 当前没有发送 Ollama 专用 `think=false` 字段，也没有把 `reasoning` 字段转换为可解析正文。因此 qwen3 和 LFM 的速度结果不能直接推断为 Agent 可用性。

## 6. 未在本次测试中实现或确认的功能

本次 Agent 评测没有覆盖以下真实运行能力：RK3588/RKLLM 板端启动与性能、麦克风采集、唤醒词、ASR、TTS 音频合成与播放、真实文件打开、真实提醒/通知发送、外部日历或网络服务、长时间运行稳定性和多用户并发。

## 7. 建议

1. 当前本地 Agent 默认优先使用 `MODEL_PROVIDER=ollama` 搭配 `qwen2.5:3b`；验证其他 Ollama 模型只需替换 `MODEL_NAME` 并重跑固定评测。
2. qwen3/LFM 已经可以通过原生适配器进入 Agent，但仍需模型级提示、参数归一化和专项盲测，不能仅凭协议通过就作为产品默认模型。
3. 在确认模型兼容性前，不应把 qwen3/LFM 的较高裸 token/s 写入产品级响应时延承诺。

## 8. 可复现证据

- 任务记录：[2026-08-06-local-model-agent-validation.md](../tasks/2026-08-06-local-model-agent-validation.md)
- 速度脚本：`scripts/benchmark_local_models.ps1`
- 速度原始结果：`work/local-model-validation/speed.json`
- Agent 原始结果：`work/local-model-validation/qwen25.json`、`qwen3.json`、`lfm.json`
- Agent 原始快照：`work/local-model-validation/qwen25.raw.jsonl`、`qwen3.raw.jsonl`、`lfm.raw.jsonl`

## 9. 回归测试状态

命令：`D:\my new work\cloud flowing\.venv\Scripts\python.exe -m pytest -q`

结果：306 个测试中 305 个通过，1 个失败。失败为 `tests/test_parameter_normalizer.py::test_schedule_title_request_queries_candidates_and_cancel_preview_is_pre_execution`：测试固定创建 `2026-07-29` 和 `2026-07-30` 的日程，而当前日期为 `2026-08-06`，默认日程查询窗口已不再包含这两个过去日期，因此候选为空。该问题与本次模型速度脚本、模型环境变量和报告文件无关，未在本次任务中修改。

## 10. Ollama 原生适配器改版复测

在基线提交 `9a0d97e` 之后，新增 `MODEL_PROVIDER=ollama` 和 `OllamaModelAdapter`。它使用原生 `/api/chat`、`format=json`、可配置 `think`，并对本机回环地址关闭 `httpx` 的系统代理读取。以下结果来自改版后的同一批 60 条用例；旧 Cloud Adapter 结果保留在第 4 节，作为改版前对照。

| 模型 | 意图准确率 | 参数准确率 | Schema 合规 | 归一化契约 | 端到端 dry-run | P50 / P95 | Schema 无效 |
|---|---:|---:|---:|---:|---:|---:|---:|
| `qwen2.5:3b` | 100.00% | 90.00% | 100.00% | 100.00% | 96.67% | 338.91 / 770.76 ms | 0/60 |
| `qwen3:1.7b` | 90.00% | 78.33% | 90.00% | 90.00% | 65.00% | 301.24 / 770.08 ms | 6/60 |
| `lfm2.5-thinking:1.2b` | 91.67% | 66.67% | 91.67% | 91.67% | 81.67% | 337.84 / 792.77 ms | 5/60 |

改版前 qwen3/LFM 的 45/60、60/60 条失败主要是 OpenAI-compatible 响应只有 `reasoning`、`message.content` 为空；改版后两者均能稳定进入 Agent 结构化解析和 dry-run 流程。改版并没有把小模型的参数抽取质量自动提升到 qwen2.5 水平，qwen3/LFM 仍需后续模型级提示、字段归一化或专项评测优化。

改版新增验证：`tests/test_ollama_adapter.py` 11 项通过，`compileall` 通过。真实结果文件为 `work/local-model-validation/ollama-native-qwen25.json`、`ollama-native-qwen3.json`、`ollama-native-lfm.json`。
