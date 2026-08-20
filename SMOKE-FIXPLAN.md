# SMOKE-FIXPLAN：人工冒烟缺陷修复计划（2026-08-20）

来源：2026-08-20 对当前分支（`zcode/pre-delivery-fixes`，commit `556744b`，474 项 pytest 基线）人工冒烟发现的 7 个缺陷，诊断已完成、未改代码。本文档是给新会话执行的自包含修改计划。

前置检查（开工前必做）：

1. 确认 `PRE-DELIVERY-FIXES-001` 对应 PR 已合并进 `origin/main`（`git log origin/main` 能看到 556744b 的内容）；未合并先走完评审，不要叠加两层未合并改动。
2. 按 `AGENTS.md` 读 `.ai-team/PROJECT.md`、`.ai-team/TASK.md`、`.ai-team/SKILL.md`。
3. 新建任务 `SMOKE-DEMO-FIXES-001`（在 `.ai-team/TASK.md` 中登记目标、验收、非目标，`Status: active`，`Owner: ZCode`），新分支 `zcode/smoke-demo-fixes`。TASK.md 更新与代码同 PR。
4. 运行环境事实（已实测，无需复查）：当前 8000 端口 desktop 进程代码为新代码；`document_roots` 含 `demo_documents`；`.env` 为 `MODEL_PROVIDER=ollama`、`qwen2.5:3b`、`AGENT_FILE_OPEN_ENABLED=false`。

通用约束：

- pytest 基线 474 项只增不减；每个 S 项配回归测试，新增测试放 `tests/test_smoke_demo_fixes.py`（一处分摊），涉及旧断言的同步更新。
- 不放松任何安全门禁：meeting_process 的 R2 风险确认保留；文件访问仍限授权根；ASR 结果仍不自动提交；不做 mock 冒充真实模型。
- 用户可见文案全部中文、说人话；内部英文错误不得再透传给最终用户。
- 复用容器内活实例（C2 教训），不得新建第二套 FileSearchTool/KnowledgeTool 实例。
- 改完跑：`.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider`、`.\.venv\Scripts\python.exe -m compileall -q agent_platform evaluation deployment scripts`、`node --check agent_platform/static/app.js`、`node .ai-team/check.mjs --base origin/main`。
- `app.js` 是单行压缩风格，改动为行内小手术，不要重排格式。

---

## 问题 → 修复项映射

| 冒烟问题 | 根因（诊断结论） | 修复项 |
|---|---|---|
| 1 ASR 二次转写覆盖前一段 | `app.js:224` 覆盖式赋值 | S5 |
| 2 "查一下今天有没有会议"被要 TXT/MD 路径 | 未命中确定性规则，3B 分类漂移到 meeting_process | S7（路由）+ S2（meeting 找文件兜底） |
| 3 "找一下周报"未找到匹配文件 | 搜索只认裸关键词，修饰词导致三关全挂 | S8 |
| 4 "预约下会议室"报英文 Schema 错误 | 路由/参数正则不对齐；缺参不澄清反而透传英文错误 | S4 |
| 5 找到文件但打不开 | `AGENT_FILE_OPEN_ENABLED=false` 且工具谎报"文件处理完成" | S6（+可选本地配置） |
| 6 "总结项目周报"选日期后卡死 | 澄清是终态、候选是静态文本、回复开新任务 | S3 |
| 7 "生成…讨论稿会议纪要"弹"确认闸门 R0" | meeting 链路不会模糊找文件；闸门标题误标 R0 | S2 + S1 |

---

## S1 闸门标题按类型区分（修"人工确认闸门 · R0"误导）

位置：`agent_platform/static/app.js:437-443`（`renderConfirmation`）。

改法：

- 标题不再无条件拼 `人工确认闸门 · ${task.risk_level}`，按 `result.type` 区分：
  - `missing_fields` → `请补充信息`
  - `candidate_confirmation` → `请选择一个选项`
  - 其余（真风险确认）→ 保留 `人工确认闸门 · ${risk_level}`
- 增加字段中文名映射表（当前只有 `when` 有映射）：`start_text→开始时间`、`end_text→结束时间`、`title→标题`、`source_path→文稿路径`、`selected_path→文件`、`query→关键词`、`text→正文`、`id→编号`。`missing_fields` 输入框 label 与后端提示消息都走该映射。

验收：missing_fields 闸门显示"请补充信息 · 开始时间"；候选闸门显示"请选择一个选项"；meeting_process 的 R2 确认仍显示"人工确认闸门 · R2"。`node --check` 通过。

## S2 meeting_process 接入文件搜索（修问题 7，兜底问题 2 后果）

位置：`agent_platform/core/agent_core.py:92-95`（`_capability_boundary` 的 meeting 分支）、`agent_platform/core/agent_core.py:318-358`（`confirm`）。

改法：

1. `_capability_boundary` 中 intent==meeting_process 且 `source_path` 缺失/无效时，不再直接返回 clarification，改为：
   - 从 `task.request_text` 提取主题词：剥掉 `帮我|请|生成|整理|一下|的|会议纪要|会议记录` 等词后取剩余最长片段作为关键词；
   - 用容器内 FileSearchTool 实例（通过工具注册表拿 `file_open` 的实例，勿新建）调 `search(keywords)`；
   - **0 命中**：维持现澄清文案"未在授权目录找到该文稿，请提供完整路径或换个说法"；
   - **唯一命中**：把 `arguments["source_path"]` 预填为该文件绝对路径，放行继续——后面仍会走既有 R2 风险确认（安全不降级），确认页展示的正是要读的文件；
   - **多命中**：转入既有 `candidate_confirmation` 闸门（`REQUIRE_CONFIRMATION`，`result={"type":"candidate_confirmation", receipt/候选列表}`），前端 radio 流零改动。
2. `confirm()` 合并参数后：若 intent==meeting_process 且 `arguments` 含 `selected_path` 而无有效 `source_path`，则 `source_path = selected_path`。
3. 文件后缀/授权根校验逻辑不动（仍在工具与边界处双查）。

测试（新增，5 例）：带绝对路径原句行为不变；仅主题名唯一命中→预填 source_path 且任务停在 R2 风险确认；多命中→candidate_confirmation 且确认后能走到纪要生成；0 命中→澄清文案；授权根外路径→仍拒绝。

验收（真实 ollama 冒烟）："帮我生成数据分级边界讨论稿的会议纪要"→唯一命中 `会前材料_数据分级边界讨论稿_20260828.txt`→一道 R2 确认→纪要生成成功。

## S3 知识库澄清改为可交互（修问题 6，本批做最小方案）

位置：`agent_platform/static/app.js:431`（澄清候选渲染）。

最小方案（仅前端）：澄清候选从静态 `<span class="source-chip">` 改为按钮；点击后把建议问句回填 `#consoleText` 并聚焦（不自动提交，保持"用户检查后再提交"约定）。建议问句模板：`项目周报_<日期> 的进展内容`（含"周报"+内容词，预路由稳定命中 knowledge_query；日期用候选里的 8 位日期）。注意 FIXPLAN D4（该直达路径未脱敏）是已记录的独立缺陷，不在本批范围，勿顺手改。

结构性方案（澄清挂起 + resume，见"范围外"）下批立项。

验收："帮我总结下这次的项目周报"→出现 4 个可点日期→点选后输入框出现完整问句→提交后返回该期周报内容摘要。

## S4 Schema 缺参转中文澄清（修问题 4）

位置：`agent_platform/core/agent_core.py:258-270`（归一化后校验段）、`agent_core.py:377-382`（missing_fields 闸门）、`agent_platform/core/parameter_normalizer.py:146-149`（`_MEETING_ROOM_BOOKING`）。

改法：

1. `parameter_normalizer.py` 预约正则与路由规则对齐：`(?:预约|预订)` 后增加可选 `(?:下|个|一下)?\s*`，使"帮我预约下会议室""帮我预约一个会议室"也能命中确定性参数（原行为仅"预约A301会议室"命中）。
2. `agent_core.py:258-270`：归一化后用 `Draft202012Validator.iter_errors` 对工具 schema 预检；校验失败时从错误推导缺失/为空的必填字段（`required` 缺项、`minLength` 且实例为空串），写入 `missing_fields`（推导不出字段的其他 schema 错误仍诚实失败）；校验通过维持现清空逻辑。这样缺 start_text 的预约在进入 `agent_core.py:396` 严格校验**之前**就转入 missing_fields 闸门。
3. 闸门消息中文化：`result` 增加 `message`（如"请补充开始时间，例如：明天下午3点"），字段名经 S1 映射显示。英文 `SchemaValidationError` 不再作为任务最终回复（`schema_validator.py:16-21` 的文案保持给模型修复用，不改）。
4. 只对"必填缺失/为空"类错误转澄清；类型错误、枚举错误等仍走诚实失败。

测试（新增 4 例）："帮我预约下会议室"→awaiting_confirmation，missing_fields 含 start_text，无英文错误文案；补"明天下午3点"确认后创建成功；"帮我预约一个会议室"同上；带完整时间的预约行为不变。检查并更新 `tests/test_parameter_normalizer.py` 中预约正则旧断言。

## S5 ASR 转写追加写入（修问题 1）

位置：`agent_platform/static/app.js:224`。

改法：`const prev=$("#consoleText").value.trim(); const t=result.transcript||""; $("#consoleText").value=prev?prev+t:t;`（中文句间不加分隔符）。仍只回填输入框、不自动提交，约定不变。

验收：连续两段语音后输入框为两段拼接，可整体编辑后提交。

## S6 文件打开禁用状态如实反馈（修问题 5 文案面）

位置：`agent_platform/tools/file_search_tool.py:113-118`。

改法：opener 返回 `process_status=="disabled_by_configuration"` 时，`output_summary` 改为"文件打开功能当前已在配置中禁用（AGENT_FILE_OPEN_ENABLED=false），未执行系统打开"，success 维持 True（任务本身诚实完成）。其余路径文案不变。更新断言"文件处理完成"的旧测试。

可选（非代码、不入库）：演示机需要真实打开时，在本地 `.env` 把 `AGENT_FILE_OPEN_ENABLED` 改 `true` 重启 desktop；`.env` 已被 gitignore。注意 FIXPLAN D1（打开无扩展名白名单）未做前，开此开关即接受该已知风险，由演示负责人决定。

## S7 补日程查询确定性路由（修问题 2 路由面）

位置：`agent_platform/core/intent_router.py:67-68`（现有 schedule_arrangement_query 规则附近）、`agent_platform/adapters/structured_response.py:217-234`（分类提示词）。

改法：

1. 新增确定性规则：请求含 `(?:今天|明天|后天|本周|下周)` 且含 `(?:有没有|有什么|有哪些)` 且含 `(?:会议|安排|日程)`，且**不含** `会议纪要|会议记录|通知|议程`（防止劫持会议文档类请求）→ `PreRouteDecision("schedule_manage", "schedule_presence_query")`。放在现有规则 67 旁、file_open/知识规则之前。
2. `parameter_normalizer`：该形态下补 `{"action":"query"}`；已有"今天→range=today"推导（`parameter_normalizer.py:492-497`）确认对 det 参数路径同样生效（`agent_core` 归一化在预路由快速路径后仍会执行）。
3. 分类提示词加一行正例：`帮我查一下今天有没有会议 -> schedule_manage`，降低未覆盖变体的 3B 漂移。

测试（新增 3 例）："帮我查一下今天有没有会议"→schedule_manage/query/today，空库时诚实返回今日无日程；"今天有什么安排"原行为不回归；"帮我生成数据分级边界讨论稿的会议纪要"不被新规则劫持。

## S8 文件搜索零命中降级重试（修问题 3）

位置：`agent_platform/tools/file_search_tool.py:67-89`（`search`）。

改法：现有三关（子串/中文子序列/整句兜底）全部零命中时，降级重试：

1. 先剥修饰词：从各 term 中移除 `这周的|这周|本周的|最近的|最新|我的|这|的` 再打分；
2. 仍零命中且 term 为 ≥3 字纯中文时，用相邻二元组（bigram）匹配：文件名包含该 term 的全部 bigram 即命中（顺序不敏感），按命中 bigram 数计分。

降级只影响零命中场景，已有命中结果的排序不变。

测试（新增 3 例，已实测基线）：`这周的项目周报` 0→命中周报文件；整句兜底场景 `帮我找一下周报`（wrapper 未剥离时）命中；裸词 `周报` 行为与排序不变。

---

## 建议实施顺序与工作量

| 顺序 | 项 | 主要文件 | 预估 |
|---|---|---|---|
| 1 | S1+S5 | app.js | 1h |
| 2 | S6 | file_search_tool.py | 0.5h |
| 3 | S8 | file_search_tool.py | 1.5h |
| 4 | S4 | agent_core.py + parameter_normalizer.py | 2.5h |
| 5 | S7 | intent_router.py + structured_response.py | 1.5h |
| 6 | S2 | agent_core.py | 3h |
| 7 | S3 | app.js | 1h |

S2 与 S4 都改 `agent_core.py`，按上表顺序做可减少行号漂移干扰（诊断行号基于 556744b，实施时以实际文件为准）。每完成一项单独 commit（`fix(smoke): Sx ...`），全部完成合并为一个 PR。

## 范围外（不在本批做，下批立项）

- 澄清挂起 + resume 机制（多轮对话闭环的根本解法；S3 只做演示级最小方案）。
- 抽取 schema 继承工具 schema 的 allOf 条件必填（`models/model_schema.py:183-187`）。
- 统一"交互请求"状态模型（missing_fields/candidate/risk 三闸门收敛）。
- FIXPLAN 批次 D（D1-D12）与"架构重构方向"仍按原计划独立推进，本计划与其不重叠。

## 完成定义

- 全部 S1-S8 实现并带回归测试；pytest 总数 ≥ 487（474 基线只增不减）且全绿。
- `compileall`、`node --check`、`node .ai-team/check.mjs --base origin/main` 通过。
- 真实 ollama 冒烟（`MODEL_PROVIDER=ollama` + `qwen2.5:3b`，desktop 模式）逐条通过：
  1. 连续两段 ASR，输入框为拼接结果；
  2. "帮我查一下今天有没有会议"→返回今日日程（空则明确说今日无日程）；
  3. "帮我找一下这周的项目周报"→返回候选列表（含 4 份周报+模板）；
  4. "帮我预约下会议室"→中文提示补充开始时间，补"明天下午3点"后创建成功；
  5. （若已本地开启 AGENT_FILE_OPEN_ENABLED）选候选后系统真实打开文件；未开启则明确提示已禁用；
  6. "帮我总结下这次的项目周报"→4 个可点日期→点选→返回该期内容摘要；
  7. "帮我生成数据分级边界讨论稿的会议纪要"→唯一文件命中→一道 R2 确认→纪要生成。
- `.ai-team/TASK.md` 勾选验收项并记录真实证据（命令+结果），与代码同 PR 交付。
