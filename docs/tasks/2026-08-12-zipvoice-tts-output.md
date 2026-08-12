# ZipVoice TTS 输出接入

- 状态：PC 端完成，待 RK3588 真机验收
- 日期：2026-08-12
- 基线：`main` / `ebc208f1a84c6b383bd7b15218fbb8d792ae559a`

## 背景与目标

当前 Agent 只交付文本结果。目标是在不修改 Qwen/LFM 模型镜像的前提下，复用本机外部 ZipVoice Distill INT8 资源，为已完成任务生成 WAV，并在 Web 操作台提供播放、停止和重新生成控件。

## 非目标

- 不把 ZipVoice 注册为 Agent 意图工具，不改变现有八个业务工具及其路由。
- 不把 ZipVoice 模型复制进 Agent 仓库或 Qwen/LFM 镜像。
- 不实现麦克风、ASR、唤醒词、流式音频或交换机声卡播放。
- 本轮 PC 验证不替代 RK3588 ARM64 性能和稳定性验收。

## 架构不变量

- TTS 只消费已完成任务的最终可见文本，不读模型思考过程、原始提示词或隐藏上下文。
- 每次生成均创建新的不可猜测版本 ID；读取音频前必须再次校验任务会话。
- 停止只控制浏览器播放，不取消或改变已完成的 Agent 任务。
- TTS 未启用、依赖缺失或模型不可用时，文本 Agent 仍可启动并正常工作。
- 模型、vocoder、参考音频及其准确文本由环境变量配置，运行时从外部目录加载。

## 实施决策

1. 增加独立 `SpeechSynthesizer` 契约和 ZipVoice/sherpa-onnx 适配器。
2. 增加 TTS 输出服务，负责最终文本提取、长度门禁、串行推理、WAV 存储和旧版本清理。
3. 增加 `POST /tasks/{task_id}/speech` 与受会话保护的音频读取接口。
4. 操作台在存在可朗读文本的已完成任务下展示播放、停止、重新生成控件。
5. `sherpa-onnx` 和 `numpy` 放入可选 `tts` 依赖组，不进入现有模型镜像默认依赖。
6. 支持环境变量配置多套参考音色；当前运行清单为 `news-female1`、`male1`、`female1`、`female2`，默认 `news-female1`。
7. 支持单声道 PCM16 和 PCM24 参考 WAV，保留音频原采样率交给 ZipVoice 推理。

## 验收条件

1. 通用问答、知识问答和文本处理的完成结果可以生成有效 PCM16 WAV。
2. 第一次播放按需生成；停止后回到开头；重新生成获得新的版本 URL 并播放。
3. 未完成任务、无文本结果、跨会话和无效音频版本均被拒绝。
4. TTS 状态出现在健康和能力接口，但不改变八工具集合。
5. 聚焦测试、全量测试、JavaScript 语法、Python 编译和 `git diff --check` 通过。

## 验证记录

- 聚焦回归：`python -m pytest tests/test_speech_output.py tests/test_agent_api.py tests/test_general_chat.py tests/test_tools.py -q`，80 项通过。
- 全量回归：`python -m pytest -q`，379 项全部通过。
- 静态验证：`python -m compileall -q agent_platform`、`node --check static/app.js`、`git diff --check` 通过；Git 仅提示现有 Windows 行尾转换，不存在空白错误。
- 真实 ZipVoice 冒烟：24 kHz PCM16 WAV，目标音频 2.347 秒，输出 112,684 字节；首次模型加载加合成耗时 6.386 秒，单次 RTF 2.721。该数据仅代表当前 Windows PC。
- 独立端口 `8123` 运行时 `/health` 返回 `tts.ready=true`、`model_loaded=true`，工具数量保持 8。
- 操作台实际完成 `1+1等于多少？`，点击播放生成 1.1 秒 / 24 kHz WAV；停止后回到初始状态，重新生成后再次播放。
- 多音色扩展初版曾验证新闻女声、新闻女声 2、雷军三种音色可真实切换；2026-08-12 按新参考音频清单移除雷军和新闻女声 2，改为 `news-female1`、`male1`、`female1`、`female2`，并新增 48 kHz PCM24 参考音频读取能力。
- 四音色真实合成复测：同一短句依次生成 `news-female1`、`male1`、`female1`、`female2` 的有效 24 kHz WAV，耗时分别为 5.411、21.015、12.801、7.398 秒；新增长参考音频可用，但首次条件编码耗时明显高于原短样本。`/health` 返回四项均 `available=true`，默认 `news-female1`，无雷军音色。
- 未执行：RK3588 Linux ARM64 依赖安装、板端 RTF、峰值内存、温度、长稳和声卡播放。
