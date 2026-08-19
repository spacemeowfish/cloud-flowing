# 交付前修复计划（FIXPLAN）

> 生成于 2026-08-19，基于对 main（624f751）的全量代码审查 + 455 项 pytest 全部通过的基线。
> 本文件自包含：新会话只需读本文件 + `.ai-team/PROJECT.md` + `.ai-team/TASK.md` 即可开工，不需要原始审查对话。
> 所有行号基于当前 main，实施前若代码已变动请重新定位。

## 通用约定（每个批次都遵守）

- 分支：`zcode/pre-delivery-fixes`，从最新 `origin/main` 切出。
- 按 `.ai-team/SKILL.md` 的 repo-task-sync 流程：先把 `DOCUMENT-ROUTING-BOUNDARIES-001` 收尾（PR#8 已合并为 de844b0，验收与验证项均已勾选，可标 `done`），再新建任务 `PRE-DELIVERY-FIXES-001`（Owner: ZCode，Status: active）。代码与 `TASK.md` 进步更新放同一个 PR。
- 每批完成后运行：
  - `.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider`
  - `.\.venv\Scripts\python.exe -m compileall -q agent_platform evaluation deployment scripts`
  - `node .ai-team/check.mjs --base origin/main`
- 原则：明天交付优先。每项修完立刻加回归测试；不确定的项宁可跳到"交付后"批次，不在今晚引入大改动。
- 批次顺序：A（必须，今晚）→ B（真实模型演示才必须）→ C（强建议）→ D（交付后，可不做）。

---

## 批次 A：演示阻塞项（今晚必须）

### A1. 修复开发者会话下所有任务失败（unknown_role）【必现 bug，最高优先】

**问题**：`api/middleware.py:36` 给持有开发者 Cookie 的请求设 `role="developer"` → `api/routes.py:38` 写入任务 → `core/agent_core.py:389` 读出 → `core/policy_engine.py:51-53` 在 `config/policies.yaml` 的 `roles`（只有 `user`、`admin`）里查不到 → `PolicyDecision(allowed=False, reason="unknown_role")` → `agent_core.py:411-412` 抛 `PermissionDeniedError`，任务 FAILED。登录开发者控制台后，同一浏览器在普通任务页发的任何任务都会失败。现有 `tests/test_developer_auth.py` 是先建任务后登录，未覆盖此顺序。

**实现方法**（推荐映射法，单点改动、完整继承 admin 语义）：
1. `agent_platform/core/agent_core.py:389` 附近：
   ```python
   _POLICY_ROLE_MAP = {"developer": "admin"}
   raw_role = str(task.context.get("role", "user"))
   role = _POLICY_ROLE_MAP.get(raw_role, raw_role)
   ```
2. 动手前先 `grep -rn "PolicyContext(" agent_platform` 确认这是唯一用请求角色构造 PolicyContext 的位置（审查时已确认，但以防万一）。
3. 不要用"在 policies.yaml 加 developer 角色"的方案：`policy_engine.py:58-60` 对高风险动作还有 `rule["allowed_roles"]` 检查，yaml 方式可能在那里再次被拒；映射法一次到位。

**回归测试**（加到 `tests/test_developer_auth.py`）：登录开发者 → 保持 Cookie 再 `POST /tasks`（mock provider）→ 断言任务走到 completed 而非 failed/unknown_role。

**验收**：手动流程同样验证一遍：开服务 → 登录开发者控制台 → 回主页面发"提醒我5分钟后喝水" → 任务成功。

### A2. 提醒/日程后台调度循环加异常保护（一次 toast 失败会静默杀死全部提醒）

**问题**：`tools/reminder_tool.py:485-488` 与 `tools/schedule_tool.py:465-468` 的 `while True: await self.poll_due(); await asyncio.sleep(0.5)` 没有 try/except；`adapters/notifications.py:32-38` 的 `toast.show()`（subprocess）也未包裹。任一异常 → 调度 task 死亡 → 之后所有提醒/日程通知静默失效，且该 task 不在 `container.background_tasks` 里，异常连日志都没有。

**实现方法**：
1. 两个 `_scheduler_loop` 把 `await self.poll_due()` 包进 `try/except Exception`，用 `logging.getLogger("agent_platform.tools.reminder"/"...schedule").exception(...)` 记录后 continue。
2. `notifications.py` 的 `show()` 内部整体 try/except，失败返回错误状态而不是抛出（通知失败不应上抛）。
3. 顺手修 `reminder_tool.py:453-461`：`poll_due` 里回调按行 try/except，通知失败的那行仍执行 UPDATE 并 commit，避免崩溃回滚导致下次重复通知。

**测试**：单测构造 callback 抛异常的 ReminderTool，跑一轮 poll_due，断言：行状态已更新（不再 due）、循环未被异常打断。

### A3. `knowledge.db` 开 WAL + busy_timeout（防演示中 database is locked）

**问题**：`tools/vector_store.py:122` 是裸 `sqlite3.connect(path, check_same_thread=False)`；`api/admin_routes.py:48-71` 重建索引时开第二个连接。两个连接并发读写无 WAL 的 SQLite，超过默认 5s 即 `OperationalError: database is locked`。仓库既有模式（`schedule_tool.py:37-38`、`todo_tool.py:43-44`、`session_manager.py:64-65`）都是 WAL + busy_timeout，唯独这里漂移。

**实现方法**：连接后立即执行：
```python
conn.execute("PRAGMA journal_mode=WAL")
conn.execute("PRAGMA busy_timeout=5000")
```
WAL 是数据库文件级持久属性，对已有 data/ 下数据库安全。

**测试**：两个连接并发（一个长事务写、一个读）不抛 locked。

### A4. 演示配置决策 + TASK.md 收尾（非代码，必须做）

1. `.env` 补 `DEVELOPER_PASSWORD=<非空强密码>`——不配则开发者登录 503，管理设置/日志/文档页全部不可达。注意必须先完成 A1，否则登录后触发 unknown_role。
2. 确认演示口径：当前 `MODEL_PROVIDER=mock`（路由走确定性正则，稳定）；若要演示真实 Qwen2.5-3B，改为 `ollama`，并预留模型加载/首响时间（TASK.md 记录冷启动 ~10s）。
3. 更新 `.ai-team/TASK.md`：`DOCUMENT-ROUTING-BOUNDARIES-001` 标 `done`（PR#8 已合并，验收/验证全勾），新建 `PRE-DELIVERY-FIXES-001` 记录本计划执行进度。
4. 演示前冒烟清单：启动 desktop 模式 → 普通页过一遍八类能力 → 登录开发者控制台再回普通页发任务（验证 A1）→ 按 ASR 一次 → （若配了 ZipVoice）合成一次。

---

## 批次 B：真实模型链路健壮性（演示用 ollama 才必须，mock 演示可降级为交付后）

### B1. 放宽参数抽取的 192-token 输出上限 + 解析失败一次性重试

**问题**：`adapters/structured_response.py:39-43` 的 `effective_max_tokens` 把所有意图 schema 输出压到 `min(requested, 192)` token。参数抽取需要回显长文本（长文润色、长提问）时 JSON 被截断 → 解析失败 → `ModelError` 不可重试（`core/errors.py:19-20`）→ 任务失败。输入上限 20000 字符，远超 192 token 能回显的量。

**实现方法**：
1. 区分 schema 类型：`is_argument_extraction_schema(schema)` 为真时改用可配置上限（新设置 `AGENT_INTENT_EXTRACTION_MAX_TOKENS`，默认 512，加进 `config/settings.py` 和 `.env.example`）；分类/接受 schema 维持 192。实现上给 `effective_max_tokens` 加参数或模块常量，由 adapter 传入设置值。
2. 兜底：`core/model_gateway.py` 抽取阶段（219-231 的 repair 块）里补一条：捕获 JSON 解析类 `ModelError` 时允许原样重生成一次（不要全局改 `ModelError.retryable`，避免影响其他语义）。

**测试**：构造超长 text_polish 输入（>200 中文字符）走 mock/假 adapter 断言不再因截断失败；或单测 `effective_max_tokens` 对 extraction schema 返回 512。

### B2. 意图分类阶段补修复重试

**问题**：`core/model_gateway.py:167-177` 分类调用不在任何 try/except 里；只有抽取阶段（219-231）有 repair 循环。3B 模型在分类输出里多带 `arguments` 字段（`additionalProperties: False`，`models/model_schema.py:46-56`）一次校验失败任务即死。

**实现方法**：把分类调用套进与抽取阶段相同的 `ModelSchemaError → repair prompt → 重试一次` 模式（复用 219-231 的既有辅助逻辑）。

**测试**：假 adapter 第一次返回带多余字段的分类结果、第二次返回合法结果，断言任务成功。

### B3. 预路由确定性参数校验加回退 + `start_text` 不再复制全文

**问题**：
- `core/model_gateway.py:201-216`：预路由确定性参数的 `_validate_result` 在 repair try/except 之外，schema 不符直接抛 `ModelSchemaError`，模型根本没被咨询。
- `core/parameter_normalizer.py:429-438`：时间线索正则命中时 `start_text = request_text.strip()`（整句），超过 `tools/schedule_tool.py:84` 的 `maxLength: 200` 必挂；同理 text_polish 的 10000 上限（`tools/text_processing_tool.py:58`）对 20000 字符输入。

**实现方法**：
1. `model_gateway.py:201-216`：确定性参数校验失败时记 warning 并落入模型抽取路径（不抛出）。
2. `parameter_normalizer.py` 的 `start_text_from_request`：剥离命中的时间线索和句首命令动词（预约/预订/帮我/我要/安排…），剩余文本作为事件描述，再按 schema 上限截断（200 字符）。
3. `text_polish` 的文本参数同样在上游截断到 schema 允许长度（或在 B1 的上限内由模型回显，二选一，推荐上游截断保底）。

**测试**：>200 字符的会议室预约请求全链路（mock）成功；超长润洗文本成功。

### B4. Ollama 不可用时快速失败

**问题**：`core/model_gateway.py:100-107` fallback 只配给 rkllm/llamacpp；ollama 挂了每个非预路由请求要等 `OLLAMA_TIMEOUT_SECONDS`（默认 120s，`config/settings.py:93`）× 两次调用。连接错误标记 `retryable=True`（`adapters/ollama_adapter.py:82`）但没人重试。

**实现方法**（最小改动，不要接 mock fallback——假答案比报错更糟）：
1. `ModelGateway.generate` 对 `retryable=True` 的连接类错误同 adapter 重试 1 次。
2. 评估把 `OLLAMA_TIMEOUT_SECONDS` 默认降到 30-60s（`.env.example` 同步），演示等待体验从"数分钟挂死"变为"约 1 分钟内明确报错"。

---

## 批次 C：数据与后台任务（强建议，明天演示会点到的按钮）

### C1. WAITING_NETWORK 死局收口 + 清理死代码

**问题**：`core/task_state_machine.py:21` 定义了 `RESUME` 事件但全仓库无人触发；`core/offline_queue.py` 的 `OfflineTaskQueue` 从未实例化（仅 `core/session_manager.py:82-88` 建表）；`agent_core.py:438-447` 硬编码 `cloud_tool_available=False`，`core/edge_cloud_router.py:28-31` 在限流模式下路由到 QUEUE → 任务永久停在 `waiting_network`，重启恢复也不续。

**实现方法**：
1. `agent_core.py` 处理路由决策处：`decision == QUEUE` 时改为 `_fail`，错误信息明确写"离线且无云端能力，任务未排队"（因为当前云端本来就不存在，诚实失败优于假排队）。
2. 删除 `core/offline_queue.py` 与 `session_manager.py:82-88` 的建表语句（`IF NOT EXISTS`，老库残留表无害）。`EdgeCloudRouter` 保留但注明当前矩阵大部分不可达，交付后再决定接线或删除（见 D 批）。

**测试**：构造 `network_available=False` + 限流模式的任务，断言终态是 failed 且错误信息可读，而非 waiting_network。

### C2. 管理端重建索引复用容器内的活实例

**问题**：`api/admin_routes.py:47-71` 用 `settings.knowledge_roots` 新建了第二个 `KnowledgeBaseTool`，而容器里的活实例用的是 `settings.document_roots`（`api/container.py:59-63`）。`AGENT_DOCUMENT_ROOTS` 显式配置时两者覆盖不同根目录——重建索引重建了个和查询不一致的库。

**实现方法**：容器把 knowledge tool 暴露为属性（如 `container.knowledge_tool`），admin 路由调用它的 reindex 方法（保持 `asyncio.to_thread`）。删除 admin_routes 里的第二套构造。

**测试**：设置 `AGENT_DOCUMENT_ROOTS` 后调 admin reindex，断言索引内容来自 document_roots；配合 A3 并发查询不 locked。

### C3. 幂等缓存区分查询与创建

**问题**：`core/tool_executor.py:30-33` 缓存成功回执，键为 `sha256(arguments)`；`config/settings.py:179` TTL 默认 3600s。1 小时内说两次"提醒我30分钟后开会"，第二次直接拿第一次的回执——用户以为建了两条，实际只有一条，且回执里的时间戳是旧的。

**实现方法**（择一，推荐 1）：
1. 拆两个 TTL：查询类维持 3600s，变更类（create/update/delete/cancel/complete）用新设置 `AGENT_MUTATION_IDEMPOTENCY_TTL_SECONDS` 默认 120s——防连击足够，不吞用户的重复意图。区分依据用工具元数据里的动作类别（若无则在 tool 层给 `idempotency_key` 加 kind 前缀）。
2. 最省事：全局默认降到 300s（`.env.example` 同步说明）。

**测试**：TTL 内第二次 create 返回缓存回执（防连击语义保留）；TTL 外第二次真实执行。

### C4. 取消路径的终态与竞态守卫

**问题**：
- `api/routes.py:76-81`：取消已完成任务返回 400，应幂等成功。
- `core/agent_core.py:293-297`：`CancelledError` 处理器里 `tasks.cancel` 可能撞 `InvalidTransitionError`（任务已完成时）逃逸；任务在 `agent_core.py:159` 赋值前被取消则 `task` 未绑定 → `NameError`。`api/container.py:140-143` 的 spawn 丢弃异常，两者都被静默吞掉。

**实现方法**：
1. `agent_core.py` 的 `process`：进入 try 前 `task = None`；CancelledError 处理器里先判 `task is not None`，再 try/except `InvalidTransitionError`（终态则不转换、直接返回当前记录）。
2. `routes.py` 取消端点：任务已是终态时返回 200 + 当前记录（幂等）。
3. `container.py` 的 `spawn`：done-callback 里 `t.exception()` 非空则 `logger.exception` 记录，close() 时同样回收。

**测试**：并发"任务完成瞬间取消"不产生未处理异常；对 completed 任务调取消返回 200。

---

## 批次 D：交付后（明天之后再做，按价值排序）

| # | 问题 | 位置 | 方法摘要 |
|---|------|------|----------|
| D1 | `file_open` 可执行任意文件：索引不过滤后缀，`os.startfile` 无白名单 | `tools/file_search_tool.py:57-63`、`adapters/platform.py:31-32` | 索引与 opener 双层加文档扩展名白名单（.txt/.md/.docx/.pdf/.xlsx/.pptx/.csv…），非白名单 `PermissionDeniedError`。当前 `.env` 已关 `AGENT_FILE_OPEN_ENABLED`，无即时风险 |
| D2 | 文件名单位数日期匹配不上 | `tools/knowledge_base_tool.py:87` | 正则改 `(\d{1,2})` + `zfill(2)`；测试 `2026年5月3日周报.txt` |
| D3 | 已删除文档永久可搜索 | `knowledge_base_tool.py:66-72`、`vector_store.py:152` | sync_documents 后对比 `documents.path` 与磁盘集合，删除多余行 |
| D4 | 周报直达路径返回未脱敏原文 | `knowledge_base_tool.py:165-173` | 该分支 parse 后过 `self._classifier.classify()`，用 redacted_text 出摘要 |
| D5 | 开发者登录无防爆破 | `core/developer_auth.py`、`api/auth.py:41-48` | 内存计数：连续失败 5 次锁 30s（按用户名维度即可，本地服务） |
| D6 | `text_polish` 原文恢复绕过脱敏入审计 | `core/agent_core.py:222-231` | 比照 `confirm()`（322-324）的分类门禁：先 classify，D3 拒绝，否则用脱敏文本 |
| D7 | 客户端可控 `data_domain` 直入策略 | `models/task.py:43`、`api/routes.py:38` | API 层白名单 `{personal, public}`，非法值 422 |
| D8 | `GET /tasks` 全表扫描 | `core/session_manager.py:108-126` | TaskAPI 维护内存 session→task_id 索引（表结构不动） |
| D9 | 杂项快赢 | 多处 | 会议转写编码统一走 DocumentParser（`meeting_notes_tool.py:50`）；schedule LIKE 转义 `%_`（`schedule_tool.py:337`）；删 reminder 周期 recurrence 死变量（`reminder_tool.py:455-458`）；`.env.example` 补 5 个缺失变量（AGENT_NETWORK_AVAILABLE/AGENT_RESOURCE_MODE/AGENT_IDEMPOTENCY_TTL_SECONDS/AGENT_AUDIT_FLUSH_SIZE/AGENT_APP_ROOT）；clarify/unsupported 终态补 `audit.flush()`（`agent_core.py:185-215`）；纯空白输入在 `models/task.py` validator 拒绝 |
| D10 | 语音转写超时遗留线程 | `core/voice_input.py:262-267` | 超时后置"转写中"标志，新录音开始前 join/拒绝；低核设备防线程堆积 |
| D11 | ZipVoice `close()` 阻塞事件循环 | `adapters/zipvoice_tts.py:114-118` | 锁获取放 `asyncio.to_thread` |
| D12 | 通知/清理类小项 | `notifications.py:11-18` | 删除二次清洗的弱重复实现 |

## 架构重构方向（下个迭代立项，不要今晚做）

1. **路由规则单一事实来源**：同一套中文规则现在分散在 `intent_router.py`（预路由正则）、`parameter_normalizer.py`（归一化）、`mock_adapter.py:94-225`（第三套正则）、`structured_response.py:142-248`（prompt 文案）四处。TASK.md 里"预约时间抽取难修、lexical 检索质量难改"的根因就是这个。方向：抽一个声明式规则模块，mock 与 prompt 至少从它生成。
2. **拆 `AgentCore.process`**（`agent_core.py:157-299`，~140 行）：按"终态处理 / text_polish 特例 / 审计 / 归一化策略"拆方法；`_capability_boundary`（67-108）里的中文动词规则下沉到工具元数据。
3. **SQLite 工具基类**：reminder/schedule/todo/vector_store 四份脚手架（连接、schema、调度循环、幂等键）复制粘贴且纪律漂移（A3/P2 就是产物）。抽 `SqliteToolStore` + 共享 scheduler loop + 幂等键 helper。
4. **EdgeCloudRouter**：要么把 `local/cloud_tool_available`、`user_preference` 真正接起来，要么删掉只保留决策表，避免"宣传了不存在的能力"。
5. **删除或接线** `resource_monitor.yaml` 的 throttled 模式与 C1 的决策保持一致。

---

## 执行顺序建议（时间盒）

1. **今晚 1-2 小时**：批次 A 全部（A1 是一行映射 + 一个测试；A2/A3 各 ~30 分钟含测试）→ 提交 PR → 冒烟。
2. **若明天演示用 ollama**：加做 B1-B3（B4 可选）。演示用 mock 则 B 整体推后。
3. **明天交付后一周内**：C1-C4 → D1-D5。
4. **下个迭代**：D6-D12 + 架构重构立项（新 TASK.md，按仓库规则先写目标/验收/非目标）。

## 完成定义

- 批次 A/B/C 各自的回归测试进 `tests/`，全量 pytest 通过（当前基线 455 项，只增不减）。
- `.ai-team/TASK.md` 的 `PRE-DELIVERY-FIXES-001` 勾选对应项并记录真实验证证据（命令 + 结果）。
- 演示冒烟清单（A4.4）人工过一遍并留记录。
