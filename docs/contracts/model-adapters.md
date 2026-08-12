# 模型适配器契约

## 内部契约

所有 Adapter 实现两条边界：`ModelAdapter.generate` 输入消息、响应 JSON Schema 和 Token 上限，输出必须是通过 Schema 校验的 JSON 对象；`ModelAdapter.generate_text` 只输入消息和 Token 上限，返回非空纯文本，不附加 JSON Schema 或 JSON response format。网络、超时、繁忙和结构错误必须归一化为 `ModelError` 层级；`asyncio.CancelledError` 必须传播。

`generate_text` 只供 `general_chat` 等明确的 D0 自由回答使用。意图、参数、工具选择仍必须走 `generate`，不能因为模型较小而放松结构化 Agent 协议。

## 结构化响应

- 意图响应最多生成 192 Token，且仍受调用方/Provider 更小上限约束。
- 生产理解链先执行只返回意图的高置信预路由；未命中时调用最小意图分类 Schema；参数阶段只使用所选意图的接受 Schema。
- 接受直接 JSON 对象、纯 JSON 字符串、完整 Markdown JSON fence、前置完整 `<think>...</think>` 后的纯 JSON。
- 拒绝截断 JSON、多个 JSON 对象、JSON 前后的任意解释文字和 Schema 不匹配对象。
- 不修补括号、不猜测字段、不降低 JSON Schema。
- 完整 JSON 对象违反当前参数 Schema 时，允许使用原输出和精简校验错误修复一次；第二次仍不合规则失败，非法/截断 JSON 不进入修复。

## 通用问答纯文本

- `general_chat` 不请求 JSON，基础算术优先由受限本地求值器处理。
- 模型只输出最终答案；一个完整闭合的前置 `<think>...</think>` 或 `<analysis>...</analysis>` 块会被剥离，未闭合推理直接拒绝。
- 最终答案若包含 FACT/占位符、结构化内部合同或系统提示词回显则拒绝，不使用文本处理工具的事实占位保护。
- 纯文本错误仍遵守 Provider 的超时、背压、数据级别和显式云回退边界。

## RKLLM 线协议

- Base URL 默认 `http://127.0.0.1:8080/v1`。
- 使用 `POST /chat/completions`，`stream=false`、`enable_thinking=false`。
- 请求字段和响应 `choices[0].message.content`/`usage` 由 `rkllm_contract.py` 校验。
- HTTP 429、503、5xx、连接失败和超时具有明确错误语义；400 类协议错误不可重试。

## Ollama 原生协议

- `MODEL_PROVIDER=ollama` 使用 `POST /api/chat`，不复用 OpenAI-compatible Cloud Adapter。
- 结构化调用固定 `stream=false`、`format=json`；纯文本调用不发送 `format`。`OLLAMA_THINKING_ENABLED=false` 时两者均发送 `think=false`。
- 意图响应继续使用共享的 192 Token 上限，并受 `OLLAMA_MAX_NEW_TOKENS` 更小上限约束。
- 本机 `127.0.0.1`、`localhost`、`::1` 连接不读取系统代理，避免回环请求被代理转发。
- 只把 `message.content` 作为最终答案；独立 thinking/reasoning 字段不得进入工具参数。

## llama.cpp 本地协议

- `MODEL_PROVIDER=llamacpp` 使用默认地址 `http://127.0.0.1:8080/v1/chat/completions`，不复用需要 API Key 的 Cloud Adapter。
- 结构化调用固定 `stream=false`、`temperature=0`、`response_format.type=json_object`，并继续用共享系统提示和 JSON Schema 校验 `choices[0].message.content`；纯文本调用不发送 `response_format` 或 Schema 系统提示。
- `LLAMACPP_MAX_TOKENS` 是 Provider 输出上限；意图响应仍使用共享的 192 Token 更小上限。
- `LLAMACPP_PARALLEL` 同时是 Agent 侧有界并发；等待超过 `LLAMACPP_QUEUE_TIMEOUT_SECONDS` 返回 busy error。
- 回环地址不读取系统代理。HTTP 429、503、5xx、连接失败、超时和非法协议响应必须映射到现有 `ModelError` 层级。
- `LLAMACPP_THREADS`、`LLAMACPP_CONTEXT_SIZE` 和 `LLAMACPP_BATCH_SIZE` 由 llama-server 启动脚本消费，不改变 Adapter 接口。

## 背压与回退

- RKLLM 和 llama.cpp 默认单并发并采用有界等待；超过各自队列超时返回 retryable busy error。
- 云回退必须同时满足：显式启用、主错误可重试、调用方显式传入 D0/D1。
- D2、D3、未知等级、结构化响应错误和取消不允许云回退。

## 验证边界

本地模拟服务验证线协议、错误归一化和 Agent 集成。只有目标 RK3588 上的官方 Runtime/Server 才能验证模型加载、输出质量、延迟、内存、温控、并发和长稳。
