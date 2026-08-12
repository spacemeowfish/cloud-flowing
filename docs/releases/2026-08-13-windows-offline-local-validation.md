# Windows x64 离线包本机验证报告

- 日期：2026-08-13
- 任务：`PC-OFFLINE-BUNDLE-001`
- 分支：`codex/pc-offline-test-bundle`
- Git 基线：`cf0f0c35c9cf0ce98ec58b2382e11ffb03816d3c`
- 结论：`BLOCKED FOR DISTRIBUTION`

## 结论

Windows x64 CPU 上的“模型 + Agent + ASR + TTS”完整本机链路已通过真实隔离安装冒烟。Qwen2.5 和 LFM 均由包内 llama.cpp 串行加载，Faster-Whisper 完成真实转写，ZipVoice 四个音色均生成有效 WAV，停止后没有遗留监听端口。

这不是可交给同事的发布包。Qwen、LFM、ZipVoice、exact vocoder ONNX 和四个参考 WAV 仍有许可证或再分发授权缺口，因此当前构建明确标记为 `NON_DISTRIBUTABLE_LOCAL_VALIDATION`，只能留在当前所有者本机，不得分享或上传 GitHub Release。

## 构建信息

| 项目 | 记录 |
|---|---|
| 目录名 | `cloud-flowing-windows-x64-offline-local-validation` |
| 运行时源码提交 | `a08a51a17a6015daa6812d172b0ef6ea4ab9d52b`（之后的提交仅含测试夹具与本报告，不改变包内运行代码） |
| 平台 | Windows x64 CPU |
| 运行方式 | 便携 Python 3.12 + llama.cpp，本地 `127.0.0.1` 服务 |
| 模型策略 | Qwen2.5 与 LFM 串行加载，不同时驻留 |
| 干净构建目录 | `4,699` files / `3,851,008,890` bytes |
| 初始负载清单 | `4,696` files / `3,849,540,929` bytes |
| 最终 ZIP 文件名 | `cloud-flowing-windows-x64-offline-local-validation.zip` |
| 最终 ZIP 字节数 | `3,636,131,116` |
| 最终 ZIP SHA256 | `d72d50291efacc1ffb86709de7367e06bce10ab9d160cc8aa372e05da6f8b92e` |
| 包状态 | `NON_DISTRIBUTABLE_LOCAL_VALIDATION` |

以上归档三项来自实际生成和复核，不是预估值。该哈希只用于本机验证产物识别，不改变不可分发状态。

## 隔离安装冒烟

最终源码构建的真实冒烟使用全新独立安装目录，调用包内运行时和包内相对配置。归档随后解压到另一个全新独立目录，逐项复核包内哈希并重新运行自检。它证明该包不依赖项目工作区中的既有 Python 环境，但不等同于另一台全新 Windows 主机验收。

| 阶段 | 通过/总数 | 结果 |
|---|---:|---|
| Self-Check | 22/22 | 0 失败；1 条预期不可分发警告 |
| Qwen 模型与 Agent | 4/4 | 真实请求通过 |
| LFM 模型与 Agent | 4/4 | 真实请求通过 |
| Faster-Whisper ASR | 3/3 | 真实转写通过 |
| ZipVoice TTS | 6/6 | 四音色均生成有效 WAV |
| 停止清理 | 1/1 | 相关监听端口为 0 |
| ZIP 完整性 | 4,699/4,699 | 无损坏条目 |
| 解压后内容哈希 | 4,694/4,694 | `SHA256SUMS` 0 错误 |
| 解压后 Self-Check | 22/22 | 0 失败；1 条预期不可分发警告 |

模型加载日志记录 Qwen `1.680s`、LFM `0.626s`（ASR/TTS 阶段第二次 LFM 加载为 `0.622s`）。真实请求与生成耗时：Qwen 直接模型 `1.720s`、Agent `2.196s`；LFM 直接模型 `0.902s`、Agent `1.198s`；Faster-Whisper CPU INT8 转写 `3.630s`。ZipVoice 四音色分别为 `4.503s`、`12.684s`、`9.064s`、`5.426s`，均生成 24 kHz、单声道、16-bit PCM WAV。

依赖安装在包内 `runtime/packages`，构建器将最长相对路径限制为 120 字符；本次最长为 108 字符，最终深路径解压后的最长完整路径为 235 字符。真实冒烟和归档自检后均未生成 `.pyc`，防止只读运行资源被启动过程修改。

## 复核命令与证据索引

在本地不可分发包根目录执行：

```powershell
.\Accept-Licenses.ps1 -AcceptAll
.\Self-Check.ps1
.\Smoke-Test.ps1
.\Stop-Agent.ps1
```

真实冒烟副本中的相对证据路径：

- Qwen 与 LFM：`logs/smoke/qwen-model.json`、`logs/smoke/lfm-model.json`
- ASR 与 TTS：`logs/smoke/asr.json`、`logs/smoke/tts.json`
- 四音色 WAV：`logs/smoke/tts/tts-news-female1.wav`、`tts-male1.wav`、`tts-female1.wav`、`tts-female2.wav`
- 运行日志：`logs/agent-*.log`、`logs/llama-*.log`
- 构建与完整性：`BUILD-METADATA.json`、`MANIFEST.json`、`SHA256SUMS`

原始 JSON、WAV 和日志只保存在本地不可分发 `dist`，不进入 Git；本报告提交的是脱敏摘要和相对索引。

Mock 没有被当作真实模型成功。该结果仅覆盖 Windows x64 CPU 链路，不覆盖 RK3588、RKNPU、实体音响、远场麦克风、功耗、温控和长时间稳定性。

## 资产与许可结论

| 资产 | 已核验结论 | 再分发状态 |
|---|---|---|
| Python 3.12 便携运行时 | PSF 许可 | 可随符合条件的包分发 |
| llama.cpp Windows x64 CPU | MIT | 可随符合条件的包分发 |
| Faster-Whisper small | MIT | 可随符合条件的包分发 |
| Qwen2.5-3B-Instruct Q4_K_M | research/noncommercial 条款；未证明公司内部商业测试和再分发权 | 阻塞 |
| LFM2.5-1.2B-Instruct Q4_K_M | LFM Open License 1.0；商业资格依赖法律实体年收入低于 USD 10M | 条件未确认，阻塞 |
| ZipVoice 模型目录 | eSpeak 固定版本、COPYING/对应源代码义务及 Emilia 数据限制未闭环 | 阻塞 |
| exact vocoder ONNX | 上游 Vocos 为 MIT，但 exact 导出缺少随附许可依据 | 阻塞 |
| 四个参考 WAV | 无录音、音色身份和再分发授权证据 | 阻塞 |

工程验证不替代法务结论。任何阻塞资产都不能因为“本机可以运行”而自动获得分发资格。

## Git 与 Release 结论

- 工作分支已正式 rebase 到 PR #1 merge commit `cf0f0c35`，不再依赖临时传输基线。
- 源码、脚本、测试和文档可以进入同一 PR。
- 模型二进制、参考 WAV、运行时、日志、生成音频和归档不得进入普通 Git 历史。
- 当前完整本机验证包不得上传 GitHub Release，也不得发给同事。
- GitHub 当前要求每个 Release 资产小于 2 GiB；本 ZIP 为 `3,636,131,116` bytes，未来即使许可闭环也需分卷或改用其他受控分发渠道。
- 许可闭环后仍需重新构建、重新生成文件清单和 SHA256，并再次执行隔离安装冒烟，才能形成可分发候选包。

## 未解决风险

1. Qwen 商业内部测试和再分发授权尚未取得。
2. 公司是否满足 LFM 的 USD 10M 年收入条件尚未书面确认。
3. ZipVoice 所含 eSpeak/Emilia 合规材料不完整。
4. exact vocoder ONNX 的再分发依据不完整。
5. 四个参考音色缺少明确授权；应取得授权或替换为可再分发的自有录音。
6. 当前结果只在本机多个隔离目录验证，尚未在另一台全新 Windows x64 电脑进行独立验收。
