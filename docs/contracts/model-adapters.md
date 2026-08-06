# 模型适配器契约

## 内部契约

所有 Adapter 实现 `ModelAdapter.generate`：输入消息、响应 JSON Schema 和 Token 上限，输出必须是通过该 Schema 校验的 JSON 对象。网络、超时、繁忙和结构错误必须归一化为 `ModelError` 层级；`asyncio.CancelledError` 必须传播。

## 结构化响应

- 意图响应最多生成 192 Token，且仍受调用方/Provider 更小上限约束。
- 生产理解链先执行只返回意图的高置信预路由；未命中时调用最小意图分类 Schema；参数阶段只使用所选意图的接受 Schema。
- 接受直接 JSON 对象、纯 JSON 字符串、完整 Markdown JSON fence、前置完整 `<think>...</think>` 后的纯 JSON。
- 拒绝截断 JSON、多个 JSON 对象、JSON 前后的任意解释文字和 Schema 不匹配对象。
- 不修补括号、不猜测字段、不降低 JSON Schema。
- 完整 JSON 对象违反当前参数 Schema 时，允许使用原输出和精简校验错误修复一次；第二次仍不合规则失败，非法/截断 JSON 不进入修复。

## RKLLM 线协议

- Base URL 默认 `http://127.0.0.1:8080/v1`。
- 使用 `POST /chat/completions`，`stream=false`、`enable_thinking=false`。
- 请求字段和响应 `choices[0].message.content`/`usage` 由 `rkllm_contract.py` 校验。
- HTTP 429、503、5xx、连接失败和超时具有明确错误语义；400 类协议错误不可重试。

## 背压与回退

- 默认 `RKLLM_MAX_CONCURRENCY=1`，等待超过 `RKLLM_QUEUE_TIMEOUT_SECONDS` 返回 retryable busy error。
- 云回退必须同时满足：显式启用、主错误可重试、调用方显式传入 D0/D1。
- D2、D3、未知等级、结构化响应错误和取消不允许云回退。

## 验证边界

本地模拟服务验证线协议、错误归一化和 Agent 集成。只有目标 RK3588 上的官方 Runtime/Server 才能验证模型加载、输出质量、延迟、内存、温控、并发和长稳。
