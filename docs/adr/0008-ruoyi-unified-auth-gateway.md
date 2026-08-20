# ADR 0008：若依统一认证门取代免登录页与密码门

- 状态：采纳（取代 ADR 0007）
- 日期：2026-08-21
- 任务：`RUOYI-AUTH-GATEWAY-001`（Phase 3 落地）

## 背景

产品要部署到 RK3588 板并通过公网 IP 对外服务，ADR 0007 的"免登录普通任务页 + 环境变量开发者密码"模型不具备面向公网的认证能力。老板决策：基于若依（RuoYi-Vue `springboot3`）做账户分离——账号、密码、角色全部存若依（MySQL），agent_platform 不保存任何密码，只验证若依签发的 JWT；业务数据按账号隔离。

## 决策

所有 API 访问必须持有效若依令牌（契约 `docs/contracts/ruoyi-auth-gateway.md`）：

- 两步校验：PyJWT 验 HS512 签名（secret 经 base64 解码作 HMAC 密钥，与若依 `token.secret` 共享）→ 只读查若依 Redis `login_tokens:{uuid}` 确认会话存在（JWT 无 exp，有效期完全由 Redis TTL 承载；禁用 ≠ 吊销，立即吊销 = 删 key）。闸机只读 Redis、绝不续期；Redis 不可达时 fail-closed。
- 白名单仅 `GET /health` 与静态页面资源（无业务数据的 HTML/JS/CSS 页壳）；其余端点（含 SSE、语音、设置、Swagger）未认证一律真 HTTP 401，稳定码 `auth_required`，对外不区分缺失/伪造/吊销。
- 身份：数据归属 = 不可变 userId（`session_id = user:{userId}`，跨设备同账号同数据）；developer 判定 = `user.admin`（等价 `userId == 1`）或 roleKey ∈ {admin, developer}；调用者传入的身份/角色头一律不可信。
- 数据隔离：待办、日程、提醒、知识库存储加 owner 维度（幂等缓存键同步按 owner 命名空间化）；任务与语音记录随 session_id 自动隔离。
- 退役：`DEVELOPER_PASSWORD`、`/auth/developer/login`、`/auth/logout`、浏览器/开发者 Cookie 会话机制与非回环监听密码校验全部删除；登录与登出发生在若依侧。

## 后果

- 公网形态收敛为"若依前端 + 若依后端 + agent_platform FastAPI"经 Nginx/HTTPS 单入口（后续 Phase 4～6 落地）。
- 密钥只有一把共享 `RUOYI_JWT_SECRET`（环境变量注入，绝不入库）；板端部署时重新生成。
- 若依源码保持黑盒（只改配置）；若依升级须按契约"变更规则"重新核验提取路径与样本。
- 存量 SQLite 数据迁移为 owner='' 遗留桶，对所有账号不可见（开发基线数据不迁移）。
- 旧前端登录入口与 EventSource SSE 流在 Phase 4 前暂不可用（预期中途状态）；Windows toast 提醒/日程通知仍为全局回调（单机开发态产物，板端 systemd 形态无此回调）。
- ADR 0007 的双界面结构保留（普通任务页 / 开发者控制台），但进入方式由本决策取代。

## 验证

- `tests/test_ruoyi_auth.py`：Mock 签发器（HS512 + 假 Redis + 契约附录 A 真实样本 fixture）覆盖放行/各 401 路径/角色映射/数据与幂等隔离；全量 pytest 573 项通过。
- 真实若依实例 curl：无 token 401 `auth_required`、user1 token 任务接口 200/201（`session_id=user:100`）且开发者接口 403、admin token 开发者接口 200、DEL Redis key 后同 token 立即 401（证据：TASK.md Phase 3 Verification 与仓库外取证文件 `D:\ruoyi-env\tmp\phase3-real-verify.txt`）。
