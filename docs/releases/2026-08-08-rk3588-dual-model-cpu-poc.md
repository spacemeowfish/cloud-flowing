# RK3588 双模型 CPU PoC 实施报告

- 日期：2026-08-09（任务始于 2026-08-08）
- 目标：证明 Qwen2.5-3B-Instruct 或 LFM2.5-1.2B-Instruct 与 Agent 能在 8 GB RK3588 上以 CPU、单模型串行方式运行
- 当前结论：PC 侧代码、两份 `linux/arm64` 离线镜像、安装/测试自动化和 ARM64 模拟冒烟已完成；RK3588 真机性能尚未执行，不能宣称完成上板验收

## 已实现

1. 新增 `general_chat`（R0/D0），收口数学、常识、翻译和闲聊；基础算术使用受限本地求值，不调用模型。普通回答走纯文本 Provider 请求，不附加 JSON Schema；完整闭合的 thinking 前缀会被剥离，未闭合推理、占位符和提示词回显会被拒绝。
2. 知识库空结果只对非本地资料型误路由回退一次；明确知识库、公司制度、产品资料请求仍保持“无来源不回答”的边界。
3. 新增 llama.cpp OpenAI-compatible Provider，支持结构化 Agent Schema、有界并发、排队超时、错误归一化和本机代理绕过。
4. 对提醒、待办、日程、文本操作等无歧义命令采用确定性参数抽取；模型误报 `missing_fields` 时，只有完整 Schema 已满足才清除误报。
5. 新增同一 Dockerfile 的两个 `linux/arm64` 单模型构建目标，最终镜像仅保留 Agent、Web 操作台、静态 `llama-server`、运行依赖和一个 Q4_K_M 模型。
6. 线程、上下文、最大输出、批大小和并发全部由环境变量控制；启动档、4096 性能档和 8192 压力档无需重建镜像。
7. 板端脚本先探测系统资源，再串行测试 4/6/8 线程，记录加载、TTFT、Tokens/s、内存、CPU、温度和 10 次连续请求成功率，最终写出 `selected.env`。

## 固定版本

| 组件 | 固定值 |
|---|---|
| llama.cpp | commit `69bf643`（release b10327） |
| Qwen | `Qwen/Qwen2.5-3B-Instruct-GGUF` revision `cc1e68e...`，Q4_K_M SHA256 `626b4a66...c62d` |
| LFM | `LiquidAI/LFM2.5-1.2B-Instruct-GGUF` revision `012803c...`，Q4_K_M SHA256 `b1b3de11...4f5` |

完整 revision、文件名与 SHA256 在 `deployment/rk3588/docker/models.lock.json`。下载器在构建前流式校验 SHA256，校验失败立即停止。

## 本机模型验证

以下只验证当前 Agent 逻辑，不代表 RK3588 CPU 性能。Qwen 是本机 Ollama Q4_K_M；LFM 是 `lfm2.5-thinking:1.2b` 代理，不是目标 `LFM2.5-1.2B-Instruct-Q4_K_M.gguf`。

| 指标 | Qwen2.5 3B | LFM thinking 1.2B 代理 |
|---|---:|---:|
| 固定用例 | 60 | 60 |
| 意图准确率 | 100% | 100% |
| 原始参数准确率 | 96.67% | 98.33% |
| 工具准确率 | 100% | 100% |
| Schema 合规率 | 100% | 100% |
| 归一化契约准确率 | 100% | 100% |
| 已裁定语义准确率 | 100% | 100% |
| 端到端准确率 | 96.67% | 96.67% |
| 待人工裁定 | 2 | 2 |

两条 `needs_review` 为 `file-08`、`file-09`，评测数据故意没有 `expected_arguments`，pipeline 已执行，不是工具失败。

受影响功能工作流结果：Qwen 为 8/8；LFM thinking 代理为 7/8。LFM 代理的知识、文件、提醒、待办、日程、文本处理和会议纪要均通过；通用问答中的算术与常识可用，但“把你好翻译成英文”在 512 Token 内只输出未闭合推理，质量门禁将任务判为失败。该限制属于本机 thinking 代理，不能推断目标 LFM Instruct GGUF 同样失败；板端固定请求已包含该翻译用例，必须以目标镜像结果为准。

报告文件：

- `evaluation/reports/2026-08-08-rk3588-poc-qwen2.5-3b.json`
- `evaluation/reports/2026-08-08-rk3588-poc-qwen2.5-3b-affected-workflows.json`
- `evaluation/reports/2026-08-08-rk3588-poc-lfm2.5-thinking-1.2b-proxy.json`
- `evaluation/reports/2026-08-08-rk3588-poc-lfm2.5-thinking-1.2b-proxy-affected-workflows.json`

## 自动化验证

- `python -m pytest -q`：373 项通过。
- `python -m compileall -q agent_platform deployment/rk3588/docker tests`：通过。
- `node --check static/app.js`：通过。
- `build_images.ps1` PowerShell AST 解析：通过。
- `models.lock.json` 解析与两模型固定摘要检查：通过。
- ARM64 容器内对 `entrypoint.sh`、源/交付版 `install.sh` 和 `board_probe.sh` 执行 `sh -n`：通过。
- `git diff --check`：通过。

## PC 构建与 ARM64 模拟冒烟

PC 环境为 Windows 10.0.19045.6466、WSL 2.7.11、Docker Engine 29.6.2、Buildx 0.35.0。Buildx 支持 `linux/arm64`，实际 ARM64 容器返回 `aarch64`。两份镜像都在本机完成构建、`docker load`、镜像检查、ARM64 二进制执行和完整服务启动。

| 产物 | tar 字节数 | tar SHA256 | Docker 镜像大小 | 镜像 ID |
|---|---:|---|---:|---|
| Qwen2.5-3B-Instruct Q4_K_M | 2,130,424,320 | `889540488cc7775b6e60298be946cb5cfb3faced20c6ab8890f1656d072f598e` | 2,130,404,025 | `sha256:b91b2b45ed389035d1f0fe6995d45aaddf6fd7499f181a31e521e7a1b92a8793` |
| LFM2.5-1.2B-Instruct Q4_K_M | 792,465,408 | `94e0080940431a433a379f15d714a19fd38cde975a4fc0035ee2527c966db084` | 792,444,980 | `sha256:13cd85e8515af5dbe0eeeb909f6a83e4bdf90f6f4c1f6261c4bac4965d3fd42f` |

两镜像均为 `linux/arm64`，`llama-server --version` 返回 b10327 / commit `69bf643`；模型内置 SHA256 校验通过，镜像中无 gcc、g++、cmake、Ollama 和测试目录。构建脚本生成 `SHA256SUMS`，板端 `install.sh` 会在 `docker load` 前自动核对 tar。

首次完整启动发现两个仅静态测试未覆盖的封装问题：资源根列表被写成普通字符串，以及 `serve` 提前导入精简镜像未包含的评测包。两项均已修复并增加回归测试；修复后的 Qwen 和 LFM 容器都达到 `healthy`，Agent `/health` 返回 `model_provider=llamacpp`。

PC ARM64 模拟结果只证明镜像与协议可执行：Qwen 模型约 11.3 秒加载，确定性 `1+1`、待办查询和直接模型回答 `2` 通过；LFM 模型约 3.3 秒加载，确定性 `1+1`、局域网通用问答和待办查询通过。模拟环境下 Qwen 通用问答/总结和 LFM 总结触发 30 秒工具超时，模型日志显示请求被正常取消；不得把 PC 模拟吞吐或这些超时直接推断为 RK3588 结果。

## 构建与真机入口

在具备 Docker Buildx 的构建机上，从仓库根目录执行：

```powershell
python deployment/rk3588/docker/prepare_models.py --model all --output models
./deployment/rk3588/docker/build_images.ps1 -Model all
```

已生成输出：

- `dist/rk3588/cloud-flowing-qwen-rk3588-cpu-poc.tar`
- `dist/rk3588/cloud-flowing-lfm-rk3588-cpu-poc.tar`
- `dist/rk3588/SHA256SUMS`
- `dist/rk3588-qwen/`：Qwen 单模型交付包。
- `dist/rk3588-lfm/`：LFM 单模型交付包。

交换机上一次只安装一个：

```sh
sh install.sh qwen /path/cloud-flowing-qwen-rk3588-cpu-poc.tar
# 测完并停止 Qwen 后再执行 LFM
sh install.sh lfm /path/cloud-flowing-lfm-rk3588-cpu-poc.tar
```

只有目标设备生成 `board-probe.txt`、`benchmark-report.json` 和 `selected.env`，且最佳 4096 档无 OOM、无明显卡顿、10 次连续请求全部成功后，才可把该模型标记为“RK3588 CPU PoC 通过”。4096 不稳定时才退回 2048；8192 仅记录压力边界，不作为首轮默认配置。
