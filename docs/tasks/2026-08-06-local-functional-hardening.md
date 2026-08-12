# 无大模型本地功能实测修复

- 状态：已完成（代码修复、回归验证和发布报告已完成）
- 日期：2026-08-06
- 基线提交：`ebc208f` (`fix: make CLI installation self-contained`)

## 背景与目标

用户在未启动大模型、使用本地操作台进行实际功能测试时，反馈知识检索、文件查找、提醒、待办、日程、文本处理和会议纪要存在结果缺失、展示不可操作、参数解析错误或权限错误；同时需要明确通用任务是否只是其他模块的统一入口。本任务在保留 mock 离线能力和现有高风险确认边界的前提下，修复可复现的功能问题并输出一份验证报告。

## 用户现象

1. 知识检索始终返回未找到。
2. 文件查找始终返回未找到匹配文件。
3. 提醒内容保留完整命令前缀。
4. 创建多条提醒后查询只返回一条。
5. 提醒取消/完成只显示 ID，难以选择。
6. 清空提醒后仍能查询到一条。
7. 待办按进行中、已完成、待处理查询失败，只有查询全部可用。
8. 待办更新查询不到记录；完成/删除只显示 ID。
9. 中文大写数字导致日程创建失败；创建后查询为空；取消只能按 ID。
10. 文本处理只输出提示词，未执行处理。
11. 会议纪要报 `PermissionDeniedError`。
12. 需要说明通用任务与业务工具的关系。

## 范围与非目标

- 范围：本地 mock/无大模型路径、操作台 API 与业务工具的查询/展示/参数归一化、离线固定测试和报告。
- 非目标：本轮不声称完成麦克风、唤醒词、ASR/TTS、RK3588 板端和真实外部服务联调；不绕过高风险操作确认；不改变用户未授权的工作区数据。

## 架构不变量

- `AgentCore` 负责统一任务生命周期和路由，业务工具负责领域数据读写；通用任务不是第二套业务实现。
- 查询、更新、取消、完成必须返回可识别的业务摘要和稳定 ID，不能只返回裸 ID。
- 清空/删除后的查询结果不得包含已删除记录。
- mock 模式仍可独立运行，不依赖本地大模型；真实副作用和高风险动作继续受策略与确认控制。
- 知识库和文件搜索必须使用配置的授权根目录，不能扩大访问范围。

## 验收条件

- 为每个已复现的用户现象新增至少一个行为测试，或记录无法自动化复现的替代证据。
- 知识库、文件搜索、提醒、待办、日程、文本处理、会议纪要和通用任务均有明确的成功/失败边界。
- 本地 mock 流程可启动并完成固定回归；受影响测试和全量测试结果均记录。
- 生成 `docs/releases/2026-08-06-local-functional-hardening.md`，区分已修复、仍受环境限制和未实现能力。

## 实施记录

### 根因与处理

- 知识库/文件搜索：默认相对路径按启动进程的当前目录解析。从 `C:\Users\chunz` 启动时会指向空的同名目录；同时会议文件的授权根目录校验因此也会拒绝项目内文件。`Settings` 现在以源码 checkout 根为相对路径锚点，显式绝对路径仍保持原值。
- 提醒：mock 参数可能把整句命令写入 `text`，查询还使用了固定幂等键，导致多条记录被缓存为一条。新增命令/时间前缀清洗、中文和财务大写数字解析（含每周中文时刻）、动态查询幂等键，并让删除/完成结果返回业务摘要。
- 待办：状态中文别名未统一，更新句式可能被离线适配器识别成查询。新增状态归一化、按 ID 更新和可读 item 输出。
- 日程：中文大写数字、结束时间和标题附加表单字段未可靠拆分；标题查询被默认时间范围限制。新增数值解析、结束/地点/提前提醒提取和标题候选查询模式。
- 文本：mock 工具此前返回了内部操作提示。现在按操作执行确定性的离线处理；本地模型下 D1/D2 文本恢复原始 payload，D3 仍执行脱敏和禁止持久化边界。
- 会议：授权路径以错误的运行目录为根，触发 `PermissionDeniedError`。路径解析修复后项目授权根可用，越权路径仍拒绝。
- 通用任务：没有新增第二套业务逻辑；`AgentCore` 统一执行理解、校验、策略、路由、确认、工具执行和审计，七个领域工具各自负责数据读写。

### 改动文件

核心实现：

- `agent_platform/config/settings.py`
- `agent_platform/adapters/mock_adapter.py`
- `agent_platform/core/parameter_normalizer.py`
- `agent_platform/core/intent_router.py`
- `agent_platform/core/agent_core.py`
- `agent_platform/core/model_gateway.py`
- `agent_platform/tools/reminder_tool.py`
- `agent_platform/tools/todo_tool.py`
- `agent_platform/tools/schedule_tool.py`
- `agent_platform/config/policy_rules.yaml`

操作台与测试：

- `static/app.js`、`static/styles.css`：结构化结果卡片、字段摘要和提醒/待办/日程快捷操作。
- `tests/test_local_resource_paths.py`
- `tests/test_local_reminder_todo_schedule.py`
- `tests/test_tools.py`、`tests/test_agent_api.py`
- 删除结果卡片会抑制已失效记录的快捷按钮，避免用户对已删除提醒/待办再次发起操作。

### 验证结果

- `python -m pytest -q --tb=short`：327/327 通过。
- `python -m pytest tests/test_agent_api.py tests/test_local_reminder_todo_schedule.py tests/test_tools.py tests/test_parameter_normalizer.py tests/test_local_resource_paths.py -q --tb=short`：84/84 通过。
- `agent-platform evaluate --mode mock --detailed --cases evaluation/test_cases --output work/local-functional-mock-evaluation.json --expected-total 60`：顶层意图/参数/工具/Schema 均 100%，`failures=[]`。详细评估为 `semantic_adjudicated_accuracy=100%`、`semantic_coverage=96.67%`、`end_to_end_accuracy=96.67%`；`file-08`、`file-09` 仅因评测用例没有 `expected_arguments` 而标记 `needs_review`，两条 pipeline 均已执行。
- `python -m compileall -q agent_platform`、`node --check static/app.js`、`git diff --check`：通过；末项只有 Git 的换行提示，无空白错误。
- 从 `C:\Users\chunz` 以独立端口启动服务验证：能力元数据中的知识/文件根指向本 checkout；知识查询返回产品保修政策并含“两年”；文件查询返回 3 个候选；会议纪要在确认后完成。独立服务已停止，未触碰现有 8000 进程。
- 操作台浏览器验证覆盖桌面和 390px 移动视口；移动页 `scrollWidth=375`、`clientWidth=375`，无横向溢出。验证使用 mock，不代表真实模型或音频链路质量。
- 收尾服务已用项目代码在 8000 端口以 mock 模式启动，`/health` 返回 `status=ok`；UTF-8 知识查询命中产品保修政策，测试提醒已取消。

### 遗留风险与运行前提

- 修改后的路径配置在进程启动时加载；现有 8000 服务必须重启后才生效。请先确认没有未保存的测试数据，再按发布报告中的命令重启。
- `AGENT_FILE_OPEN_ENABLED=false` 时只做授权范围内搜索和候选确认，不会真的打开桌面文件；真实通知弹窗、麦克风、唤醒词、ASR、TTS、RK3588/RKLLM、Ollama/云模型质量、外部连接器和长稳并发未在本任务中验证。
- mock 文本处理是可重复的离线兜底，不等价于模型润色质量。日程取消/待办删除为 R2，清空全部提醒为 R3，仍需确认；提醒完成/取消为 R1。标题操作先列候选，不能声称可以无确认地按自然语言删除。
- 本地知识检索是轻量关键词/Hashing n-gram 召回，不等价于高质量语义 RAG。

### Git 证据

- 基线分支：`main`；基线提交：`ebc208f`。
- 本任务未创建提交，工作区保留上述实现、测试、任务记录和报告改动，便于继续审阅和由用户决定提交时机。
