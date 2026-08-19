# 统一文档目录与意图边界优化（归档）

- 任务：`DOCUMENT-ROUTING-BOUNDARIES-001`
- 状态：`done`
- 日期：2026-08-19 归档（开发期 2026-08 上旬至 2026-08-16）
- 合并记录：PR#8 merge commit `de844b0`（分支 `zcode/routing-boundary-fixes`，含 PR#7 合并后 rebase 与三处冲突解决）
- 后续任务：`PRE-DELIVERY-FIXES-001`（见 `.ai-team/TASK.md`）

## 目标

将知识库和报告文件统一为一个文档来源，同时保留文件查找/打开与文档内容问答两种逻辑能力；收紧提醒、待办、日程、文本、文件、会议、知识问答和通用问答的路由边界。分类使用 Qwen2.5-3B 的“意图分类 -> 单工具参数提取”两阶段链路，支持 `clarify`、`unsupported` 终止结果。

## 验收（全部通过，证据见下）

- `AGENT_DOCUMENT_ROOTS` 默认包含 `data/documents` 和 `demo_documents`，旧目录配置兼容且新配置优先。
- 统一目录中的 txt/md/docx 同时可用于文件索引和内容索引，来源带文件名与日期元数据。
- `预约 A301 会议室` 预路由到 `schedule_manage`，保留 location，缺时间进入 missing_fields 确认流。
- `查询会议室使用规则` 路由到 `knowledge_query`；预约动作不进入知识问答。
- `查看项目周报` 返回文件候选；`项目周报中完成了什么` 走内容问答；多份未指定日期返回澄清。
- 明确日期的项目周报回答附文件名和日期；无关制度文档不命中。
- “提醒功能怎么用”走知识问答；“提醒我下午三点开会”创建提醒；“待办清单文件在哪”查找文件。
- “总结项目周报”不把文件名当正文；“本周有什么会议”无真实数据不虚构。
- `meeting_process` 不生成虚构路径；`clarification`/`unsupported` 正常完成；工具真实失败保持失败。

## 决策

- `AGENT_DOCUMENT_ROOTS` 为规范来源，旧 `AGENT_KNOWLEDGE_ROOTS`/`AGENT_AUTHORIZED_FILE_ROOTS` 仅兼容回退。
- 先用文件名、日期、主题词筛选和 hashing/lexical 检索门禁，不引入大型向量模型。
- `clarify` 与 `unsupported` 只属于分类阶段终止结果，不注册为工具。
- `knowledge_query` 动作词守卫增加提问句式豁免（什么/哪些/如何/怎么/怎样/多少/是否/几/吗/呢）。
- “预约/预订 + 会议室”前缀由预路由确定性处理（决策变更，锚点明确；确定性参数保留 location）。
- `file_open` 查询词清洗：动词包装必选匹配 + 尾部后缀剥离 + 中文子序列评分。
- 语音输入容器初始化时后台预加载 Faster-Whisper（`voice.prewarm`），首次录音冷启动 6.84s→2.10s。

## 验证证据

- `python -m pytest -q -p no:cacheprovider`：455 项全部通过（含 `tests/test_routing_boundary_fixes.py` 22 项）。
- `python -m compileall -q agent_platform evaluation deployment scripts`、`node --check agent_platform/static/app.js`、`git diff --check`、`node .ai-team/check.mjs --base origin/main` 通过。
- 本机 `qwen2.5:3b` 调用计时：冷 10.37s / 2 calls，热 0.94s / 2 calls。
- 用户级 HTTP 全流程复测（mock）：会议室规则命中来源、带日期周报问答附文件名+日期、查看项目周报返回候选、待办清单文件在哪直接命中、预约 A301 询问时刻、多份周报日期澄清、本周会议不虚构。
- ASR 预热验证：服务启动后首次录音（松开→文字）2.10s，转写正确。
- PR#7 合并后集成验证：455 项 pytest 与双角色界面（匿名 403/错误密码 401/登录 200/登出后 403）共存正常。

## 遗留（转入后续任务）

- 真实 Qwen2.5-3B 会议预约参数抽取质量与 lexical 检索质量为已知局限，进入 `PRE-DELIVERY-FIXES-001` 批次 B 范围。
