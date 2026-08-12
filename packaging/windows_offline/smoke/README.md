# 离线包真实冒烟脚本

该目录会原样复制到离线包的 `scripts/smoke`。模型进程与 Agent 进程由包外层的启动/切换脚本管理；这里不启动、停止或并行切换模型。

```powershell
runtime\python\python.exe scripts\smoke\smoke.py model --bundle-root . --model-id qwen2.5-3b-instruct --output logs\smoke\qwen.json
runtime\python\python.exe scripts\smoke\smoke.py asr --bundle-root . --output logs\smoke\asr.json
runtime\python\python.exe scripts\smoke\smoke.py tts --bundle-root . --output logs\smoke\tts.json
runtime\python\python.exe scripts\smoke\smoke.py all --bundle-root . --model-id qwen2.5-3b-instruct --output logs\smoke\qwen-all.json
```

- `model` 检查 llama.cpp 健康接口和真实 Chat Completions，并用同一个 `X-Session-Id` 创建、轮询 Agent 通用问答任务。
- `asr` 通过 Windows SAPI 即时生成 16 kHz 单声道 PCM16 中文 WAV，把 PCM 帧直接交给 Faster-Whisper small，完成后删除临时音频。
- `tts` 基于同一会话的已完成任务依次生成四个音色，并把校验过的 WAV 保存到 `logs/smoke/tts`。
- 每个检查独立记录成功、耗时、结果或错误；任一检查失败时进程退出码为 `1`。
- JSON 证据会清理本机绝对路径，但保留实际模型回答、转写文本和包内相对产物路径。

