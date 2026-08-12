# Windows x64 离线内部测试包

- 任务：`PC-OFFLINE-BUNDLE-001`
- 状态：`blocked`（技术验证通过，再分发许可未通过）
- 日期：2026-08-13
- 分支：`codex/pc-offline-test-bundle`
- 流程基线：PR #1 merge commit `cf0f0c35c9cf0ce98ec58b2382e11ffb03816d3c`

## 目标与非目标

本任务将现有 Windows PC Agent、两个 GGUF、本地 ASR 和 ZipVoice 做成可解压、可自检、可启动和可停止的内部测试包。它不新增安装器、托盘、开机自启、唤醒词、常驻监听、会议录音、流式 TTS 或外部连接器。

工程链路已在独立安装目录真实跑通，但完整构建只能标记为 `NON_DISTRIBUTABLE_LOCAL_VALIDATION`。在许可闭环前，它仅供当前所有者本机验证，不得发送给同事，也不得上传 GitHub Release。

## 实施结果

- 便携 Python 3.12、Windows x64 llama.cpp CPU 服务和固定 Python 依赖均由包内相对路径加载。
- Qwen2.5 和 LFM 两个 GGUF 串行运行，默认 Qwen2.5；模型切换会受控停止并重启模型服务与 Agent。
- 配置模板不含密钥、本机用户名或绝对路径；应用资源根可由包根确定。
- 包内提供启动、停止、自检、模型切换、资产授权确认、音色导入和真实冒烟脚本。
- 构建目录已生成 `MANIFEST.json`、`SHA256SUMS`、`PACKAGE-STATUS.json`、中文安装说明和第三方许可证摘要。
- Python 依赖安装到较短的 `runtime/packages`，构建器裁剪未使用的 ONNX 开发工具，并把最长相对路径限制为 120 字符；全部运行脚本禁用 `.pyc` 写入。
- 工作分支已正式 rebase 到 `cf0f0c35`，不再以 `1053a53` 作为待修正的临时父提交。

## 隔离验证

最终源码构建在全新独立安装目录完成真实冒烟；归档随后在另一个全新独立解压目录完成内容哈希和自检复核。两者均使用包内运行时和相对配置，不依赖项目工作区中的 Python 环境。结果如下：

| 验证项 | 结果 | 说明 |
|---|---:|---|
| Self-Check | 23/23 通过 | 0 失败；另有 1 条预期的“不可分发本机验证包”警告 |
| Qwen 模型与 Agent | 4/4 通过 | 真实模型请求，不以 Mock 代替 |
| LFM 模型与 Agent | 4/4 通过 | 真实模型请求，不以 Mock 代替 |
| Faster-Whisper ASR | 3/3 通过 | 完成真实转写和结果校验 |
| ZipVoice TTS | 6/6 通过 | 四个音色均生成并校验有效 WAV |
| 服务停止 | 通过 | 停止后相关监听端口数量为 0 |

最终源码提交为 `15113c43b2bbd27b06aaacc0a127b4f703b37a10`。干净构建目录包含 `4,699` 个文件，总大小 `3,851,010,582` bytes；其中初始负载清单记录 `4,696` 个文件、`3,849,542,620` bytes。最长相对路径为 108 字符；深路径隔离目录的最长完整路径为 235 字符。冒烟产生的日志和 WAV 位于隔离副本，不进入干净归档。

Zip64 本机验证归档名为 `cloud-flowing-windows-x64-offline-local-validation.zip`，大小 `3,636,131,543` bytes，SHA256 为 `422fa4517257884a2a7253ef19a22f6cb29ccfeefa18dc7231cefd81c46cf07d`。ZIP 完整性检查覆盖 `4,699` 个条目且无损坏项；最终独立解压目录复核 `SHA256SUMS` 共 `4,694` 条、0 错误，自检 23/23 通过。运行与自检后仍为 0 个 `.pyc`。

另将干净构建复制到最长完整路径 245 字符的隔离目录，Self-Check 得到 `22 pass / 0 fail / 2 expected warnings`：除不可分发警告外，路径门禁按设计提示迁移到 `C:\CloudFlowing` 等短目录，没有误报为运行失败。

GitHub 当前要求单个 Release 资产小于 2 GiB。这份 ZIP 超过该限制；即使后续许可闭环，也必须分卷或使用其他受控分发渠道，不能把当前归档原样上传为单个 Release 资产。

## 许可门禁

- Qwen 使用 research/noncommercial 条款，尚不能据此认定公司内部商业测试和再分发合法。
- LFM Open License 1.0 的商业资格依赖法律实体年收入低于 USD 10M；公司事实尚未确认。
- ZipVoice 完整目录包含 eSpeak 相关数据，但缺少可核验的固定版本、COPYING 与对应源代码交付；Emilia 训练数据限制也未闭环。
- 上游 Vocos 为 MIT，但当前 exact vocoder ONNX 导出没有随附足以确认再分发的许可依据。
- `news-female1`、`male1`、`female1`、`female2` 四个参考 WAV 没有录音、音色身份和再分发授权证据。

因此，“完整同事离线包”和“GitHub Release 资产”均为 blocked。本机验证成功不能覆盖上述法律门禁。

## 证据与产物边界

- 可提交 Git：应用源码、构建脚本、锁定清单、模板、测试、任务记录和不含私有路径的验证摘要。
- 不可提交 Git：GGUF、ASR/TTS 权重、参考 WAV、便携运行时、生成音频、日志、数据库、`.env` 和 ZIP。
- 当前本机目录和归档只用于验证，不可分享。归档名、字节数和 SHA256 均来自实际生成结果，但不构成再分发许可。
- 本报告只证明 Windows x64 CPU 本机链路，不代表 RK3588、RKNPU、实体音响、远场麦克风、功耗、温控或长稳验收。

## 后续动作

1. 取得 Qwen 商业内部测试/再分发授权，或改成由使用方按许可自行导入。
2. 确认公司是否满足 LFM 的 USD 10M 年收入条件并留存依据。
3. 补齐 ZipVoice/eSpeak/Emilia 与 exact vocoder ONNX 的许可证据。
4. 为四个参考音色取得明确授权，或替换为可再分发的自有录音。
5. 完成代码全量回归、VibeCollab 检查和 PR；许可闭环后以 `distributable` 模式重新生成可交付归档及 Release 资产。
