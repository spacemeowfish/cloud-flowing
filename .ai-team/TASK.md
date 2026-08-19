# Current Task

- ID: `SMOKE-DEMO-FIXES-001`
- Title: `人工冒烟缺陷修复（SMOKE-FIXPLAN S1-S8）`
- Status: `active`
- Owner: `ZCode`
- Next owner: `spacemeowfish/reviewer`

## Goal

按 `SMOKE-FIXPLAN.md`（2026-08-20，基于 556744b 与 474 项 pytest 基线）修复人工冒烟发现的 7 个演示阻塞缺陷，共 8 个修复项 S1-S8。目标是真实 ollama qwen2.5:3b desktop 演示链路逐条可用：ASR 连续转写、日程存在性查询、带修饰词文件搜索、缺参中文澄清、文件打开禁用如实反馈、知识库澄清可点选、会议纪要模糊找文件。

前置：PRE-DELIVERY-FIXES-001 代码已推送为 PR #9（556744b 尚未合并进 main）；本任务基于 556744b 新分支 `zcode/smoke-demo-fixes`，PR base 指向 `zcode/pre-delivery-fixes`，PR #9 合并后改 base 为 main。旧任务归档至 `docs/tasks/2026-08-19-pre-delivery-fixes.md`。

## Acceptance scenarios

- [ ] S1 闸门标题按类型区分：missing_fields 显示"请补充信息 · <字段中文名>"，candidate_confirmation 显示"请选择一个选项"，真风险确认仍显示"人工确认闸门 · R2"等；字段名有中文名映射。
- [ ] S2 meeting_process 模糊找文件：仅主题名唯一命中→预填 source_path 并维持 R2 风险确认；多命中→candidate_confirmation 闸门；0 命中→中文澄清；带绝对路径原行为不变；授权根外路径仍拒绝。
- [ ] S3 知识库澄清候选可点击：候选从静态文本变为按钮，点击回填 #consoleText 并聚焦（不自动提交）。
- [ ] S4 Schema 缺参转中文澄清："帮我预约下会议室"/"帮我预约一个会议室"→missing_fields 含 start_text 的中文闸门，补"明天下午3点"后创建成功；类型/枚举等其他 schema 错误仍诚实失败。
- [ ] S5 ASR 转写追加写入：连续两段语音后输入框为两段拼接，可整体编辑后提交。
- [ ] S6 文件打开禁用如实反馈：opener 返回 disabled_by_configuration 时 output_summary 明确说明"文件打开功能当前已在配置中禁用"，不再谎报"文件处理完成"。
- [ ] S7 日程查询确定性路由："帮我查一下今天有没有会议"→schedule_manage/query/today，空库时诚实返回今日无日程；"今天有什么安排"不回归；会议文档类请求不被新规则劫持。
- [ ] S8 文件搜索零命中降级重试："这周的项目周报"0 命中→剥修饰词后命中；≥3 字纯中文 bigram 兜底；裸词行为与排序不变。

## Invariants

- 474 项 pytest 基线只增不减（新增回归全部放 `tests/test_smoke_demo_fixes.py`）；全绿。
- 不放松任何安全门禁：meeting_process R2 风险确认保留；文件访问仍限授权根（双查）；ASR 不自动提交；不做 mock 冒充真实模型。
- 复用容器内 FileSearchTool/KnowledgeTool 活实例，不新建第二套实例。
- 用户可见文案全部中文、说人话；内部英文错误不透传给最终用户。
- `app.js` 单行压缩风格，仅行内小手术，不重排格式。
- FIXPLAN 批次 D（D1-D12）、澄清挂起+resume、三闸门收敛为范围外，不顺手改。

## Decisions

- PR #9 未合并即开工：用户 2026-08-20 明确指示实施 S1-S8（当前请求优先）。为不产生单 PR 双层未合并改动，S1-S8 独立分支+独立 PR（base=`zcode/pre-delivery-fixes`），PR #9 合并后重定 base 到 main。
- 其余决策随各 S 项实施补充。

## Completed

-（实施中，逐项 commit 记录于 Git）

## Pending

- S1-S8 实施与回归测试。

## Next step

- 按 SMOKE-FIXPLAN 建议顺序实施：S1+S5 → S6 → S8 → S4 → S7 → S2 → S3，每项单独 commit（`fix(smoke): Sx ...`）。

## Verification

- [ ] `.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider`：≥487 项全绿（474 基线 + 新增）
- [ ] `.\.venv\Scripts\python.exe -m compileall -q agent_platform evaluation deployment scripts` 通过
- [ ] `node --check agent_platform/static/app.js` 通过
- [ ] `node .ai-team/check.mjs --base origin/main` 通过
- [ ] 真实 ollama 冒烟 7 条（SMOKE-FIXPLAN"完成定义"逐条）：待代码完成后执行

## Handoff note

- From: `ZCode`
- To: `spacemeowfish/reviewer`
- Summary:（待实施完成后填写）
