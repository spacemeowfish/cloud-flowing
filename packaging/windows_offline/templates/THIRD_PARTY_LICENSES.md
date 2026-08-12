# 第三方资产与再分发状态

本文件是工程门禁摘要，不替代法律意见。精确哈希、版本和构建模式见
`BUILD-METADATA.json` 与 `config/assets.lock.json`。

| 资产 | 固定版本/来源 | 许可证 | 本包结论 |
|---|---|---|---|
| CPython embeddable | 3.12.10, python.org | PSF-2.0 | 允许 |
| llama.cpp CPU | b10375, ggml-org/llama.cpp | MIT | 允许 |
| Qwen2.5-3B GGUF | `cc1e68e...`, Qwen HF | qwen-research | 阻塞：商业内部测试再分发权未建立 |
| LFM2.5-1.2B GGUF | `012803c...`, LiquidAI HF | LFM 1.0 | 有条件：须由公司确认适用实体/营收条件 |
| Faster-Whisper small | `536b066...`, Systran HF | MIT | 允许 |
| ZipVoice 完整模型目录 | sherpa-onnx 发布归档 | mixed/incomplete | 阻塞：eSpeak 源码/NOTICE 与 Emilia 训练数据边界未闭合 |
| vocos ONNX | k2-fsa 发布资产 | 上游 MIT，精确导出未随附许可 | 有条件：须提供该导出权利证明 |
| 四个参考 WAV | 用户本机文件 | 未验证 | 阻塞：不得凭本构建器转授权 |

官方证据：

- Qwen: https://huggingface.co/Qwen/Qwen2.5-3B-Instruct/blob/aa8e72537993ba99e69dfaafa59ed015b17504d1/LICENSE
- LFM: https://huggingface.co/LiquidAI/LFM2.5-1.2B-Instruct-GGUF/blob/012803cf70d6cdcf698f0c65fa8f9b7175128770/LICENSE
- Faster-Whisper: https://huggingface.co/Systran/faster-whisper-small/tree/536b0662742c02347bc0e980a01041f333bce120
- ZipVoice ONNX 历史文件: https://huggingface.co/k2-fsa/ZipVoice/tree/2fe18de429ca87690bd6e042bf8de5dbac7a69ec
- Emilia 数据说明: https://huggingface.co/datasets/amphion/Emilia-Dataset/blob/main/README.md
- eSpeak NG: https://github.com/espeak-ng/espeak-ng
- Vocos 上游: https://huggingface.co/charactr/vocos-mel-24khz
- llama.cpp: https://github.com/ggml-org/llama.cpp/releases/tag/b10375
- CPython: https://www.python.org/downloads/release/python-31210/

Python wheel 自带的 `*.dist-info/LICENSE*` / `licenses/` 文件保留在
`runtime/python/Lib/site-packages`。Faster-Whisper 的包内补丁见
`PATCHES.md`，PyAV 不在本包中。

包内 `licenses/` 目录提供 Qwen Research License、LFM Open License 1.0、
llama.cpp MIT、Faster-Whisper MIT 和 OpenAI Whisper MIT 的固定离线快照；
`licenses/SOURCE-MANIFEST.md` 记录精确来源与修订，
`licenses/BLOCKED-NOTICE.md` 记录这些许可文本尚未解决的分发缺口。
离线快照的存在不代表 Qwen、ZipVoice、vocoder 或参考 WAV 已获得分发授权。
