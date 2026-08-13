# 同事 Fork 后的 Windows PC 完整测试说明

本说明用于同事从自己的 GitHub Fork 获取云湃 Agent 源码，并在自己的 Windows PC 上自行下载模型进行内部测试。模型、参考音频、`.env`、测试数据和日志不得提交到 Git。

## 1. 电脑要求

- Windows 10 22H2 或 Windows 11 x64。
- 建议 16 GB 内存、至少 12 GB 可用磁盘。
- 可访问 GitHub、PyPI、Ollama 和 Hugging Face。
- 浏览器和麦克风；Windows 已允许桌面应用访问麦克风。
- 安装 Git for Windows。Python 3.12 与 Ollama 可由准备脚本通过 `winget` 安装。

PC 测试不等于 RK3588、实体音响、远场麦克风、功耗、温控或长时间稳定性验收。

## 2. Fork 和 Clone

1. 打开 <https://github.com/spacemeowfish/cloud-flowing>，点击右上角 **Fork**。
2. 在自己的 Fork 页面复制 HTTPS 地址。
3. 在 PowerShell 执行，替换 `<你的GitHub用户名>`：

```powershell
git clone https://github.com/<你的GitHub用户名>/cloud-flowing.git
Set-Location .\cloud-flowing
git remote add upstream https://github.com/spacemeowfish/cloud-flowing.git
git remote -v
```

`origin` 应指向同事自己的 Fork，`upstream` 应指向原仓库。

## 3. 一键准备运行环境和模型

先阅读模型许可证，再执行：

- Qwen 2.5 3B：<https://ollama.com/library/qwen2.5:3b>
- LFM2.5 1.2B：<https://ollama.com/library/lfm2.5-thinking:1.2b>

只准备 Qwen、LFM 和 Faster-Whisper：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\Setup-PC-Test.ps1
```

同时下载 ZipVoice 模型和 vocoder：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\Setup-PC-Test.ps1 -IncludeZipVoice
```

脚本会：

- 检查并通过 `winget` 安装 Python 3.12 和 Ollama。
- 如果机器上已有 `py.exe` 但没有可用的 Python 3.12 runtime，脚本会继续回退到 `winget` 安装流程。
- 创建 `.venv` 并安装 `dev,tts,voice` 依赖。
- 通过 Ollama 下载 `qwen2.5:3b` 和 `lfm2.5-thinking:1.2b`。
- 下载固定版本的 Faster-Whisper small，并校验 SHA256。
- 使用 `-IncludeZipVoice` 时下载官方 ZipVoice INT8 模型及 vocoder，并校验 SHA256；选择性解压时跳过上游 `test_wavs` 示例音频，随后删除下载归档。
- 即使使用 `-IncludeZipVoice`，ZipVoice 仍默认保持禁用；需要在设置页手动切换到 `zipvoice` 并提供合法参考 WAV 和逐字文本。
- 创建本机 `.env`，默认选择 Qwen，并启用 Faster-Whisper。

下载中断后可以重新运行，已通过 SHA256 校验的文件会跳过。模型和本机配置位于被 Git 忽略的 `.local-models/`、`.venv/` 和 `.env`。

脚本不会保留或配置上游示例音色，也不会替同事下载私人音色。下载模型不等于获得超出上游许可证的权利；同事及所在公司应自行确认使用条件。

## 4. ZipVoice 音色准备

要测试 TTS，测试人员需要准备一段本人录制或公司已明确授权使用的参考 WAV，并写下与录音逐字一致的文本。

参考音频要求：

- WAV 格式，单声道 PCM16 或 PCM24。
- 内容清晰、无背景音乐。
- 参考文本必须与音频逐字匹配。
- 不使用同事、名人、客户或其他未明确授权人员的声音。

启动软件后，在设置页配置：

- TTS Provider：`zipvoice`
- Model directory：`.local-models/zipvoice/sherpa-onnx-zipvoice-distill-int8-zh-en-emilia`
- Vocoder：`.local-models/zipvoice/vocos_24khz.onnx`
- Reference WAV：测试人员合法准备的本地 WAV
- Reference text：参考 WAV 的逐字文本

保存设置后等待软件自动重启，并检查健康状态中的 `tts.ready=true`。

## 5. 启动软件

```powershell
.\.venv\Scripts\python.exe -m agent_platform.cli desktop
```

浏览器打开：

- 操作台：<http://127.0.0.1:8000/>
- 健康检查：<http://127.0.0.1:8000/health>
- API 文档：<http://127.0.0.1:8000/docs>

服务只应监听 `127.0.0.1`，不要暴露到局域网或公网。

## 6. 完整测试清单

在设置页确认 Provider 为 `ollama`，先选择 `qwen2.5:3b`：

- 通用问答、数学、翻译。
- 知识库导入与有来源问答。
- 授权文件查询与打开确认。
- 提醒、待办和日程。
- 文本处理和会议纪要生成。
- 麦克风按住说话、松开转写；转写结果只回填，不应自动提交。
- 配置合法参考音色后，测试 TTS 生成、播放、停止和重新生成。

然后在设置页切换到 `lfm2.5-thinking:1.2b`，至少重复通用问答、工具调用和文本处理测试。两个模型的结果应分别记录，不要把 Mock 结果当成真实模型结果。

运行自动化检查：

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
node .ai-team/check.mjs --base upstream/main
```

## 7. 记录问题并提交 PR

开始修改前创建分支：

```powershell
git fetch upstream
git switch -c fix/pc-test-问题简述 upstream/main
```

修改代码时同步更新 `.ai-team/TASK.md`，记录问题、复现方法、修改内容、测试命令、真实结果和残留风险。检查后提交到自己的 Fork：

```powershell
git status
git diff --check
node .ai-team/check.mjs --base upstream/main
git add <本次修改的文件>
git commit -m "fix: 修复PC测试发现的问题"
git push -u origin fix/pc-test-问题简述
```

随后在 GitHub 从同事 Fork 的分支向 `spacemeowfish/cloud-flowing:main` 创建 Pull Request。不要提交以下内容：

- `.env`、API 密钥或个人路径。
- `.local-models/`、GGUF、ONNX、Whisper 模型或 Ollama 模型。
- 私人参考 WAV、生成音频、数据库、日志和用户数据。

## 8. 常见问题

- `winget` 不存在：先从 Microsoft Store 更新“应用安装程序”，或手动安装 Python 3.12 和 Ollama 后重跑脚本。
- Ollama 拉取失败：确认 `http://127.0.0.1:11434/api/tags` 可访问，再重跑脚本。
- Hugging Face 下载慢：保留已经完成的文件，重新执行脚本即可继续准备其他缺失文件。
- 麦克风没有设备：在 Windows 隐私设置中允许桌面应用访问麦克风。
- TTS 未就绪：确认模型/vocoder 路径存在，音色 WAV 合法，参考文本逐字匹配。
- 修改配置后异常：检查项目根目录 `.env.backups/`，设置服务会保留最近五份备份。
