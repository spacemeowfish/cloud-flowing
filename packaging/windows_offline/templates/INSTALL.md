# 云湃 Agent Windows x64 离线内部测试包

## 先看许可状态

打开 `PACKAGE-STATUS.md`。只有其中同时显示 `BUILD_MODE: distributable`
和 `REDISTRIBUTABLE: YES` 时，才可按公司流程转交他人。`local-validation`
包仅限资产持有人在本机隔离验证，不是可分发交付物。

## 系统要求

- Windows 10/11 x64，建议 16 GB 内存、至少 12 GB 可用磁盘。
- 使用本机 CPU 串行加载一个模型；无需预装 Python、Ollama 或编译器。
- 浏览器、麦克风和 Windows PowerShell 5.1 或 PowerShell 7。
- 所有服务只监听 `127.0.0.1`。

## 解压与首次自检

完整解压到英文或中文路径均可，不要在 ZIP 内直接运行。进入解压目录：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\Accept-Licenses.ps1
.\Self-Check.ps1
```

先阅读 `THIRD_PARTY_LICENSES.md` 及其中链接的固定上游许可证。
`Accept-Licenses.ps1` 会逐个要求输入 `I ACCEPT`，只记录当前用户的本机
使用确认，不会授予或扩大再分发权。随后自检核对系统架构、运行时、模型、
配置与 SHA256。未获得音色权利证明时不要导入参考 WAV。

## 启动与访问

```powershell
.\Start-Agent.ps1
```

启动脚本先串行加载 `config/active-model.txt` 指定的 GGUF，再启动 Agent。
浏览器访问 `http://127.0.0.1:8000/`，健康检查为
`http://127.0.0.1:8000/health`。日志位于 `logs/`。

## 模型切换

```powershell
.\Switch-Model.ps1 -Model qwen
.\Switch-Model.ps1 -Model lfm
```

切换会先停止当前 llama.cpp 与 Agent，再只加载目标模型，避免两个 GGUF
同时占用内存。Qwen 与 LFM 的许可证条件不同，必须分别确认。

## 麦克风与语音输入

在操作台按住录音按钮说话、松开后等待 Faster-Whisper 转写。转写只回填
输入框，不会自动提交；原始 PCM 仅驻留内存。若设备列表为空，请在
Windows 隐私设置中允许桌面应用访问麦克风。

## ZipVoice 四音色

ZipVoice 不是 Agent 工具，只朗读已完成任务的可见文本。四个预期音色为
`news-female1`、`male1`、`female1`、`female2`。当前参考 WAV 未证明可再
分发。可分发候选包必须默认禁用，只有取得权利证明后才能通过
`Import-Voices.ps1` 导入。本机验证包可能已由资产持有人显式启用这四个
WAV，根目录会持续显示 `NON_DISTRIBUTABLE_LOCAL_VALIDATION`；该包仍不得
转交他人。操作台提供生成、播放、停止和重新生成。

## 核心测试

先运行自检。手工体验时再启动服务，并在操作台依次测试通用问答、知识查询、文件查找、
提醒、待办、日程、文本处理和会议纪要。真实依赖冒烟使用：

```powershell
.\Smoke-Test.ps1
```

`Smoke-Test.ps1` 必须在服务已停止时运行；它会自行串行启动 Qwen、切换
LFM、测试 ASR/TTS 并在结束时停止服务。自动 ASR 冒烟需要 Windows 已安装
简体中文 SAPI 语音；实际麦克风仍应在操作台另做手工验证。

报告应分别记录 Qwen、LFM、Agent、Faster-Whisper 与 ZipVoice，不能用
Mock 或“任务 completed”代替真实输出检查。

## 停止、重装和数据

```powershell
.\Stop-Agent.ps1
```

重装前备份 `data/`，然后解压一份全新包并按需恢复数据。不要复制旧包的
`config/license-acceptance.json` 来代替新用户的许可证确认。数据库、
审计、TTS 与会议输出位于 `data/`/`logs/`，删除前先备份。

## 常见故障

- 端口占用：停止占用 8000/8080 的程序，或检查 `config/bundle.json`。
- 模型加载失败：重新运行 `Self-Check.ps1`，核对磁盘空间与 SHA256。
- 首次响应慢：模型加载和 CPU 首 Token 延迟属于预期，查看 llama 日志。
- TTS 不可用：确认音色已合法导入，且 ZipVoice/vocoder 自检通过。
- ASR 模型缺失：核对 `models/faster-whisper-small/model.bin`。
- 依赖导入失败：不要自行 pip 联网安装；使用原始包重新解压。
