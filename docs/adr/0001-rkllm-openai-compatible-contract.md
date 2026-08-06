# ADR-0001：RKLLM 使用官方 OpenAI 兼容线协议

- 状态：已采纳
- 日期：2026-08-02

## 背景

项目需要在没有 RK3588 的阶段完成模型适配、协议测试和部署准备。RKLLM v1.3.0 官方 Server Demo 已提供 `/v1/models` 与 `/v1/chat/completions`，而仓库中的云模型适配器也使用 OpenAI 兼容响应结构。

## 选项

1. 自建 `/generate`，再在板端维护一层映射。
2. 直接冻结官方 OpenAI 兼容端点，并在 Adapter 内隔离官方版本差异。
3. 在 Agent 进程内直接绑定 RKLLM C API。

## 决定

采用选项 2。内部继续以 `ModelAdapter.generate(messages, response_schema, max_tokens)` 为稳定边界；RKLLM Adapter 负责把它映射到官方非流式 `/v1/chat/completions`。

当前 Agent 调用是短请求结构化输出，不需要把 SSE 流式协议暴露给 Agent Core。模拟服务和 Adapter 都必须使用仓库内 Pydantic 线协议模型校验。

## 后果

- 不维护与官方重复的私有板端 Server 协议。
- 官方字段变化只影响 RKLLM Adapter/契约测试。
- 系统 Prompt 在 RKLLM 请求中被扁平化进单个用户 Prompt，避免依赖官方 Demo 对 system message 的实现细节。
- 真实板端仍必须针对冻结的 Toolkit、Runtime、Server Demo 和驱动组合执行契约测试。

## 验证

- RKLLM 线协议模型单元测试。
- 官方协议模拟服务集成测试。
- 上板后对 `/v1/models`、结构化正常响应、503 繁忙响应执行契约冒烟。
