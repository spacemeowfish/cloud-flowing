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
- [ ] Phase 2 契约冻结：`docs/contracts/auth-gateway.md` 定稿（签名算法、claims 结构、Redis key、前端令牌存储、环境变量名），并用真实 token 手动解码验证理解正确。
- [ ] Phase 3 FastAPI 闸机：全部路由默认校验（白名单仅 `/health`），非法/缺失/过期/吊销统一 401；数据按账号隔离（用户名为数据归属，跨设备同账号同数据）；开发者入口改判若依角色，旧环境变量密码门退役；Mock 签发器测试覆盖放行/各 401 路径与角色映射；curl 实测无 token 401、带真实若依 token 200。
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

## Phase 2 预发现（待写入契约文档 `docs/contracts/auth-gateway.md`）

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

- Phase 2～7 未开始（逐项见 Acceptance scenarios）；Phase 2 素材已齐（见"Phase 2 预发现"）。

## Next step

- Phase 2：定稿 `docs/contracts/auth-gateway.md`——请求头格式（`Authorization: Bearer`）、白名单（仅 `/health`）、401 响应格式、签名算法（HS512）与密钥语义（secret 经 base64 解码作 HMAC 密钥，实测）、claims 结构（`sub` + `login_user_key`，无 exp）、Redis key/值结构（`login_tokens:<uuid>`，FastJson2 容错解析）、续期行为（<20 分钟滑动续期）、环境变量名（`RUOYI_JWT_SECRET`、`RUOYI_REDIS_URL`）、前端 `Admin-Token` cookie；附真实 token 解码验证记录。

## Verification

- [x] Phase 0（2026-08-20，纯文档变更）：`node .ai-team/check.mjs --base origin/main` 通过（Result: valid）；全量 `pytest -q -p no:cacheprovider` 474 项全部通过（分支自 origin/main `a19f3c4`，无代码变更，作基线留证；系统 pytest-current 临时目录权限故障，改用 `--basetemp` 独立目录运行）。
- [x] Phase 1（2026-08-20，若依本地实例，全部实测）：Maven BUILD SUCCESS；后端 8080/前端 8081 可用；admin+user1 双账号登录→JWT 验签（HS512，b64 解码密钥匹配、原始字节不匹配）→`/getInfo` 200→Redis `login_tokens:<uuid>` TTL=1800s→无 token 401；admin 默认密码已失效；验证码已恢复开启并复测生效。浏览器界面人工走查（登录页 UI 操作、F12 肉眼观察）留待评审人执行（http://localhost:8081）。
- [ ] Phase 2 起各 Phase 验收证据逐项补录。

## Handoff note

- From: `ZCode`
- To: `spacemeowfish/reviewer`
- Summary: Phase 0 + Phase 1 完成。Phase 0：计划文档 12 题答案回填、TASK.md/PROJECT.md 修订、PRE-DELIVERY 归档补齐、冒烟暂缓项并入保留。Phase 1：若依本地全家桶跑通（便携组件 + RuoYi-Vue2 前端拆仓适配），admin 改密、developer 角色与测试账号建立，真实 JWT 全链路验证完成并坐实 jjwt 0.9.1 密钥语义（b64 解码）与"JWT 无 exp、Redis TTL 承载有效期"等契约关键事实（见 Phase 2 预发现）。下一动作：Phase 2 契约文档定稿。本地实例：MySQL 3306 / Redis 6379 / 后端 http://localhost:8080 / 前端 http://localhost:8081（`D:\ruoyi-env\start-env.cmd` 一键启停；测试账号密码在 `D:\ruoyi-env\secrets\`，不入库）。
