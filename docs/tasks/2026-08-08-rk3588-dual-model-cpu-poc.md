# RK3588 双模型 CPU PoC 与通用问答

- 状态：PC 侧实施、ARM64 镜像构建与模拟冒烟完成，待 RK3588 真机验收
- 日期：2026-08-08
- 基线：`main` / `ebc208f` (`fix: make CLI installation self-contained`)
- 前置任务：[`2026-08-07-three-model-affected-functional-validation.md`](2026-08-07-three-model-affected-functional-validation.md)

## 背景与目标

目标设备是 8 GB、单通道内存、无声卡且尚未配置 RKNPU/RKLLM 的 RK3588 交换机。首轮交付不是量产镜像，而是两套 `linux/arm64` CPU PoC，分别验证 Qwen2.5-3B-Instruct Q4_K_M 和 LFM2.5-1.2B-Instruct Q4_K_M 能与当前 Agent 通过 llama.cpp OpenAI-compatible API 串行运行。

同时补齐普通问题的收口能力：新增 `general_chat`，让数学、常识、翻译和闲聊不再错误进入本地知识库；知识检索仅在非本地资料型请求无命中时受控回退一次。

## 已确认边界

- 只验收 Web/API 文本交互，不包含声卡、麦克风、ASR、TTS 或扬声器。
- 首轮 Qwen 和 LFM 都使用 CPU + llama.cpp；RKNPU/RKLLM 是后续加速阶段。
- 两个模型一次只运行一个，不能在 8 GB 设备上同时驻留。
- 模型权重仅用于内部研发评测，不作为可公开分发的产品镜像。
- 镜像参数通过环境变量配置；2048/256 是启动档，不是最终能力上限。
- 未在目标板完成 `docker load`、模型加载和连续请求前，不声称镜像可直接安装或性能达标。

## 架构不变量

- 模型继续通过 `ModelAdapter.generate(messages, response_schema, max_tokens)` 返回 Schema 合规 JSON；通用回答只在 `answer` 字段内自由生成。
- 确定性模块拥有意图边界、参数 Schema、权限、风险确认、执行、审计和结果门禁。
- `general_chat` 不写业务数据表，但仍保留脱敏后的标准任务状态和审计事件。
- 明确要求查询知识库、本地资料或组织专属制度时，检索无来源不得用模型常识伪造成本地答案。
- 基础算术由受限表达式求值器完成，不为 `1+1` 额外消耗模型推理。
- Docker 中模型服务仅监听容器回环地址；只对外暴露 Agent Web/API。

## 影响范围

- 模型与工具契约：`agent_platform/models`、`agent_platform/adapters`、`agent_platform/core`、`agent_platform/tools`
- 运行配置与组合根：`agent_platform/config/settings.py`、`agent_platform/api/container.py`
- 操作台和文档：`static/app.js`、`README.md`、模型适配契约与 ADR
- RK3588 PoC：`deployment/rk3588/docker/`、板端探测、安装和性能测试脚本
- 回归：工具、路由、Gateway、API、llama.cpp 协议、部署脚本和固定评测契约

## 验收条件

1. `1+1=?` 稳定返回 `2`，普通常识/翻译路由到 `general_chat`，明确知识库请求仍保持来源边界。
2. 模型误报已满足参数为 `missing_fields` 时不触发人工补参；真正缺失字段仍停止执行。
3. `MODEL_PROVIDER=llamacpp` 可通过受控队列调用 `/v1/chat/completions`，错误和 Schema 语义与现有本地 Adapter 一致。
4. 两个 ARM64 镜像由同一 Dockerfile 按模型参数构建，最终层只含运行依赖、Agent、llama-server 和一个模型。
5. 启动档、性能档和压力档均由环境变量切换；真机脚本串行比较 4/6/8 线程并记录实际性能。
6. 聚焦测试、全量测试、`compileall`、JavaScript 语法检查、Shell 语法检查和 `git diff --check` 通过。

## 验证记录

- 实施前全量基线：340 项通过。
- 实施后最终全量回归：`python -m pytest -q`，373 项通过。
- Python `compileall`、`static/app.js` 语法、PowerShell 构建脚本解析、模型锁 JSON 与 `git diff --check` 通过。
- PC 已安装并验证 WSL 2.7.11、Docker Engine 29.6.2、Buildx 0.35.0；Buildx 与运行时均实际返回 `aarch64`/`linux/arm64`。
- 两份官方锁定 GGUF 已下载并校验：Qwen 为 2,104,932,768 字节、SHA256 `626b4a6678b86442240e33df819e00132d3ba7dddfe1cdc4fbb18e0a9615c62d`；LFM 为 730,895,168 字节、SHA256 `b1b3de114215d9507409a662a501a631095a479a419584e8a2ded6304b19b4f5`。
- 已生成并重新导入两个最终 tar。Qwen tar 为 2,130,424,320 字节、SHA256 `889540488cc7775b6e60298be946cb5cfb3faced20c6ab8890f1656d072f598e`；LFM tar 为 792,465,408 字节、SHA256 `94e0080940431a433a379f15d714a19fd38cde975a4fc0035ee2527c966db084`。
- 交付物已拆成 `dist/rk3588-qwen` 和 `dist/rk3588-lfm` 两个独立目录；每个目录只含一个模型 tar、对应单行 `SHA256SUMS`、模型专属 `PACKAGE-MANIFEST.txt` 和完整安装/测试说明。构建脚本支持 `-PackageOnly`，已有镜像可不重建直接重新分包。
- 两个镜像均由 Docker inspect 确认为 `linux/arm64`；ARM64 模拟执行报告 `llama-server` b10327 / commit `69bf643`，模型内置摘要通过，且运行镜像不含 gcc、g++、cmake、Ollama 和测试目录。交付目录包含安装前自动校验的 `SHA256SUMS`。
- 完整启动冒烟发现并修复两项封装问题：列表型资源根改为 JSON 环境变量；`serve` 不再提前导入镜像未包含的评测包。Qwen 和 LFM 修复后均达到 Docker `healthy`，`/health` 返回 `model_provider=llamacpp`，能力接口列出 8 个工具。
- PC ARM64 模拟中，Qwen 的 `1+1` 与待办查询完成，直接模型请求返回 `2`；LFM 的 `1+1`、局域网通用问答与待办查询完成。Qwen 通用问答/总结及 LFM 总结在 30 秒工具门禁处超时，日志显示模型仍在生成且被正常取消；这是模拟环境冒烟证据，不作为 RK3588 性能结论，也不调整产品超时。
- Qwen2.5 3B 本机 Ollama 固定 60 条：意图/工具/Schema/归一化契约/已裁定语义均为 100%，端到端 96.67%，`needs_review=2`。
- LFM2.5 thinking 1.2B 本机代理固定 60 条：意图/工具/Schema/归一化契约/已裁定语义均为 100%，端到端 96.67%，`needs_review=2`。该结果不是目标 Instruct GGUF 成绩。
- Qwen 受影响功能工作流为 8/8。LFM thinking 代理为 7/8：知识、文件、提醒、待办、日程、文本处理和会议纪要通过；纯文本通用问答中的简短翻译在 512 Token 内只产生未闭合推理，被质量门禁正确拒绝。目标 Instruct GGUF 必须在镜像/真机阶段重新验证，不能用代理结果代替。
- RK3588 真机的板端探测、4/6/8 线程对照、4096/8192 上下文、TTFT、Tokens/s、峰值内存、温度和连续 10 次请求仍未执行。
- 完整结果见 [`../releases/2026-08-08-rk3588-dual-model-cpu-poc.md`](../releases/2026-08-08-rk3588-dual-model-cpu-poc.md)。

## 遗留风险

- 目标交换机的系统、内核、glibc、Docker 和 CPU 拓扑尚未确认，必须先运行板端探测。
- Q4_K_M 的 PC/Ollama 或 x86 llama.cpp 结果不能替代 RK3588 CPU 性能与稳定性。
- 如果 Qwen Q4_K_M 在 8 GB 设备上不稳定，允许显式改用官方 Q3_K_M 做对照，但不得静默替换并沿用 Q4_K_M 报告。
