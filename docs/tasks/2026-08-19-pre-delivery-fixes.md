# Current Task

- ID: `PRE-DELIVERY-FIXES-001`
- Title: `交付前修复（FIXPLAN 批次 A/B/C）`
- Status: `handoff`
- Owner: `ZCode`
- Next owner: `spacemeowfish/reviewer`

## Goal

按 `FIXPLAN.md`（生成于 2026-08-19，基于 main 624f751 与 455 项 pytest 基线）执行交付前修复：批次 A（演示阻塞项）、批次 B（真实 ollama qwen2.5:3b 链路健壮性，用户已确认演示使用 ollama qwen2.5 3B）、批次 C（数据与后台任务）。批次 D 与架构重构不在本任务范围。

前置收尾：`DOCUMENT-ROUTING-BOUNDARIES-001` 已按 PR#8（de844b0）合并结果标记 `done`，归档至 `docs/tasks/2026-08-19-document-routing-boundaries.md`。

## Acceptance scenarios

- [x] A1 开发者 Cookie 下发任务不再 `unknown_role` 失败：`_POLICY_ROLE_MAP` 将 developer 映射为 admin 策略语义（单点：`agent_core.py` 构造 PolicyContext 处）。
- [x] A2 提醒/日程 `_scheduler_loop` 对 poll 异常记日志并继续；toast `show()` 失败回退 console 不上抛；`poll_due` 回调按行 try/except，失败行仍 UPDATE+commit 不重复通知。
- [x] A3 `SQLiteVectorStore` 连接后执行 `PRAGMA journal_mode=WAL` 与 `busy_timeout=5000`，管理端重建索引与查询并发不再 locked。
- [x] A4 演示配置：`.env` 切换 `MODEL_PROVIDER=ollama`、`MODEL_NAME=qwen2.5:3b`、`OLLAMA_TIMEOUT_SECONDS=60`、补 `DEVELOPER_PASSWORD`（本地文件，不入 Git）；`.env.example` 同步新变量说明。
- [x] B1 参数抽取阶段输出上限由 192 放宽到可配置 `AGENT_INTENT_EXTRACTION_MAX_TOKENS`（默认 512，仅对 argument-extraction schema 生效，分类/接受 schema 维持 192）；抽取阶段非重试 `ModelError`（截断 JSON）原样重生成一次。
- [x] B2 意图分类阶段增加 `ModelSchemaError -> 修复 prompt -> 重试一次`（新增 `_classification_repair_message`，修复输出多余 arguments 字段等 3B 常见漂移）。
- [x] B3 确定性预路由参数校验失败时记 warning 并回退模型抽取（不再直接抛 `ModelSchemaError`）；`start_text_from_request` 不再复制整句（见 Decisions 偏离说明）；text_polish 文本上游按 schema 上限 10000 截断。
- [x] B4 `ModelGateway.generate` 对连接类可重试错误（非超时/限流/忙）同 adapter 重试 1 次；`OLLAMA_TIMEOUT_SECONDS` 默认 120→60。
- [x] C1 路由 QUEUE 决策改为诚实失败（错误信息“离线且无云端执行能力，任务未排队”），不再进入永久 `waiting_network`；删除 `core/offline_queue.py` 与 `session_manager` 的 offline_queue 建表。
- [x] C2 管理端 `/admin/knowledge/reindex` 复用容器内活实例（`container.knowledge`，其 roots 为 `document_roots`），删除第二套构造。
- [x] C3 幂等缓存区分查询与变更：新设置 `AGENT_MUTATION_IDEMPOTENCY_TTL_SECONDS`（默认 120s）；reminder/schedule/todo 变更类 `idempotency_key` 加 `mutation:` 前缀；读取类维持 3600s。
- [x] C4 取消终态任务返回 200 + 当前记录（幂等）；`AgentCore.process` 的 CancelledError 处理器加 task-unbound 与 `InvalidTransitionError` 守卫；`container.spawn` done-callback 记录后台任务异常日志。

## Invariants

- 默认 PC 模型仍为 `qwen2.5:3b`（ollama 本机 digest `357c53fb659c`，与历史报告一致）。
- 确定性代码继续负责 Schema、授权、数据分级、确认、执行、幂等、取消、审计；B 批只增加模型调用的容错与预算，不放松任何 Schema 校验。
- 不引入 mock fallback 冒充真实模型（B4 明确不做假答案回退）。
- 不把密码、Cookie 或本机绝对路径写入 Git（`.env` 已被 ignore，密码仅本地）。
- 455 项 pytest 基线只增不减；本次全量 474 项通过（+20 新增回归、−1 离线队列死代码测试）。

## Decisions

- A1 采用映射法（`_POLICY_ROLE_MAP = {"developer": "admin"}`）而非在 policies.yaml 增加 developer 角色：后者会在高风险动作 `allowed_roles` 检查处再次被拒。
- B3 `start_text` 偏离 FIXPLAN 字面方案：FIXPLAN 建议剥离时间线索后用剩余文本作 start_text，但 `schedule_tool` 只解析 `start_text` 的时间表达式，剥离会导致工具无法解析开始时间、所有带时间预约退化为询问时刻。实现改为：命中的时间线索本身作为 `start_text`（天然短、可解析、≤200），剩余文本剥离命令动词后仅在 title 为空时作 `title` 兜底（`schedule_manage.title_from_request`）。两个旧断言“整句复制”的测试已按新行为更新。
- B4 只重试连接类错误（排除超时/限流/忙），避免超时重试让演示等待时间翻倍。
- C3 变更识别用工具 `idempotency_key` 的 `mutation:` 前缀约定（计划中的兜底方案），未扩展 ToolMetadata 结构。
- A1 回归测试放在新文件 `tests/test_pre_delivery_fixes.py`（与 FIXPLAN 建议的 test_developer_auth.py 等价覆盖，避免两处维护同一场景）。
- `AGENT_DOCUMENT_ROOTS` 语义保持：构造参数显式传 legacy roots 时仍按原设计合并回退，环境变量始终优先（C2 测试用 monkeypatch.setenv 表达该语义）。

## Completed

- 批次 A（A1-A4）、批次 B（B1-B4）、批次 C（C1-C4）全部实现，含回归测试 `tests/test_pre_delivery_fixes.py` 20 项。
- 同步更新：`tests/test_model_gateway.py`（B1 行为变更：截断 JSON 重试一次后仍失败才报错）、`tests/test_parameter_normalizer.py`（B3 start_text 新行为）、`tests/test_policy_routing.py`（删除 offline_queue 测试）。
- `.env.example` 新增/更新：`AGENT_INTENT_EXTRACTION_MAX_TOKENS`、`AGENT_MUTATION_IDEMPOTENCY_TTL_SECONDS`、`AGENT_IDEMPOTENCY_TTL_SECONDS` 说明、`OLLAMA_TIMEOUT_SECONDS=60`。

## Pending

- 批次 D（D1-D12）与架构重构方向：交付后按 FIXPLAN 价值排序另立任务。
- 人工冒烟清单（A4.4）剩余项：desktop 模式普通页过八类能力、ASR 按一次、ZipVoice 合成一次（服务端任务链路已由脚本冒烟覆盖）。
- 真实 ollama 演示冷启动预留 ~10s（TASK 历史记录 qwen2.5:3b 冷 10.37s/热 0.94s）；建议演示前预热一次。3B 分类对无锚点问句（如“珠穆朗玛峰有多高”）可能落入知识问答，演示通用问答建议使用“什么是/为什么”句式（确定性预路由）。

## Next step

- 审查并合并本 PR；合并后按 A4.4 清单人工冒烟（演示用 `.env` 已配置：ollama qwen2.5:3b + DEVELOPER_PASSWORD，密码在本地 `.env`，不入库）。
- 反馈验收意见后由 ZCode 继续修订（用户约定：优化完成后由用户验收给反馈再修改）。

## Verification

- [x] `.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider`：474 项全部通过（基线 455 + 20 新增 − 1 删除；exit 0）
- [x] `.\.venv\Scripts\python.exe -m compileall -q agent_platform evaluation deployment scripts` 通过
- [x] `node .ai-team/check.mjs --base origin/main`（TASK.md 与代码同 PR 更新后通过；本次会话首次运行为 blocked，系 TASK.md 尚未提交所致，已随本提交修复）
- [x] 本机 `ollama list` 确认 `qwen2.5:3b`（357c53fb659c）已就绪
- [x] 真实 ollama 冒烟（`agent_platform.cli serve` + `.env` 演示配置，脚本 `scripts/smoke_ollama_demo.py`，密码从环境读取）：健康检查 ok/ollama；预路由提醒（5分钟后喝水）完成；真实模型日程“明天下午3点开项目评审会”完成并正确创建 2026-08-20T15:00+08:00、标题“项目评审会”（历史 Pending 的预约时间参数问题在本次 B 批修复后实测通过）；通用问答“什么是人工智能”真实模型回答正常、“1+1等于多少”确定性回答正常；开发者登录（200）后同 Cookie 发提醒任务 completed（A1 实测）；completed 任务取消返回 200/completed（C4 实测）。“珠穆朗玛峰有多高”被 3B 分入知识问答返回未命中（分类质量已知局限，任务诚实完成，非本次回归；演示用“什么是…”句式可稳定走通用问答）。
- [ ] 人工冒烟清单其余项（desktop 模式八类能力、ASR 按一次、ZipVoice 合成一次）：待本 PR 合并后人工执行并补记录

## Handoff note

- From: `ZCode`
- To: `spacemeowfish/reviewer`
- Summary: FIXPLAN 批次 A/B/C 全部完成（A1 developer 角色映射、A2 调度与通知异常保护、A3 WAL、A4 演示配置；B1-B4 模型链路容错；C1-C4 死局/重建索引/幂等/取消守卫），`.env` 已切换 ollama qwen2.5:3b 并配置开发者密码（本地）。474 项 pytest 通过。B3 start_text 按工具解析语义做了等效偏离（见 Decisions）。批次 D 与人工冒烟待交付后/合并后执行。

## Archive note

- 归档时间：2026-08-20（SMOKE-DEMO-FIXES-001 开工时）。代码工作已全部完成并推送为 PR #9（`zcode/pre-delivery-fixes` → main），状态保持 handoff，等待评审合并。剩余人工冒烟验收被 2026-08-20 冒烟发现的 7 项缺陷部分覆盖，缺陷修复由后续任务 SMOKE-DEMO-FIXES-001 承接。
