# RKLLM 上板前集成任务记录

- 状态：PC 可验证范围已完成；等待模型转换环境和 RK3588 真机验收
- 日期：2026-08-02
- 基线：非 Git 工作区；当前收集 230 项测试、固定评测集 60 条

## 目标

1. 冻结 Agent 内部模型契约和 RKLLM 官方 HTTP 线协议。
2. 复用结构化 Prompt、JSON 解析和 JSON Schema 校验。
3. 实现可配置的 RKLLM HTTP Adapter、单并发背压和安全的模型级回退。
4. 提供可运行的官方协议模拟服务，并通过全部 60 条固定用例。
5. 准备 W8A8 校准、模型导出、版本清单、systemd 服务和上板验收材料。

## 非目标

- 不声称 RKLLM Runtime、NPU、模型转换产物或 RK3588 性能已验证。
- 不在没有目标板、匹配驱动和 RKLLM SDK 的情况下生成伪造的性能数据。
- 不改变 Agent Core 中确定性工具负责权限、确认、执行和审计的边界。

## 开发依据

- 官方 RKLLM v1.3.0 Server Demo 提供 `/v1/models` 和 `/v1/chat/completions`。
- 官方 Server 以单模型锁串行推理，繁忙时返回 HTTP 503。
- 官方转换示例使用场景相关校准数据，并为 RK3588 示例采用 W8A8、normal、3 NPU cores。
- 当前 `RKLLMModelAdapter` 是占位实现；`CloudModelAdapter` 已有 192 Token 意图上限，但没有共享解析模块。

## 架构不变量

1. `ModelAdapter.generate` 只返回符合调用方 JSON Schema 的对象。
2. RKLLM 线协议使用官方 OpenAI 兼容端点，不新增私有 `/generate` 产品协议。
3. 解析器只容忍完整 Markdown JSON fence 和前置完整 `<think>...</think>`；任意解释文字、多对象或截断 JSON 必须失败。
4. RKLLM 默认最多一个在途请求；排队必须有超时，繁忙错误必须可重试。
5. 云回退默认关闭；启用后也只允许显式标记为 D0/D1 的请求，D2/D3 和未知等级不得回退。
6. 取消必须原样传播，不能被转换为重试或云回退。
7. 模拟服务通过只能证明协议和集成，不等于真机模型效果或性能通过。

## 影响范围

- `agent_platform/adapters`：共享结构化响应、RKLLM 协议、Adapter、模拟服务。
- `agent_platform/core/model_gateway.py`：可选且分级约束的模型回退。
- `agent_platform/config/settings.py`、`.env.example`：RKLLM 与回退配置。
- `agent_platform/core/agent_core.py`：向模型网关传递已分类的数据等级。
- `deployment/rk3588`：校准、转换、部署与验收准备物。
- `tests`、`README.md`：回归防护和当前基线。

## 验收条件

- RKLLM Adapter 正常、非法响应、400/429/500/503、超时、排队超时、取消均有测试。
- 共享解析同时覆盖 Cloud 和 RKLLM，且拒绝截断/任意包裹内容。
- 回退仅对 retryable 错误及 D0/D1 生效。
- 本地 RKLLM 模拟服务跑完 60 条固定评测，意图、参数、工具均为 100%。
- 全量 `pytest` 通过；部署脚本完成静态/干跑验证。
- 任务记录写入真实验证结果和仍需真机完成的门槛。

## 实施决策

- 采用 ADR-0001 的官方 OpenAI 兼容协议。
- RKLLM 请求将系统约束和当前会话扁平化为单个用户 Prompt，以规避官方示例普通对话路径未稳定消费 system message 的兼容风险。
- 模型回退放在 `ModelGateway`，不复用业务工具的 `EdgeCloudRouter`。

## 验证结果

- 共享解析、RKLLM Adapter、协议模拟、回退与原模型网关聚焦测试：`44 passed`。
- 部署资产测试：`5 passed`。
- 全量回归：`265 passed in 5.28s`；收集数量同为 265。
- 实际 loopback 模拟 Server：`127.0.0.1:8081`，`/v1/models` 契约通过。
- CLI 经真实 HTTP 跑完 60 条固定用例并保存 60 行 raw JSONL：意图、参数、工具、Schema 均为 100%。
- 详细端到端为 96.67%；仅 `file-08`、`file-09` 因没有期望参数而标记 `needs_review`，其 Pipeline 均成功执行。
- Agent 实际监听 `127.0.0.1:8000`，`/health` 返回 `provider=rkllm`；知识查询冒烟完成并调用 `knowledge_query`。
- 28 条校准种子验证通过，SHA256：`4d06932b830fa91f9d9b0926fc6ddc4e84f50cecb0f1feff1b8f838370e5b79a`。
- W8A8 构建配置干跑通过，SHA256：`0d25332a4d6270124b201fa363d625dfc2fd2c3e76aa896a93500d1562fe111e`；未固定模型 revision 时正式导出会拒绝执行。
- 对 2026-08-02 获取的官方当前 `flask_server.py`（756 行）执行 AST 补丁验证，localhost 和进程内调频保护均成功应用。
- `scripts/run_comparison.ps1` PowerShell 语法解析通过；旧的 50 条硬编码已更新为 60。
- `python -m compileall -q agent_platform deployment` 通过；新增两个 console entry point 已安装。
- 敏感信息扫描未发现真实凭据，只有既有测试中的合成密钥样本和配置字段名。

## 遗留风险

- 当前项目虚拟环境未安装 `rkllm-toolkit`、`transformers` 或 `torch`，任务也未提供 Hugging Face 模型目录和固定 source revision，因此未生成 `data_quant.json`、`.rkllm` 或 `model-manifest.json`。
- 已在 Windows/Ollama 对真实 `qwen2.5:3b` 完成固定 60 条 v3.1 评测：意图/工具/Schema 100%，规范化契约 100%，端到端 96.67%；报告为 `evaluation/reports/qwen2.5-3b-v3.1-staged-60.json`。该结果是量化前 PC 基线，不能替代 RKLLM 量化后和 RK3588 真机复测。
- RKLLM Runtime、NPU 驱动、模型加载、真实结构化质量、延迟、内存、温度、降频、100 次连续运行和 8 小时长稳必须按真机验收表完成。
- systemd unit 已通过静态测试，但目标镜像的用户组、设备节点、频率脚本权限和目录布局仍需上板核对。
- 本任务实施阶段工作区尚未初始化 Git，因此当时以任务记录、自动化测试和运行产物保留证据；这些内容随后一并纳入首个 Git 基线提交。
