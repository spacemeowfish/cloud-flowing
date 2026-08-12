# Windows x64 离线内部测试包

- 任务：`PC-OFFLINE-BUNDLE-001`
- 状态：实施中
- 日期：2026-08-13
- 分支：`codex/pc-offline-test-bundle`
- 流程基线：PR #1 merge commit `cf0f0c35c9cf0ce98ec58b2382e11ffb03816d3c`

## 目标与非目标

本任务将现有 Windows PC Agent、两个 GGUF、本地 ASR 和 ZipVoice 做成可解压、可自检、可启动和可停止的内部测试 ZIP。它不新增安装器、托盘、开机自启、唤醒词、常驻监听、会议录音、流式 TTS 或外部连接器。

## 交付契约

- 运行时固定且离线：便携 Python 3.12、Windows x64 llama.cpp CPU 服务和预安装 Python 依赖。
- 两个模型串行运行，默认 Qwen2.5；切换模型会受控停止并重新启动本地模型与 Agent。
- 所有路径由包根解析，模板和说明不得包含构建机用户名、绝对路径或秘密。
- 模型、音频、运行时和 ZIP 只存在于独立 dist，不进入 Git。
- 每项资产记录官方来源、版本、SHA256、许可证和再分发结论。不能证明再分发权的资产不进入公开 Release。
- 隔离冒烟必须观察真实模型、真实 Faster-Whisper 和真实 ZipVoice 输出，不用 Mock 替代。

## 预期目录

```text
cloud-flowing-pc-offline/
  app/
  config/
  models/
  runtime/python/
  runtime/llama.cpp/
  scripts/
  data/
  logs/
  INSTALL.md
  MANIFEST.json
  SHA256SUMS
  THIRD_PARTY_LICENSES.md
```

## 验收证据

实施完成后在 `docs/releases/` 保存不含本机绝对路径的总结，在独立 dist 的 `evidence/` 保存完整命令、耗时、服务日志、模型响应摘要、ASR 文本和四个 WAV 元数据。大二进制与生成音频不得提交到 Git。

## 当前已知风险

- PR #1 已合并，但普通 Git HTTPS 曾临时不可用；提交 PR 前必须恢复并 rebase 到最新 `origin/main`。
- 两份 GGUF 的文件存在和哈希已确认，精确上游与许可证仍需由模型元数据和官方页面交叉验证。
- 四个参考 WAV 的来源与可再分发权必须单独确认，不能仅因本机已有文件就视为可公开发布。
- GitHub Release 单文件大小限制可能要求拆分资产，不能用 Git LFS 或普通 Git 历史绕过。
