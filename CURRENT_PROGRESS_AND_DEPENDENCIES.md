# Agent Platform 当前进展与必要依赖

- 交付日期：2026-08-02
- 项目版本：`0.1.0`
- 代码基线：`main` / `11be82585b48f1a2f036e1ede31362be43dbf5ce`
- 基线提交：`feat: establish local-first agent platform baseline`
- 交付补充：本包在该提交上补入本说明和 `deployment/rk3588/.env.rk3588.example`，不改变运行代码
- 目标模型：`Qwen2.5-3B-Instruct`
- 当前结论：PC/Ollama 与 RKLLM 上板前准备已完成；RK3588 真机转换、部署、性能和长稳验收尚未完成

## 1. 当前进展

### 1.1 已完成并验证

1. 本地优先 Agent Platform MVP

   - 已实现模型网关、结构化 Schema 校验、任务状态机、会话持久化、权限与数据分级、端云路由、离线队列和脱敏审计。
   - 已实现待办、日程、提醒、文件查找/打开、知识库、短文本处理和会议纪要工具。
   - 已提供 CLI、FastAPI、REST、SSE 和本地 Web 任务中心。
   - 默认只监听 `127.0.0.1`，使用 Mock 模型，不调用云端，不允许真实文件打开。

2. T4 短文本处理修复

   - 已修复 `summarize` 分支草稿变量未初始化导致的崩溃。
   - `summarize`、`polish`、`rewrite`、`shorten` 四类操作均有真实工具测试和 Agent 集成测试。

3. Qwen2.5-3B 精度优化

   - 已实现高置信意图预路由、单意图参数 Schema、受限一次 Schema 修复和严格失败边界。
   - Windows/Ollama 上使用固定 60 条中文用例完成真实 `qwen2.5:3b` v3.1 评测。
   - 结果：意图 100%、参数 90%、工具 100%、Schema 100%、规范化契约 100%、语义匹配 96.67%、端到端 96.67%。
   - 两条 `file_open` 用例因评测定义没有期望参数而保持 `needs_review`；其 Pipeline 本身执行成功。

4. RKLLM 上板前集成

   - 已冻结 OpenAI-compatible `/v1/chat/completions` 契约并实现 RKLLM Adapter。
   - 已实现共享结构化响应解析、单并发背压、排队超时、取消传播和受数据等级约束的云回退。
   - 已提供本地协议模拟 Server、W8A8 校准生成器、导出入口、官方 Server 补丁器、systemd unit、健康检查和真机验收表。
   - 本地 RKLLM 协议模拟固定 60 条通过；这只证明协议与 Agent 集成，不代表真实 NPU 性能。

5. 当前自动化验证

   - `pytest` 收集并通过 296 项测试。
   - `python -m compileall -q agent_platform evaluation deployment` 通过。
   - Git 基线已建立，当前交付代码对应提交 `11be825`。

### 1.2 尚未完成

1. 尚未安装和冻结匹配的 RKLLM Toolkit、Runtime、RKNPU 驱动、系统镜像与官方 Server commit。
2. `source_model_revision` 仍是占位值，尚未生成 `data_quant.json`、`.rkllm` 和 `model-manifest.json`。
3. 尚未在 RK3588 上验证模型加载、量化后准确率、首 Token 延迟、Tokens/s、内存、温控、降频、100 次连续运行和 8 小时长稳。
4. 尚未在目标 Linux 镜像上确认设备权限、systemd 启停、日志轮转、异常断电恢复和真实外设。
5. API 本身不提供账号认证；如需暴露到局域网，必须先接入外部认证代理。
6. 真实天气、票务等外部连接器不属于当前默认验证范围。
7. 当前 60 条属于固定回归集；模型继续优化前应另建盲测扩展集，不能把同一批数据同时当训练依据和最终盲测。

## 2. 必要依赖

### 2.1 核心运行依赖

| 项目 | 要求 | 本次验证环境 |
|---|---|---|
| Python | `>=3.11` | `3.12.10` |
| setuptools | `>=69`，构建源码包时需要 | 标准隔离构建已验证 |
| wheel | 构建源码包时需要 | 标准隔离构建已验证 |
| FastAPI | `>=0.115,<1` | `0.140.7` |
| HTTPX | `>=0.27,<1` | `0.28.1` |
| jsonschema | `>=4.22,<5` | `4.26.0` |
| Pydantic | `>=2.7,<3` | `2.13.4` |
| pydantic-settings | `>=2.2,<3` | `2.14.2` |
| python-docx | `>=1.1,<2` | `1.2.0` |
| PyYAML | `>=6,<7` | `6.0.3` |
| Uvicorn | `>=0.30,<1` | `0.51.0` |
| SQLite | Python 标准库自带 | Python 3.12.10 内置 |
| tzdata | Windows 需要 | 由项目标记自动安装 |

安装范围以 `pyproject.toml` 为唯一依赖声明来源。普通联网安装会在隔离环境中获取 `setuptools` 和 `wheel`；使用 `--no-build-isolation` 或完全离线安装时必须提前安装这两项。源码包不包含 Python 安装包或离线 wheel；离线部署时需要提前准备与目标架构匹配的 wheelhouse。

### 2.2 开发和回归测试依赖

| 项目 | 声明范围 | 本次验证版本 |
|---|---|---|
| pytest | `>=8,<9` | `8.4.2` |
| pytest-asyncio | `>=0.23,<1` | `0.26.0` |
| pytest-cov | `>=5,<7` | `6.3.0` |

### 2.3 真实 Qwen PC 评测依赖（可选）

- Ollama；本次验证版本为 `0.32.5`。
- Ollama 模型 `qwen2.5:3b`；本次模型大小约 1.93 GB。
- 本次模型 digest：`357c53fb659c5076de1d65ccb0b397446227b71a42be9d1603d46168015c9e4b`。
- Ollama 默认地址：`http://127.0.0.1:11434`。
- 模型本体不在压缩包内，需要单独下载。

DeepSeek 对比是可选路径。真实 API Key 不在压缩包内，也不应提交到 Git；需要使用者自行创建本地 `.env.deepseek`。

### 2.4 RK3588 真机依赖（上板时必需）

- RK3588 Linux 板卡；8 GB 可用于串行原型验证，正式标准配置优先评估 16 GB。
- 与目标镜像和驱动严格匹配的 RKLLM Toolkit、RKLLM Runtime、`librkllmrt.so` 和 RKNPU 驱动。
- 固定 commit 的 Rockchip `rknn-llm` 官方 Server Demo。
- 固定 revision 的 `Qwen/Qwen2.5-3B-Instruct` 原始模型目录。
- 模型转换 PC 环境中的 `torch`、`transformers` 和 `rkllm-toolkit`。
- 目标机上的 Python 3.11+、本项目运行依赖、systemd、正确的 `render`/`video` 设备组和数据目录权限。

RKLLM 组件没有在本包中提供。Toolkit、Runtime、驱动和 `librkllmrt.so` 不得跨版本混用。

## 3. 快速安装与启动

Windows PowerShell：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
agent-platform serve
```

Linux/ARM64：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
cp .env.example .env
agent-platform serve
```

启动后访问：

- Web：`http://127.0.0.1:8000/`
- API 文档：`http://127.0.0.1:8000/docs`
- 健康检查：`http://127.0.0.1:8000/health`

## 4. 验证命令

```powershell
pytest
python -m compileall -q agent_platform evaluation deployment
agent-platform evaluate --mode mock
```

真实 Qwen A/B：

```powershell
.\scripts\run_qwen_ab.ps1
```

RKLLM 本地协议模拟：

```powershell
python -m agent_platform.devtools.rkllm_mock_server
$env:MODEL_PROVIDER="rkllm"
$env:RKLLM_SERVER_URL="http://127.0.0.1:8081/v1"
agent-platform evaluate --mode rkllm --detailed --output evaluation/reports/rkllm-mock.json
```

## 5. 关键证据

- 任务记录：`docs/tasks/2026-08-02-qwen-accuracy-and-t4-hardening.md`
- RKLLM 任务记录：`docs/tasks/2026-08-02-rkllm-prehardware-integration.md`
- 真机步骤：`deployment/rk3588/README.md`
- 真机验收表：`deployment/rk3588/acceptance-checklist.md`
- Qwen v3.1 报告：`evaluation/reports/qwen2.5-3b-v3.1-staged-60.json`
- Qwen v3.1 raw：`evaluation/reports/qwen2.5-3b-v3.1-staged-60.raw.jsonl`
- 报告 SHA256：`ca5688546365028afc5fa89c658329685904a037eb97d213e77f9ea01ba96c17`
- raw SHA256：`f1c6e13c510a55ed07d4e5c61bc184ac3eb5071448049ca2aed82b4af37e2be5`

## 6. 压缩包边界

压缩包包含源码、测试、`.env.example`、`deployment/rk3588/.env.rk3588.example`、部署脚本、固定评测集、正式评测证据、项目文档和合成演示数据。这两个环境文件都只包含示例值和空密钥。

压缩包不包含：

- `.git`、`.venv`、缓存和覆盖率文件；
- `.env`、`.env.deepseek`、`.env.qwen` 或任何真实 API Key；
- 运行数据库、日志、锁文件和临时评测目录；
- Ollama 模型、Hugging Face 原始模型、`.rkllm` 模型；
- RKLLM Toolkit/Runtime、系统镜像、驱动或其他厂商二进制。

因此本包是可审计的源码交付包，不是包含模型和系统依赖的一键离线镜像。
