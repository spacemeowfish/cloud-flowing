# Current Task

- ID: `DOCUMENT-ROUTING-BOUNDARIES-001`
- Title: `统一文档目录与意图边界优化`
- Status: `handoff`
- Owner: `ZCode`
- Next owner: `spacemeowfish/reviewer`

## Goal

将知识库和报告文件统一为一个文档来源，同时保留文件查找/打开与文档内容问答两种逻辑能力；收紧提醒、待办、日程、文本、文件、会议、知识问答和通用问答的路由边界。分类继续使用 Qwen2.5-3B 的“意图分类 -> 单工具参数提取”两阶段链路，并支持分类阶段的 `clarify`、`unsupported` 终止结果。

本任务从 `origin/main` 独立开发。PR#7（用户/开发者界面）当前仍未合并，因此本分支只接入当前 main 可承载的结果类型和文档边界，不复制 PR#7 的提交。TTS、ASR、唤醒词、RK3588 性能、真实会议室连接器和完整商业认证不在范围内。

## Acceptance scenarios

- [x] `AGENT_DOCUMENT_ROOTS` 默认包含 `data/documents` 和 `demo_documents`，旧目录配置仍兼容且新配置优先。
- [x] 统一目录中的 txt/md/docx 同时可用于文件索引和内容索引，来源带文件名与日期元数据。
- [x] `预约 A301 会议室` 路由到 `schedule_manage`，保留 location，并明确只是本地日程。（ZCode 复审修订：预约+会议室 是高置信表达，改由预路由确定性处理；无时间时走 missing_fields 确认流询问时刻，本地日程说明由工具补充。）
- [x] `查询会议室使用规则` 路由到 `knowledge_query`；不得把预约动作送进知识问答。
- [x] `查看项目周报` 返回文件候选；`项目周报中完成了什么` 走内容问答；多份未指定日期时返回澄清。（ZCode 复审修复：查询词清洗 + 文件名子序列匹配后，用户流程实测通过。）
- [x] 明确日期的项目周报回答附带对应文件名和日期；无关制度文档不得命中。（ZCode 复审修复：提问句式不再被动作词守卫误杀后实测通过。）
- [x] “提醒功能怎么用”走知识问答；“提醒我下午三点开会”创建提醒；“待办清单文件在哪”查找文件。
- [x] “总结项目周报”不得把文件名当作正文；“本周有什么会议”无真实数据时不由通用模型虚构回答。
- [x] `meeting_process` 不生成虚构路径；`clarification`/`unsupported` 正常完成，不调用工具；工具真实失败保持失败。

## Invariants

- 目录位置不决定能力类型，用户表达和模型意图决定文件索引或内容索引。
- `general_chat` 不回答本地文件、项目、会议和日程状态；`knowledge_query` 不执行创建、预约、打开、删除或修改。
- 文件访问只允许授权根目录；模型不能绕过 schema、确认、权限和结果校验。
- 本地日程不等于真实会议室锁定；不引入外部会议室连接器。
- 不把密码、密钥、Cookie、原始敏感任务内容或本机绝对路径写入日志、前端或 Git。

## Decisions

- 新配置 `AGENT_DOCUMENT_ROOTS` 为规范来源，旧 `AGENT_KNOWLEDGE_ROOTS`/`AGENT_AUTHORIZED_FILE_ROOTS` 仅做兼容回退。
- 先用现有文件名、日期、主题词筛选和 hashing/lexical 检索门禁，不引入大型向量模型。
- `clarify` 与 `unsupported` 只属于分类阶段终止结果，不注册为工具、不进入参数抽取。
- PR#7 未合并，当前分支从最新 `origin/main` 开始，避免混入用户/开发者界面提交。
- （ZCode）`knowledge_query` 的动作词守卫增加提问句式豁免：文本含“什么/哪些/如何/怎么/怎样/多少/是否/几/吗/呢”时不按动作请求拒绝。“完成了什么”类内容提问不再误杀。
- （ZCode）“预约/预订 + 会议室”前缀改由预路由到 `schedule_manage`（决策变更，修订 Codex 原先留给模型分类的设计）：该表达锚点明确；确定性参数保留 location；缺时间进入 missing_fields 确认流，安全且对 mock/真实模型行为一致。
- （ZCode）`file_open` 查询词清洗：动词包装（打开/查找/查看/看看…）必选匹配 + 尾部“文件/在哪”类后缀剥离；无动词句式（“待办清单文件在哪”）用独立定位正则。文件名匹配增加中文子序列评分，口语化查询可命中含插入词的真实文件名。
- （ZCode）语音输入在容器初始化时后台预加载 Faster-Whisper 模型（`voice.prewarm`），首次录音不再承担冷启动成本；失败静默不影响语音状态。

## Completed

- 已确认 `origin/main` 为 `f857428`，工作区干净，并创建 `codex/document-routing-boundaries`。
- 已读取项目规范、任务上下文和证据驱动开发要求。
- 上一任务 `CLI-EVALUATION-PATH-001` 的评测路径修复已在原任务记录中交接；本任务不回滚其代码。
- 已实现 `AGENT_DOCUMENT_ROOTS`、旧配置回退、统一文件/内容索引、周报日期筛选、来源文件名/日期和无关命中门禁。
- 已将 `demo_docs` 与 `demo_files` 的演示资产归并到 `demo_documents`，并让文件搜索、知识问答、会议文本使用同一组根目录。
- 已移除问号、单个名词、任意提醒/待办/日程和仅“总结”开头的宽松快速路由；分类阶段增加 `clarify`/`unsupported`，并在 AgentCore 增加能力门禁。
- 已接入前端的澄清、不支持、来源日期和本地日程说明展示。
- 已新增文档边界回归测试；全量 pytest 通过。
- （ZCode 复审）按普通用户流程实测发现 4 个验收场景不通过，已在 `zcode/routing-boundary-fixes` 分支修复：提问句式误杀、文件查询词不清洗、文件名匹配过严、预约会议室不预路由；另修复 `.env` 旧变量指向空目录导致的文档功能整体失效（本地 `.env` 已迁移，`.env.example` 已补充说明）。
- （ZCode 复审）ASR 耗时专项：实测纯转写热路径 1.81s、进程内全链路首次 5.30s、端到端（松开->文字）首次 6.84s / 热 1.83s、Ollama 生成争抢下 2.07-2.45s、麦克风打开 0.31s。20s 体感无法在当前代码复现，判定为此前旧服务进程/冷启动叠加；已增加容器启动预热，首次录音实测降至 2.10s。

## Pending

- 审查并合并 `zcode/routing-boundary-fixes`（含本任务全部修复）；PR#7 的合并仍由仓库所有者单独处理。
- 真实 Qwen2.5-3B 的会议预约参数抽取仍需后续优化（本分支未改模型链路）：无时间输入走 missing_fields 询问时刻属预期；带时间输入的 `start_text` 解析质量沿用原 Pending 记录，不计为真实模型质量验收通过。
- “提醒功能怎么用”等口语化知识问答在 lexical 检索下可能命中含关键词但不相关的制度文档（实测命中考勤制度）；属检索质量已知局限，待后续引入更强检索或由真实模型改写查询。

## Next step

审查 `zcode/routing-boundary-fixes` 的单独提交（相对 `codex/document-routing-boundaries` 仅含复审修复与测试）；合并后从最新 main 继续真实 Qwen2.5-3B 的预约参数回归，不与 PR#7 混合。

## Verification

- [x] 聚焦路由、模型 schema、知识库、Agent API 回归测试
- [x] `python -m pytest -q -p no:cacheprovider`：450 项通过（含新增 `tests/test_routing_boundary_fixes.py` 22 项）
- [x] `python -m compileall -q agent_platform evaluation deployment scripts`
- [x] `node --check agent_platform/static/app.js`
- [x] `git diff --check`
- [x] `node .ai-team/check.mjs --base origin/main`
- [x] 本机 `qwen2.5:3b` 调用计时：冷 10.37 s / 2 calls，热 0.94 s / 2 calls；仅意图可靠，预约时间参数仍需修复。（Codex 原始记录，本分支未改模型链路）
- [x] （ZCode）用户级 HTTP 全流程复测（mock，迁移后 `.env`）：会议室规则命中来源、带日期周报问答附文件名+日期、查看项目周报返回候选待确认、待办清单文件在哪直接命中文件、预约A301进入 missing_fields 询问时刻、多份周报无日期返回日期澄清、本周会议不虚构。
- [x] （ZCode）ASR 预热验证：服务启动后首次录音（松开->文字）2.10s，转写内容正确。

## Handoff note

- From: `ZCode`
- To: `spacemeowfish/reviewer`
- Summary: 复审发现 4 个验收场景用户流程不通过并已修复（提问句式误杀、文件查询清洗与匹配、会议室预约预路由、.env 漂移），另按用户要求增加 ASR 模型启动预热（首次录音 6.84s→2.10s）。450 项测试通过；决策变更（预约预路由）已在 Decisions 记录。真实模型预约参数与 lexical 检索质量仍为后续项。
