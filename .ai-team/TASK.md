# Current Task

- ID: `RUOYI-AUTH-GATEWAY-001`
- Title: `公网访问前置改造：若依认证网关`
- Status: `active`
- Owner: `ZCode`
- Next owner: `spacemeowfish/reviewer`

## Goal

按 `docs/tasks/2026-08-20-ruoyi-auth-gateway-plan.md`（计划文档，第 8 节答案已于 2026-08-20 回填）完成公网访问前置认证改造：若依（RuoYi-Vue `springboot3` 分支）统一登录门 + FastAPI JWT 闸机（未认证一律 401，白名单仅 `/health`）+ 数据按账号隔离 + 自签 HTTPS 部署包（手册+脚本交付老板执行，开发者远程支援）。Phase 0～6 全部在 Windows PC 完成并留 PC 证据；Phase 7 板端验收由部署人执行。

前置收尾：`PRE-DELIVERY-FIXES-001` 归档至 `docs/tasks/2026-08-19-pre-delivery-fixes.md`（与 PR #10 分支内容逐字节一致）。`SMOKE-DEMO-FIXES-001` 在 PR #10（base 已于 2026-08-20 改为 main）评审中，其未完成项以"前置任务暂缓项"并入本文件保留。

## Acceptance scenarios

- [x] Phase 1 本地跑通若依：JDK 17 + MySQL 8 + Redis + Node 18 环境就绪；建角色（普通角色内置、developer 新建）与测试账号（user1/dev1）经管理 API 完成并验证；真实 JWT 验签/解码/Redis 会话全链路验证（含 admin 与 user1 双账号；界面人工走查留评审，前端 8081 已可用）。
- [x] Phase 2 契约冻结：`docs/contracts/ruoyi-auth-gateway.md` 定稿（2026-08-20 附录 A 真实样本已贴入并经双模型交叉评审修正；签名算法、claims 结构、Redis key/值结构与提取路径、前端令牌存储、环境变量名全部冻结），真实 token 解码 + Redis 原始值取证完成。
- [x] Phase 3 FastAPI 闸机（2026-08-21 完成，验收证据见 Verification）：全部路由默认校验（白名单仅 `GET /health` + 静态页面资源），非法/缺失/吊销/Redis 故障统一 401 `auth_required`（fail-closed）；数据按账号隔离（userId 归属，跨设备同账号同数据）；开发者入口改判若依角色，旧环境变量密码门退役；Mock 签发器测试覆盖放行/各 401 路径与角色映射；curl 实测无 token 401、带真实若依 token 200。
- [ ] Phase 4 前端登录对接：读不到有效 token 跳若依登录页；登录后回跳进操作台，API 统一附加 `Authorization: Bearer` 头；普通用户不见控制台；登出清理并回登录页。
- [ ] Phase 5 本地全链路（Nginx 三条 location）：未登录 401/跳登录、普通用户控制台不可见且直调开发者接口被拒、developer 可用、若依禁用账号立即 401、伪造 token 401；剧本截图/录屏归档并标注为 PC 证据。
- [ ] Phase 6 部署包：`deployment/ruoyi-gateway/` 下 nginx.conf、systemd unit ×3、ARM64 安装脚本、自签证书脚本、部署手册、安全验收清单，文档走查通过。
- [ ] Phase 7 板端验收（部署人执行）：公网可达出登录页、端口收敛仅 443、认证闭环（禁用立即失效）、`free -h` 资源实测不 OOM、重启后三个 systemd 服务自动恢复、带认证链路语音冒烟；证据归档后本任务标记 `done`。
- [ ] 最终门禁：计划文档第 7 节五条安全清单（HTTPS、端口收敛、默认账号已改、防爆破、闸机纵深）全部有真实证据。

## Invariants

- 计划文档第 3 节冻结决策整体纳入本任务，不重新讨论；如确需推翻，先在本文件 Decisions 记录理由。
- 若依源码当黑盒：只改配置，不改其 Java 源码；使用最新版 RuoYi-Vue `springboot3` 分支（JDK 17 + Vue2 前端）。
- 白名单仅 `/health`；SSE、语音、文件、设置、Swagger 文档一律在登录后。
- 密钥（`token.secret` 等）走环境变量/仓库外配置，绝不进 Git（仓库既有铁律）。
- PC 开发全程监听回环地址；本任务不包含把 PC 监听改为非回环的行为变更。
- PC 证据不冒充板端结论：Phase 6 为止是 PC 证据，板端内存/性能/公网连通性只在 Phase 7 验收。
- 不提供生产可用的"关闭认证"开关；测试用 Mock 而非开关。
- 仓库命令基线（pytest / compileall / node --check）全绿才推进下一 Phase；每个 Phase 结束在本文件记录进度与证据。

## Decisions

- 2026-08-20 老板确认计划文档第 8 节 12 题答案（详见该文档回填处）：1～3 网络环境问题暂缓至部署期；板上同跑 3B 模型与若依（不挪云，Phase 7 实测，8G 不足按第 6 节预案兜底）；账户分离=数据按账号隔离；先按"普通用户 + developer"两类角色；账号手动建、不开放注册；全员必须登录；自签证书；手册+脚本交付、老板执行；上线尽快。
- 证书路线确定为自签：属第 3 节决策表内"备选路径"的选定而非推翻，Phase 6 只交付自签脚本，不再核实 ZeroSSL/acme.sh 政策。
- PR #10 base 已于 2026-08-20 改为 main（PR #9 已真合并 `a19f3c4`，smoke 分支无残留提交、无需清理）；冒烟任务后续开发按用户决定暂缓，未完成项整体并入本文件"前置任务暂缓项"，任何合并顺序下不丢失（TASK.md 冲突取本文件版本即可）。
- 2026-08-20 用户排期澄清：先开发若依相关内容（Phase 1 起），PR #10 的人工冒烟与合并测试统一延后到若依开发完成后进行；开发期间 PR #10 挂起不阻塞。
- Phase 1 环境全部采用便携 ZIP 组件（免管理员、不污染系统）：Temurin JDK 17.0.20 + MySQL 8.0.43 + tporadowski Redis 5.0.14.1 + Node 18.20.8 + Maven 3.9.9（阿里云镜像），统一放仓库外 `D:\my new work\ruoyi-env`，并建无空格联接 `D:\ruoyi-env`（路径空格会打断 mvn.cmd）；`start-env.cmd`/`stop-env.cmd` 一键启停。JDK 走清华 TUNA Adoptium 镜像（直连 ~80KB/s，镜像 7MB/s）。
- 前端改用独立仓库 `yangzongzhuan/RuoYi-Vue2`（@aa88eaa）：springboot3 分支已不内置 ruoyi-ui，官方将前端拆为 RuoYi-Vue2/Vue3 仓库且声明可任意搭配后端分支；符合冻结决策"Vue2 前端"本意，记录为事实性调整而非推翻。前端须用 Node 18（Vue CLI 4/webpack 4 与系统 Node 24 不兼容），`/dev-api` 代理 → 8080 已验证。
- jjwt 0.9.1 密钥语义（实测坐实，非推断）：`token.secret` 字符串经 base64 解码后作为 HS512 HMAC 密钥——原始字节验签不匹配、b64 解码后匹配；Phase 3 `RUOYI_JWT_SECRET` 必须同样处理。secret 用 128 字符标准 base64 字母表（避免 url-safe 字符歧义），存 `D:\ruoyi-env\secrets\`（仓库外）。
- 脚本化登录需临时关验证码时，除改 `sys_config` 外必须同时删 Redis 缓存键 `sys_config:sys.account.captchaEnabled`（CaptchaController 会预热缓存，只改库不生效）；本阶段验证后已恢复 true 并复测生效。
- 2026-08-20 契约定稿（双模型互审，评审即通过）：`docs/contracts/ruoyi-auth-gateway.md` 附录 A 贴入真实样本后定稿。关键修正与新增冻结项：
  - **数据归属由"用户名"修正为 userId**（计划文档第 3 节冻结决策的正式修正，理由：若依允许管理员改用户名，改名会使历史数据失联；userId 不可变）。
  - 401 稳定码 `auth_required`（不沿用 `http_401`）；对外不区分缺失/伪造/吊销（防探测）；Redis 故障 fail-closed。
  - **禁用 ≠ 吊销**（源码核验）：禁用只挡新登录，已登录会话保留至 TTL；唯一立即吊销路径 = 删 Redis key（强退）；Phase 5/7"禁用→立即 401"剧本必须含强退步骤。
  - SSE 鉴权冻结为前端改 fetch + ReadableStream（禁 query 参数传 token）。
  - 白名单澄清：静态页面资源（无业务数据）允许匿名 GET，供 Phase 4 跳转流程；数据/动作端点一律在门后。
  - 交叉评审修正底稿 4 处 + 1 处内部矛盾：密钥 ≥64 字节强制项归因 PyJWT（jjwt 0.9.1 无此强制）；提取路径按实测改为顶层 `username`/`userId`（getter 序列化产物）；`user.admin` 布尔字段**存在**（底稿误称没有）且为 admin 判定首选；§2"`sub` 为数据归属权威来源"与 §6 userId 修正冲突，已改为 sub 仅作用户名展示/审计来源。

- 2026-08-21 订立"会话执行约定"（见下文同名章节）：约束本任务 Phase 3～7 会话的 token 消耗（长工具输出落盘、对话只读摘要；取证样本不反复贴回对话、证据记压缩摘要+可复核指针；会话开头读本 TASK.md 全文但不整份重读契约全文）。不放松任何不变式/验收/验证要求，不约束其他任务；晋升仓库级通用规则须另行决策。
- 2026-08-21 Phase 3 落地决策：
  - owner 注入路径：`Tool.execute(arguments, context=ToolContext)` 可选参数贯穿 8 个工具；`agent_core` 以 `ToolContext(owner=task.session_id)` 注入（任务/评测/CLI 全路径自动覆盖）；`ToolExecutor` 幂等缓存键按 `owner:{owner}:{key}` 命名空间化（修复多用户同参数互吃缓存的隔离缺陷）。数据工具（todo/schedule/reminder/knowledge）缺 owner 即拒绝执行（fail loudly）。
  - 存量数据迁移：todos/schedules/reminders 加 `owner` 列（ALTER TABLE，默认 ''，对所有账号不可见）；知识库 documents/chunks 主键加 owner 维度需重建表（同语义）；开发基线数据不迁移。
  - 知识库空间语义：存储与检索按 owner 隔离；`sync_documents` 把共享授权目录索引进各账号自己的空间；admin `reindex` 导入发起者（developer）空间。周报类报告候选列表来自共享授权目录（服务器策展内容），不按 owner 隔离——按账号隔离的是"账号的知识空间"，共享目录是服务器语料；后续如需按账号上传知识再扩展。
  - `/developer` 页面路由在门后（匿名 401、user 303、developer 200）；`/developer.html` 静态文件与 `/`、`/app.js` 等页壳资源匿名可加载（契约 §5 澄清的落地形态）。
  - 提醒/日程的 Windows toast 调度回调保持全局（单机开发态产物；板端 systemd 形态无此回调），数据本身已按 owner 隔离。
  - rk3588 POC 遗留工具（`deployment/rk3588/docker/benchmark_profiles.py` 等）仍引用 `DEVELOPER_PASSWORD`（对 agent 已是惰性变量）；留待 Phase 6 部署包统一重做 rk3588 部署形态时清理，不在本 Phase 改冻结的 PoC 验收材料。

## 会话执行约定（2026-08-21 订立，仅约束本任务 Phase 3～7 会话）

为控制剩余 Phase 的会话 token 消耗，后续会话照此执行；不约束其他任务。本约定只调整会话工作方式，不放松任何不变式、验收或验证要求：

- 长工具输出（构建日志、redis-cli dump、curl 响应等）先重定向/落盘到文件，对话中只读摘要；仅当下一步需要**分析**该输出时读全量——省的是反复重贴，不省首次分析。
- 取证原始样本不反复贴回对话：样本以已入库文件（如契约附录 A）为准，读一次即可；TASK.md 证据记为压缩摘要 + 指针。指针只指向已入库文件；仓库外文件（如 `D:\ruoyi-env\secrets\*`）的关键片段须同时嵌入入库的契约/验收文档，保证评审人在其他 clone 仍可复核。
- 会话开头完整读本 TASK.md 全文（约 16KB）；**不**整份重读 `docs/contracts/ruoyi-auth-gateway.md`（约 18KB）——契约在 Phase 3 实施时通读一次，Phase 4 起只按需查对应章节。
- TASK.md 只记结论与压缩证据摘要（与 SKILL.md"不记录原始工具输出"一致），大块原文留在交付物文档（如契约附录 A）。

## Completed

- Phase 0（2026-08-20）：计划文档第 8 节答案回填并同步正文（账户分离含义、Phase 3 会话映射按账号隔离、Phase 6 证书脚本定自签）；`PRE-DELIVERY-FIXES-001` 归档补齐至 `docs/tasks/2026-08-19-pre-delivery-fixes.md`；本 TASK.md 建立；PROJECT.md 认证模型描述修订。
- Phase 1（2026-08-20）：
  - 环境：便携 JDK17/MySQL8/Redis/Node18/Maven 就绪并启动（MySQL 3306、Redis 6379）。
  - 若依源码：后端 RuoYi-Vue `springboot3`（9e3fb55）+ 前端 RuoYi-Vue2（aa88eaa）克隆至 ruoyi-env；`ry-vue` 建库（utf8mb4）导入 ry_20260417.sql + quartz.sql 共 31 表。
  - 配置：druid root/空密码；`token.secret` 换 128 字符强随机标准 base64；`token.expireTime=30` 分钟。
  - 构建：Maven BUILD SUCCESS（7 模块 1m10s），ruoyi-admin.jar 启动于 8080；前端 dev 于 8081（Node 18），登录页与 `/dev-api` 代理验证通过。
  - 账号：admin 默认密码已改强密码（旧 admin123 实测失效）；新建 developer 角色（id=100）与 user1（common）、dev1（developer）测试账号，密码存仓库外 secrets。
  - Token 全链路验证（admin + user1）：登录→三段式 JWT（header `{"alg":"HS512"}`，payload `{"sub":"<用户名>","login_user_key":"<uuid>"}`，无 exp claim）→ Python HMAC 验签（b64 解码密钥匹配）→ 带 Bearer 调 `/getInfo` 200→ Redis `login_tokens:<uuid>` 存在且 TTL=1800s → 无 token 401。
  - 验证码开关：脚本验证期间临时关闭、验证后恢复 true 并复测生效。
- Phase 2（2026-08-20）：
  - 契约文档 `docs/contracts/ruoyi-auth-gateway.md` 定稿（9 条主契约 + 附录 A 真实样本 + 附录 B 落地要点 + 变更规则）。
  - 实测取证：user1 + admin 双账号脚本登录（验证码临时关闭→取证→恢复 true 并经 `/captchaImage` 复测）；JWT 解码（header `{"alg":"HS512"}`、payload 仅 `sub`+`login_user_key`）；Redis `login_tokens:{uuid}` 原始值全文落样（user1 4294 字符、TTL 1788s；admin 身份片段）；标准库 `json.loads` 解析实测失败于 `103L` 记法（容错解析必要性实证）；带 Bearer 调 `/getInfo` 200、无 token 若依侧 HTTP 200+body code 401（两侧 401 形态差异坐实）。
  - 样本与取证文件存仓库外 `D:\ruoyi-env\secrets\phase2-*`（不入库）；契约附录 A 内嵌字节精确样本。
- Phase 3（2026-08-21）：
  - 代码：`core/ruoyi_auth.py`（验签器/只读 Redis store/FastJson2 容错解析/Authenticator，fail-closed）；`api/middleware.py` 重写为 JWT 闸机（白名单 `GET /health` + 静态页壳，401 `auth_required`）；`/auth` 只剩 `GET /auth/me`（role/username/user_id）；`DeveloperSessionService`、`/auth/developer/login`、`/auth/logout`、双 Cookie 机制、非回环密码校验、`DEVELOPER_PASSWORD` 设置项全部删除；`pyproject.toml` 核心依赖新增 `PyJWT`、`redis`。
  - 数据隔离：`ToolContext` owner 注入（接口/执行器/编排器/8 工具）；todos/schedules/reminders/知识库 owner 维度 + 迁移；幂等缓存按 owner 命名空间化；任务与语音记录随 `session_id = user:{userId}` 自动隔离。
  - 测试：新增 `tests/test_ruoyi_auth.py`（11 项：解析器真实样本/验签器含"原始字节签名必须失败"陷阱用例/settings 校验/闸机各 401 路径/角色映射/任务跨设备同数据/待办隔离/幂等 owner 隔离）+ 共享助手 `tests/ruoyi_support.py`（Mock 签发器 + 假 Redis store，session 值复刻附录 A 记法）；存量测试接入铸 token 助手（`gateway.headers()/promote/demote`）。全量 573 项通过（基线 474）。
  - 文档：ADR 0008（取代 0007）、PROJECT.md 认证模型改写为现行、`.env.example` 换 RUOYI_* 占位。
  - 中途状态（预期，Phase 4 闭环）：旧前端登录入口（已删端点）与 EventSource SSE 流暂不可用；desktop 模式打开的旧页面在无令牌时 API 全部 401。

## Phase 2 预发现（2026-08-20 已并入契约文档 `docs/contracts/ruoyi-auth-gateway.md` 定稿，以契约为准）

- JWT 本体无 exp/有效期 claim：有效期完全由 Redis key TTL 承载（expireTime 分钟）；FastAPI 侧不能依赖 exp 验证，第二步 Redis 存在性校验即有效期校验。
- 自动续期：`verifyToken` 在剩余 <20 分钟时重置 Redis TTL（滑动过期）；"禁用立即生效"测试需注意活跃用户会被续期——吊销路径是强退/删 Redis key，仅改用户状态不删会话。
- Redis value 为 FastJson2 序列化 LoginUser：含 `@type`、长整型 `103L`、`Set[...]` 记法，**非标准 JSON**——Phase 3 需容错解析（正则/定制解析器提取 userName、roles[].roleKey、admin 标志）。
- 用户名字段在标准 `sub` claim（Constants.JWT_USERNAME = Claims.SUBJECT）；前端令牌存 cookie `Admin-Token`（js-cookie，非 HttpOnly），请求附加 `Authorization: Bearer <token>`。
- 本分支 API 形态差异：`PUT /system/user/profile/updatePwd` 收 JSON body（非 query 参数）。
- 安全待办（Phase 6 清单项）：内置"普通角色"（role 2）默认携带大量系统菜单权限（user1 登录后 permissions 含 system:user:resetPwd 等），生产前必须清空其菜单绑定。

## 前置任务暂缓项（SMOKE-DEMO-FIXES-001 遗留；2026-08-20 用户排期：若依开发优先，人工冒烟与 PR #10 合并测试统一延后到本任务开发完成后进行）

- 人工冒烟剩余项：ASR 连续两段转写拼接（S5 前端，需真机麦克风）；如演示需真实打开文件，本地 `.env` 置 `AGENT_FILE_OPEN_ENABLED=true` 重启 desktop（已知 FIXPLAN D1 风险由演示负责人决定）。
- desktop 模式全量人工冒烟清单：待 PR #10 合并后人工执行。
- 澄清挂起 + resume、三闸门收敛、FIXPLAN 批次 D：按 SMOKE-FIXPLAN"范围外"另立任务。

## Pending

- Phase 4～7 未开始（逐项见 Acceptance scenarios）；Phase 4 按契约 §8/§9（SSE 改 fetch+ReadableStream、`Admin-Token` 同源读取）与计划文档 Phase 4 节实施。

## Next step

- Phase 4 前端登录对接：本地代理把若依前端与操作台置于同源；操作台启动逻辑读不到 `Admin-Token` → 跳若依登录页，登录后回跳；所有 API 请求（含 SSE，按契约 §8 改 fetch 流）统一附加 `Authorization: Bearer`；界面按角色渲染（普通用户隐藏控制台入口）；登出清理本地 token 回登录页；顺带完成旧解锁对话框等 Phase 3 遗留前端清理。

## Verification

- [x] Phase 0（2026-08-20，纯文档变更）：`node .ai-team/check.mjs --base origin/main` 通过（Result: valid）；全量 `pytest -q -p no:cacheprovider` 474 项全部通过（分支自 origin/main `a19f3c4`，无代码变更，作基线留证；系统 pytest-current 临时目录权限故障，改用 `--basetemp` 独立目录运行）。
- [x] Phase 1（2026-08-20，若依本地实例，全部实测）：Maven BUILD SUCCESS；后端 8080/前端 8081 可用；admin+user1 双账号登录→JWT 验签（HS512，b64 解码密钥匹配、原始字节不匹配）→`/getInfo` 200→Redis `login_tokens:<uuid>` TTL=1800s→无 token 401；admin 默认密码已失效；验证码已恢复开启并复测生效。浏览器界面人工走查（登录页 UI 操作、F12 肉眼观察）留待评审人执行（http://localhost:8081）。
- [ ] Phase 2 起各 Phase 验收证据逐项补录。
- [x] Phase 2（2026-08-20，全部实测）：契约附录 A 取证——user1/admin 登录（验证码关→取证→恢复 true，`GET /captchaImage` 返回 `captchaEnabled=true` 复测）；JWT 解码见 A.1（HS512、仅 `sub`+`login_user_key`）；`redis-cli KEYS/GET/TTL` 原始值落样 A.2/A.3（TTL 1788s）；`json.loads` 于 char 92（`103L`）失败实证；带 Bearer `GET /getInfo` 200（user=admin roles=['admin']）、无 token 若依侧 `[http_status=200] {"msg":"...","code":401}`。仓库检查（check.mjs/pytest 基线）见本 Phase commit 记录。
- [x] Phase 3（2026-08-21）：
  - 自动化：全量 `pytest -q -p no:cacheprovider --basetemp <独立目录>` 573 项全部通过（exit=0）；`compileall agent_platform evaluation deployment` OK；`node --check agent_platform/static/app.js` OK；`node .ai-team/check.mjs --base origin/main` Result: valid。
  - 真实实例 curl（本地若依 + uvicorn 8000，取证文件 `D:\ruoyi-env\tmp\phase3-real-verify.txt`，摘要）：无 token `GET /tasks`、`POST /tasks` 均 401 `{"code":"auth_required",...}`；`GET /health` 200（白名单）；user1 token `/auth/me` → `{"role":"user","username":"user1","user_id":100}`、`GET /tasks` 200、`POST /tasks`（UTF-8 body）201 且 `session_id="user:100"`、`/openapi.json` 403；admin token `/auth/me` → developer、`/openapi.json` 200；`redis-cli DEL login_tokens:{uuid}`（模拟强退）后同 token 立即 401；验证码全程关→恢复 true 复测。
  - 遗留说明：git-bash curl 直传中文 body 会 400（shell 编码伪象，UTF-8 文件体 201），非服务端缺陷。

## Handoff note

- From: `ZCode`
- To: `spacemeowfish/reviewer`
- Summary: Phase 0～3 完成。Phase 3（2026-08-21）：JWT 闸机中间件落地（白名单 `GET /health`+静态页壳，401 `auth_required` fail-closed，userId 数据归属，旧密码门全量退役），待办/日程/提醒/知识库加 owner 隔离与幂等缓存 owner 命名空间化；573 项测试全绿 + 真实若依实例 curl 验证通过（401/200/201/403/吊销全剧本，证据摘要见 Verification）。ADR 0008 取代 0007，PROJECT.md 认证模型已改为现行。下一动作：Phase 4 前端登录对接（契约 §8/§9，含 SSE 改 fetch 流与 Phase 3 遗留前端清理）。本地环境：`D:\ruoyi-env\start-env.cmd` 一键启停（MySQL 3306 / Redis 6379 / 后端 8080 / 前端 8081）；agent_platform 本地 `.env` 已注入 RUOYI 变量（不入库）；测试账号密码在 `D:\ruoyi-env\secrets\`。
