# Current Task

- ID: `SMOKE-DEMO-FIXES-001`
- Title: `人工冒烟缺陷修复（SMOKE-FIXPLAN S1-S8）`
- Status: `handoff`
- Owner: `ZCode`
- Next owner: `spacemeowfish/reviewer`

## Goal

按 `SMOKE-FIXPLAN.md`（2026-08-20，基于 556744b 与 474 项 pytest 基线）修复人工冒烟发现的 7 个演示阻塞缺陷，共 8 个修复项 S1-S8。目标是真实 ollama qwen2.5:3b desktop 演示链路逐条可用：ASR 连续转写、日程存在性查询、带修饰词文件搜索、缺参中文澄清、文件打开禁用如实反馈、知识库澄清可点选、会议纪要模糊找文件。

前置：PRE-DELIVERY-FIXES-001 已推送为 PR #9 并于 2026-08-19 以真合并（`a19f3c4`）进入 main；本任务基于 556744b 新分支 `zcode/smoke-demo-fixes`，PR #10 base 已于 2026-08-20 改为 main（smoke 分支相对 main 恰好只含本任务 10 个提交，无需清理提交栈）。旧任务归档至 `docs/tasks/2026-08-19-pre-delivery-fixes.md`。

## Acceptance scenarios

- [x] S1 闸门标题按类型区分：missing_fields 显示"请补充信息 · <字段中文名>"，candidate_confirmation 显示"请选择一个选项"，真风险确认仍显示"人工确认闸门 · R2"等；字段名有中文名映射（app.js FIELD_LABELS）。
- [x] S2 meeting_process 模糊找文件：仅主题名唯一命中→预填 source_path 并维持 R2 风险确认（确认页展示文稿名）；多命中→candidate_confirmation 闸门；0 命中→中文澄清；带绝对路径原行为不变；授权根外路径仍拒绝（工具根校验兜底）。
- [x] S3 知识库澄清候选可点击：候选变为按钮，点击回填 #consoleText 并聚焦（不自动提交）；建议问句模板 `项目周报_<8位日期> 的进展内容` 后端端到端验证。
- [x] S4 Schema 缺参转中文澄清："帮我预约下会议室"/"帮我预约一个会议室"→missing_fields 含 start_text 的中文闸门（"请补充开始时间，例如：明天下午3点"），补时间后创建成功；类型/枚举等其他 schema 错误仍诚实失败。
- [x] S5 ASR 转写追加写入：连续两段语音后输入框为两段拼接（前端行为，node --check 验证；真机双段语音待人工冒烟）。
- [x] S6 文件打开禁用如实反馈：disabled_by_configuration 时 output_summary 明确"文件打开功能当前已在配置中禁用（AGENT_FILE_OPEN_ENABLED=false），未执行系统打开"；opener 正常路径文案不变。
- [x] S7 日程查询确定性路由："帮我查一下今天有没有会议"→schedule_manage/schedule_presence_query/range=today；"今天有什么安排"仍走 schedule_arrangement_query；会议纪要/记录/通知/议程类请求不被劫持；分类提示词加正例。
- [x] S8 文件搜索零命中降级重试："这周的项目周报"剥修饰词后命中；≥3 字纯中文 bigram 兜底；裸词"周报"命中集与排序不变（降级仅作用于零命中场景）。

## Invariants

- 474 项 pytest 基线只增不减：本次 495 项全绿（+21 新增回归于 `tests/test_smoke_demo_fixes.py`，改动 2 处旧断言见 Decisions）。
- 未放松任何安全门禁：meeting_process R2 风险确认保留（唯一命中路径必过）；文件访问仍限授权根（agent_core 双查 + 工具根校验）；ASR 不自动提交；无 mock 冒充真实模型。
- FileSearchTool 复用容器内 `file_open` 活实例（经 ToolRegistry 获取，未新建第二套实例）。
- 用户可见新增文案全部中文；`schema_validator.py` 的英文文案保留给模型修复用途未改。

## Decisions

- PR #9 未合并即开工：用户 2026-08-20 明确指示实施 S1-S8（当前请求优先）。为避免单 PR 双层未合并改动，S1-S8 独立分支 `zcode/smoke-demo-fixes` + 独立 PR（base=`zcode/pre-delivery-fixes`），PR #9 合并后重定 base 到 main。
- S4 预约缺参：裸"预约（下/一下/一个/个）会议室"确定性参数**不再**把整句塞进 start_text（旧断言 `test_booking_deterministic_arguments_keep_location` 已更新），由 agent_core 的 schema 预检（`Draft202012Validator.iter_errors` 推导 required 缺项与 minLength 空串）提前转中文闸门，少一次工具往返；推导仅覆盖"必填缺失/为空"，类型/枚举/唯一性错误仍严格失败（单元测试锁定）。
- S4 预检推导遇 meeting_process 的 source_path 缺失时跳过闸门，交给 S2 的授权文件搜索兜底（避免静态闸门拦截模糊找文件）。
- S2 多命中走既有 candidate_confirmation；候选确认轮 selected_path 在 confirm() 映射回 source_path（meeting schema additionalProperties=false 需删除 selected_path）。候选确认后 confirmed=True 不再触发第二次 R2 闸门，与平台既有"单轮确认即放行"语义一致（file_open 候选流同构）；唯一命中/绝对路径路径必过 R2，安全不降级。R2 确认页新增"文稿：<文件名>"明细（MeetingNotesTool.confirmation_context）。
- S7 新确定性规则使"本周有什么会议"从"留给模型"变为确定性 schedule_manage（计划字面规则覆盖该形态）；旧边界测试 `test_ambiguous_external_schedule_is_left_for_model_classification` 改用无日期锚点的"有什么会议"保持原意。评测基线要求网关原始参数含 range，确定性参数直接携带 range=today 等（与 mock 模型输出形态对齐，60 用例基线不变）。
- mock 适配器 meeting 无路径分支由 `{"source_path": ""}`（违反抽取 schema minLength）改为合法 partial 形态 `{"arguments": {}, "missing_fields": ["source_path"]}`，与真实模型行为对齐；评测集 60 用例全部带绝对路径，不受影响。
- 测试容器配置只设 `document_roots`：同时显式设 legacy `authorized_file_roots`/`knowledge_roots` 会触发 settings 校验器用 legacy 合并值覆盖 `document_roots`（PR#7 既有语义）。
- 真实 ollama 冒烟使用独立端口 8010 + 独立主库，但 schedules/knowledge 等伴生库按 `database_path.with_name(...)` 派生规则与 desktop 实例共享了 `data/schedules.db`；冒烟插入的 1 条"会议室预约"（id 5）已精确删除，用户原有 4 条数据未动。后续冒烟如需完全隔离应把 AGENT_DATABASE_PATH 指向独立子目录。
- 2026-08-20 用户决定：PR #10 base 改为 main（PR #9 已真合并 `a19f3c4`，smoke 分支无 pre-delivery 残留提交，无需清理提交栈）；本任务后续开发内容暂不实施，未完成项整体暂缓保留（见 Pending），留到后续任务接手。

## Completed

- S1-S8 全部实现，每项独立 commit（`fix(smoke): Sx ...`，共 9 个提交含 S7 评测基线对齐修正）。
- 新增回归测试 21 项（`tests/test_smoke_demo_fixes.py`）；更新旧断言 2 处（`test_routing_boundary_fixes.py` 预约参数、`test_document_routing_boundaries.py` 模糊外部日程示例）。
- 真实 ollama qwen2.5:3b 冒烟（serve 独立实例）通过 8/9 自动化断言，唯一"失败"项系共享日程库存在今日真实日程（行为正确、断言环境不符），详见 Verification。

## Pending

- 暂缓项（2026-08-20 用户决定：后续开发内容暂不实施，留到后面做；后续任务接手时从本清单恢复）：
  - 人工冒烟剩余项：ASR 连续两段转写拼接（S5 前端，需真机麦克风）；如演示需真实打开文件，本地 `.env` 置 `AGENT_FILE_OPEN_ENABLED=true` 重启 desktop（已知 FIXPLAN D1 风险由演示负责人决定）。
  - desktop 模式全量人工冒烟清单：待 PR 合并后人工执行。
  - 澄清挂起 + resume、三闸门收敛、FIXPLAN 批次 D：按 SMOKE-FIXPLAN"范围外"另立任务。

## Next step

- 评审并合并本 PR（base 已于 2026-08-20 改为 main）；合并后剩余人工冒烟与范围外开发按用户决定整体暂缓，后续任务接手（RUOYI-AUTH-GATEWAY-001 的 TASK.md 已完整并入本清单，作为跨任务保留点）。

## Verification

- [x] `.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider`：495 项全部通过（基线 474 + 21 新增；exit 0）
- [x] `.\.venv\Scripts\python.exe -m compileall -q agent_platform evaluation deployment scripts` 通过
- [x] `node --check agent_platform/static/app.js` 通过
- [x] `node .ai-team/check.mjs --base origin/main` 通过（Result: valid）
- [x] 真实 ollama 冒烟（`MODEL_PROVIDER=ollama` + `qwen2.5:3b`，独立 serve 实例 8010 端口，逐条实测）：
  1. "帮我查一下今天有没有会议"→completed，"查询到 1 个日程实例"（共享库含今日真实"项目评审会"，返回正确；空库诚实返回见 pytest `test_presence_query_returns_honest_empty_result`）；
  2. "帮我找一下这周的项目周报"→candidate_confirmation 5 个候选（4 周报+模板，S8 降级命中）；
  3. 选候选确认→completed，output_summary="文件打开功能当前已在配置中禁用（AGENT_FILE_OPEN_ENABLED=false），未执行系统打开"（S6）；
  4. "帮我预约下会议室"→missing_fields 闸门 fields=[start_text] message="请补充开始时间，例如：明天下午3点"（S4，无英文）；补"明天下午3点"确认→completed"已创建日程"；
  5. "帮我总结下这次的项目周报"→completed 澄清 4 个日期候选（S3）；"项目周报_20260804 的进展内容"→completed sources=[项目周报_20260804.txt]；
  6. "帮我生成数据分级边界讨论稿的会议纪要"（真实 3B 分类）→awaiting_confirmation risk_confirmation，确认页含"文稿：会前材料_数据分级边界讨论稿_20260828.txt"（S2 唯一命中+R2）；确认→completed"会议纪要已生成：会前材料_数据分级边界讨论稿_20260828-会议纪要.md"。
- [ ] ASR 连续两段转写拼接（S5）：需真机麦克风人工执行
- [ ] desktop 模式全量人工冒烟清单：待 PR 合并后人工执行

## Handoff note

- From: `ZCode`
- To: `spacemeowfish/reviewer`
- Summary: SMOKE-FIXPLAN S1-S8 全部完成（8 项验收全勾），495 项 pytest 通过（+21 回归），四类静态检查通过，真实 ollama qwen2.5:3b 冒烟 6/7 条实测通过（唯一剩余为需真机的 ASR 双段转写）。分支基于 556744b；PR #9 已真合并进 main，本 PR base 已于 2026-08-20 改为 main（无需清理提交栈）。剩余人工冒烟与范围外开发按用户 2026-08-20 决定整体暂缓（见 Pending）。关键决策与偏离均记录于 Decisions（预约 start_text 行为变更、"本周有什么会议"路由边界变更、mock partial 形态对齐、冒烟共享库清理）。
