# 文本处理质量与误路由修复

- 状态：已完成（本轮质量门禁补丁）
- 日期：2026-08-07
- 基线：`main` / `ebc208f` (`fix: make CLI installation self-contained`)
- 前置任务：[`2026-08-07-three-model-affected-functional-validation.md`](2026-08-07-three-model-affected-functional-validation.md)

## 背景与目标

真实 Ollama 测试发现文本润色、总结和语气调整存在四类问题：结果被工具层加上 `【草稿】`、短文本被硬截断、带“调整为正式语气”的请求可能被误路由为知识/提醒/日程，以及模型泄露 `<FACT_n>`/`<占位符>`。本任务修复这些问题，并保留文本工具只生成内容、不执行发送的边界。

## 依据与不变量

- 模型只负责文本生成；意图、参数 Schema、权限、确认和工具执行仍由确定性模块负责。
- 文本结果不得把内部事实保护标记或模型占位符返回给用户。
- 润色/总结不能通过字符数硬截断生成结果；无法证明结果质量时返回不损坏事实的本地回退文本。
- “调整为正式语气：……”和“语气调整：……”必须在模型调用前确定路由到 `text_polish`，不能因正文出现“提醒”“日程”等词而触发其他工具。
- 文本处理不发送、不创建提醒、不创建日程。

## 验收条件

1. 润色“请尽快提交资料”不含 `【草稿】`、`<FACT_...>`、`<占位符>`，且不以明显残句结束。
2. 总结短文本不被切成半句，且不泄露内部标记。
3. 两个“调整为正式语气”示例均得到 `text_polish`，不创建提醒或日程。
4. 日期、金额、电话等受保护事实仍原样保留。
5. Mock 回归、文本工具聚焦测试和全量测试通过；真实模型复测至少验证上述质量门禁和路由结果。

## 影响范围

- `agent_platform/tools/text_processing_tool.py`
- `agent_platform/core/intent_router.py`
- `agent_platform/core/parameter_normalizer.py`（如需补充操作前缀）
- 相关文本工具、路由和 API 回归测试

## 本轮补充问题与实现

- `AgentCore` 只把实际缺少的 `operation`/`text` 视为文本必填项；模型误报 `tone`、`target_length` 不再触发“请补充缺失参数”确认阀门。
- `TextProcessingTool` 清理“所有占位符保持原样”、`ext{FACT_n}` 等提示词回显，并拒绝中文输入对应的英文或结构化乱码；质量不确定时回退原文。
- 轻松语气在模型原样回显常见短句时使用确定性中文回退，避免“目标轻松但内容不变”。
- 三模型抽样补丁：把模型固定模板输出（“润色后的文本”“总结内容”“调整后的文本”“草稿内容”）纳入 `_SCAFFOLDING_OUTPUTS` 门禁直接判为无效；`_DRAFT_PREFIX` 同时剥离“草稿内容：”前缀，避免 LFM 的模板占位句和 Qwen2.5 草拟前缀进入用户结果。

## 验证记录

- 聚焦回归：`python -m pytest -p no:cacheprovider --basetemp "$PWD\\.pytest-temp-reasonix" tests/test_tools.py tests/test_agent_api.py -q`，全部通过（含新增 scaffolding/语言漂移/轻松语气回退用例）。
- 全量回归：`python -m pytest -p no:cacheprovider --basetemp "$PWD\\.pytest-temp-reasonix" -q`，**340 项全部通过**（退出码 0）。
- 静态检查：`node --check static/app.js`、`git diff --check` 通过（仅有 CRLF 换行提示，无格式错误）。
- 真实模型抽样：本机 `qwen2.5:3b` 对三组文本复测，未再观察到占位符规则尾句、英文语气结果或轻松语气原样回显；模型仍可能生成质量一般但结构完整的草稿，工具门禁会优先保证可读性和事实安全。

## 遗留风险

- `temperature=0` 下相同模型、相同输入和相同提示词通常会得到相同输出，这是当前 Ollama 适配器的确定性配置；模型服务升级、硬件并行和非零采样仍可能带来差异。
- 三个模型的语言质量仍需按发布报告中的真实模型专项脚本持续复测；本轮不把一次抽样等同于所有模型 7/7 通过。
