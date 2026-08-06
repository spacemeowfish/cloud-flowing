# Ollama 原生模型适配器

- 状态：已完成
- 日期：2026-08-06
- 基线提交：`9a0d97e` (`chore: baseline cloud-flowing v0.02`)

## 目标

1. 保留现有 `mock`、`cloud`、`rkllm` 行为。
2. 新增 `MODEL_PROVIDER=ollama`，通过原生 `/api/chat` 验证本机 Ollama 模型。
3. 默认关闭 thinking，避免 Qwen3/LFM 等模型只返回 reasoning、没有结构化正文。
4. 本机回环地址不读取系统代理，消除 `httpx` 请求 502 的环境依赖。
5. 用单元测试和本机固定 60 条评测验证适配器协议与真实模型效果。

## 模块契约

- Agent Core 继续只依赖 `ModelAdapter.generate`。
- Ollama Adapter 负责协议转换、错误归一化和最终正文抽取。
- 共享 `parse_structured_response` 负责 JSON 解析和 Schema 校验。
- thinking/reasoning 内容不允许作为最终工具参数解析。

## 验收条件

- 原生请求固定包含 `stream=false`、`format=json`、可配置 `think` 和受限 `num_predict`。
- HTTP、超时和非法协议响应映射到现有 `ModelError` 层级。
- 三个本机模型均产出新的固定 60 条 Agent 报告。
- 全量 pytest、compileall 和 Git 状态有明确记录。

## 实际结果

- 新增 `OllamaModelAdapter`、`MODEL_PROVIDER=ollama`、Ollama 配置项、CLI `--mode ollama`、适配器契约文档和 11 项单元测试。
- qwen2.5：意图 100%、参数 90%、Schema 100%、归一化契约 100%、端到端 96.67%。
- qwen3：意图 90%、参数 78.33%、Schema 90%、归一化契约 90%、端到端 65%，Schema 无效 6/60。
- LFM2.5：意图 91.67%、参数 66.67%、Schema 91.67%、归一化契约 91.67%、端到端 81.67%，Schema 无效 5/60。
- `pytest --tb=no`：306 项中 305 项通过、1 项失败；失败是现有固定过去日期的日程测试。模型结果保存于 `work/local-model-validation/ollama-native-*.json`。
