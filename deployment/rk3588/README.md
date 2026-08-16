# RK3588 上板前准备与部署

本目录把 PC 阶段可完成的模型校准、W8A8 转换、官方 Server 准备、systemd 服务和验收入口固化下来。目录中的测试通过不代表 RK3588 Runtime、NPU 或性能已经验证。

## 1. 冻结版本

1. 将 `model-build-config.json` 的 `source_model_revision` 改为 Qwen2.5-3B-Instruct 的精确 Hugging Face commit。
2. 记录并固定 RKLLM Toolkit、Runtime、官方 `rknn-llm` commit、NPU 驱动和系统镜像。
3. 不要混用不同发布包中的 Toolkit、Runtime 和 `librkllmrt.so`。

当前协议代码按官方 v1.3.0 Server Demo 的 `/v1/models`、`/v1/chat/completions` 和 per-request `max_tokens` 设计。官方入口：https://github.com/airockchip/rknn-llm

## 2. 校准数据

先做无需模型的结构检查：

```bash
python deployment/rk3588/generate_calibration.py --validate-only
```

在安装 `torch`、`transformers` 且模型已下载的独立 PC 环境生成校准对：

```bash
python deployment/rk3588/generate_calibration.py \
  --model-dir /models/Qwen2.5-3B-Instruct \
  --output deployment/rk3588/data_quant.json
```

28 条种子覆盖七类真实业务分布，但不复用固定评测集原句。生成器使用生产结构化 Prompt，目标文本只解码新生成 Token。

## 3. W8A8 转换

先检查构建参数；默认配置故意保留未固定 revision 标记，正式导出会拒绝未固定版本：

```bash
python deployment/rk3588/export_rkllm.py --validate-only
```

安装与目标 Runtime 匹配的 `rkllm-toolkit` 后执行：

```bash
python deployment/rk3588/export_rkllm.py \
  --model-dir /models/Qwen2.5-3B-Instruct \
  --dataset deployment/rk3588/data_quant.json \
  --output deployment/rk3588/qwen2.5-3b-instruct-w8a8-rk3588.rkllm
```

成功后同时生成 `model-manifest.json`，记录源码 revision、量化参数、校准集和模型 SHA256、Python 与关键包版本。模型文件和生成的校准输出不提交到源码仓库。

## 4. 准备官方 Server

从固定 commit 取官方 `examples/rkllm_server_demo/rkllm_server/flask_server.py`，然后生成本机绑定版本：

```bash
python deployment/rk3588/prepare_vendor_server.py \
  --source /src/rknn-llm/examples/rkllm_server_demo/rkllm_server/flask_server.py \
  --output /opt/agent-platform/vendor/rkllm/flask_server_local.py
```

脚本通过 AST 确认官方入口形状后只做三项修改：host 改为环境可控且默认 `127.0.0.1`；port 改为环境可控；进程内 `sudo` 调频默认禁用。systemd 在启动 Server 前以显式特权步骤运行固定频率脚本。

## 5. systemd

1. 创建 `agent-platform` 系统用户，并赋予目标镜像要求的 `render`、`video` 设备组。
2. 将 `.env.rk3588.example` 复制为 `/etc/agent-platform/rk3588.env`，权限设为 `0600`。需要受信任局域网预览时，将 `AGENT_HOST` 改为 `0.0.0.0` 并在该文件设置非空 `DEVELOPER_PASSWORD`；不要把真实密码写回仓库。
3. 安装两个 unit 到 `/etc/systemd/system/`，核对模型、Runtime、Python 和数据目录路径。
4. 执行 `systemctl daemon-reload && systemctl enable --now agent-platform.service`。
5. 通过 `journalctl -u rkllm-server -u agent-platform` 检查模型加载和重启原因。

云回退默认关闭。确需启用时，密钥只能放在权限受限的环境文件中；代码仍只允许 D0/D1 在可重试模型错误后回退。

## 6. 验收入口

```bash
python deployment/rk3588/healthcheck.py --wait 120
MODEL_PROVIDER=rkllm agent-platform evaluate --mode rkllm --detailed \
  --output evaluation/reports/rk3588.json \
  --capture-raw evaluation/reports/rk3588.raw.jsonl \
  --prompt-version rkllm-v1
```

完整门槛见 `acceptance-checklist.md`。在模型、Server、Agent、60 条评测、性能与长稳全部实测前，不得把 `hardware_validation` 从 `not_run` 改为通过。
