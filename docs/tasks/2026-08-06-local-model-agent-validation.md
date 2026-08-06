# 本机模型速度与 Agent 接入验证任务

- 状态：已完成
- 日期：2026-08-06
- 工作区：`D:\my new work\cloud-flowing_0806`
- Git：目标工作区没有 Git 元数据，本次不能提供提交级差异证据

## 目标与边界

1. 以 `MODEL_PROVIDER=cloud` 打开现有 CloudModelAdapter，连接本机 Ollama OpenAI-compatible 接口。
2. 测量本机三个模型的文本生成 token 速度。这里的“吐词速度”是模型生成文本的 token/s，不是语音 TTS 播放速度。
3. 用项目固定 60 条评测集验证 Agent 的意图、参数、工具、Schema 和 dry-run 端到端链路。
4. 不执行真实文件打开、删除、通知发送、外部网络调用，也不把本机 Ollama 结果解释为 RK3588/RKLLM 真机性能。

## 测试对象

| 模型 | Ollama digest | 文件大小 |
|---|---|---:|
| `qwen2.5:3b` | `357c53fb659c` | 1,929,912,432 bytes |
| `qwen3:1.7b` | `8f68893c685c` | 1,359,293,444 bytes |
| `lfm2.5-thinking:1.2b` | `95bd9d45385f` | 731,163,903 bytes |

## 运行条件

- Ollama `0.32.5`，`127.0.0.1:11434`，本机 AMD Radeon RX 6700 XT。
- 每次只加载一个模型；先 warmup，再执行 5 次固定请求。
- Agent 评测使用旧工作区已安装的 `.venv` Python，避免改变目标目录依赖。
- 测试进程使用以下环境变量；没有写入项目 `.env`：

```text
MODEL_PROVIDER=cloud
MODEL_BASE_URL=http://127.0.0.1:11434/v1
MODEL_API_KEY=ollama
MODEL_TIMEOUT_SECONDS=120
NO_PROXY=127.0.0.1,localhost
```

`NO_PROXY` 是必要条件。Windows 系统代理会让 Python/httpx 的本机请求得到 502；旁路代理后 Ollama `/v1` 请求正常。

## 命令与证据

- 速度脚本：`scripts/benchmark_local_models.ps1`
- 速度结果：`work/local-model-validation/speed.json`
- Agent 结果：`work/local-model-validation/qwen25.json`、`qwen3.json`、`lfm.json`
- 原始快照：同目录下的 `*.raw.jsonl`
- 评测命令：

```powershell
python -m agent_platform.cli evaluate --mode cloud --cases evaluation/test_cases --detailed --expected-total 60
```

## 结果摘要

- `qwen2.5:3b`：固定 60 条中意图准确率 100%，Schema 合规 100%，工具准确率 100%，归一化后的契约准确率 100%，dry-run 端到端 96.67%。
- `qwen3:1.7b`：意图准确率 25%，45/60 条结构化输出无效，端到端 21.67%。
- `lfm2.5-thinking:1.2b`：60/60 条结构化输出无效，端到端 0%。

## 主要风险结论

- `CloudModelAdapter` 只读取 OpenAI 响应的 `choices[0].message.content`。Qwen3 和 LFM 在本次 OpenAI-compatible 请求中把推理放在 `reasoning`，正文为空或不是可解析 JSON，当前适配器会按“invalid structured JSON”拒绝。
- 速度脚本通过 Ollama 原生 `/api/chat` 使用 `think=false` 测量可见生成；项目当前 CloudModelAdapter 没有发送该 Ollama 专用字段。因此速度结果不能直接等同于三个模型在 Agent 结构化任务上的效果。
- 本次验证确认了真实模型链路，但没有覆盖 RK3588 板端启动、RKLLM Server、麦克风/唤醒词、ASR、TTS、真实系统副作用和长时间稳定性。

## 回归测试

- 命令：`D:\my new work\cloud flowing\.venv\Scripts\python.exe -m pytest -q`
- 结果：299 个测试中 298 个通过、1 个失败。
- 失败测试：`tests/test_parameter_normalizer.py::test_schedule_title_request_queries_candidates_and_cancel_preview_is_pre_execution`。
- 判断：测试固定使用 2026-07-29/30 日程，而当前日期为 2026-08-06，默认查询窗口排除了过去日期；与本次模型接入测试文件无关，未修改。
