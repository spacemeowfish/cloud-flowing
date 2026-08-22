# 若依认证网关对接契约

- 任务：`RUOYI-AUTH-GATEWAY-001`（公网访问前置改造：若依认证网关）
- 阶段：**已定稿**（2026-08-20。附录 A 真实样本已贴入；经第二模型源码级交叉评审，修正 4 处：§1 密钥长度强制项归因 PyJWT、§4 提取路径按实测样本改顶层 `username`/`userId` 且 `user.admin` 布尔字段存在、§5 补静态页面资源澄清、附录 A 落样）
- 用途：本文件是 agent_platform（FastAPI 闸机）接入若依账户体系的**唯一契约**。Phase 3（FastAPI 闸机中间件）、Phase 4（前端登录对接）、Phase 5（Nginx 全链路）开发必须按本文件执行，不得凭经验或网上的若依教程另立事实。
- 冻结基线：RuoYi-Vue `springboot3` 分支（后端 3.9.2、jjwt 0.9.1、fastjson2、Vue2 前端 RuoYi-Vue2）。本契约全部事实来自该版本**源码核验 + Phase 1 实测**；若依升级版本后必须按文末"变更规则"重新核验本契约。
- 配套文档：`docs/tasks/2026-08-20-ruoyi-auth-gateway-plan.md`（计划与冻结决策）、`.ai-team/TASK.md`（进度与决策记录）、`.ai-team/PROJECT.md`（不变量）。

---

## 1. 令牌格式与签名

**冻结结论**

- 请求头：`Authorization: Bearer <jwt>`（与若依 `token.header` 配置一致）。
- 签名算法：HS512（`TokenService.createToken` → `signWith(SignatureAlgorithm.HS512, secret)`）。
- 密钥语义（jjwt 0.9.1，Phase 1 实测坐实）：`token.secret` 字符串**先按标准 base64 解码，解码结果才是 HMAC 密钥**。拿原始字节验签永远失败——这是最容易踩的坑。

**闸机约束**

- FastAPI 侧用 PyJWT 验签，密钥 = `base64.b64decode(RUOYI_JWT_SECRET)`（标准字母表，非 url-safe）。
- 解码后的密钥长度必须 ≥64 字节：**强制项来自 PyJWT（≥2.6）**——HMAC 密钥长度小于 digest size（HS512 即 64 字节）时 `decode` 直接抛 `InvalidKeyError`；jjwt 0.9.1 无此强制。当前 128 字符 secret 解码后 96 字节，两侧均满足。
- `RUOYI_JWT_SECRET` 与若依 `token.secret` **必须是同一把密钥**（两个服务共享）。

## 2. claims 结构

**冻结结论**

- payload 仅两个 claim：`sub`（用户名）、`login_user_key`（uuid）。**无 exp、无 iat**（`Constants.JWT_USERNAME = Claims.SUBJECT`，`Constants.LOGIN_USER_KEY = "login_user_key"`）。

**闸机约束**

- 不能验证 exp；有效期完全由第 3 条的 Redis TTL 承载。
- `sub`（验签后可信）是用户名的权威来源（与 Redis 值顶层 `username` 同值，用于展示与审计）；**数据归属身份以 userId 为准**（见第 6 条），不得用可变的用户名作归属键。

## 3. 有效期、续期与吊销

**冻结结论**

- 有效期 = Redis key `login_tokens:{uuid}` 的 TTL（`token.expireTime`，本部署冻结为 30 分钟）。
- 滑动续期：剩余 ≤20 分钟时若依重置 TTL（`TokenService.verifyToken`）。**续期只发生在若依自己的请求链路上**：用户只访问 agent-api 时不会续期，30 分钟必过期；活跃于若依侧的用户会被一直续期。
- 吊销 = 删 key（登出走 `LogoutSuccessHandlerImpl` → `delLoginUser`，后台强退走在线用户管理的强退，最终都是删 `login_tokens:{uuid}`）。
- **禁用 ≠ 吊销（重要修正，源码核验）**：禁用用户只改 MySQL 状态（`SysUserServiceImpl.updateUserStatus` 不碰 Redis），只挡**新登录**（`UserDetailsServiceImpl` 拒绝禁用用户登录）；已登录会话的 Redis key 原样保留直到 TTL 过期，期间若依后端与闸机都会继续放行。**立即吊销的唯一路径是删 key。**

**闸机与部署约束**

- 闸机必须**每请求查 Redis key 存在性**，不能只验签名。
- 闸机**只读 Redis，绝不写、绝不续期**（否则等于给吊销开洞）。
- 部署流程：在若依后台禁用用户后，必须同时在"在线用户"里强退该用户；Phase 5/7 验收剧本"禁用账号 → 立即 401"按此执行，测试时不能只改用户状态。

## 4. Redis 会话结构

**冻结结论**

- 位置：与若依**同一 Redis 实例、同一 db 0**（`spring.data.redis.database: 0`）；`RUOYI_REDIS_URL` 必须指向它，否则会话互相看不见。
- value：FastJson2 `JSONWriter.Feature.WriteClassName` 序列化的 LoginUser，**非标准 JSON**（含 `@type` 类名、`Set[...]` 集合记法），标准 JSON 库（如 Python `json`）解析不了，Phase 3 必须写容错解析（正则/定制解析器）。

**提取路径（冻结，照此写解析器；2026-08-20 按附录 A 实测样本核验定稿）**

- userName → **顶层 `username`**（如 `"username":"user1"`；来自 `LoginUser.getUsername()` getter 序列化——LoginUser 本体无 username 字段，getter 委托 `user`，故与 `user.userName` 同值、与 JWT `sub` 同值）。顶层缺失时回退 `user.userName`，再回退 JWT `sub`。
- userId → **顶层 `userId`**（如 `"userId":100L`；同样来自 getter 序列化）；回退 `user.userId`。
- roles → `user.roles[].roleKey`（嵌套在 `user` 下，普通数组记法；**LoginUser 顶层没有 roles 字段**，源码与实测一致）。
- admin → **`user.admin` 布尔字段存在**（实测 `"admin":false` / `"admin":true`；来自 `SysUser.isAdmin()` getter 序列化，其实现为 `userId == 1`）。判定冻结为 `user.admin == true`，与 `user.userId == 1` 等价；解析器优先读布尔字段，缺失时回退 `userId == 1`。
- 数值记法：Long 对象字段带 `L` 后缀（`103L`、`100L`），primitive long 无后缀（`"expireTime":1787241317737`）；解析器必须兼容两种。
- 实测补充：value 中**没有 `password` 字段**（附录 A 样本全文核验），fixture 无需脱敏即可入库。

**闸机约束**

- 解析器必须容忍字段缺失（角色列表可为空、字段可能不存在），任何解析失败按"未认证"处理（fail-closed）。
- 序列化格式随 fastjson2 版本变化：升级若依后必须用附录 A 的方法重新取证并更新解析器测试。
- 附录 A 的真实原始值样本是 Phase 3 解析器的测试 fixture，定稿前必须贴入。

## 5. 白名单与 401 格式

**冻结结论**

- agent_platform 白名单：仅 `GET /health`（精确路径 + 精确方法）。SSE、语音、文件、设置、Swagger 一律在登录后。
- 静态页面资源（`agent_platform/static` 下的 HTML/JS/CSS 页壳，不含业务数据）允许匿名 `GET` 加载——Phase 4 的"页面加载 → JS 读 `Admin-Token` → 跳若依登录页"流程以页面可加载为前提。这是对上一条的澄清而非扩大：任何返回业务数据或触发动作的端点一律需要令牌。
- 401 格式（agent_platform 侧，前端/Nginx/测试按此判定）：**真 HTTP 401** + 现有 `ErrorResponse` 形状 `{code, message, retryable, detail}`；未认证场景的 `code` 冻结为一个稳定值：`auth_required`（不沿用随状态码变化的 `http_401`）。
- 与若依侧不同（两边分开写，勿混淆）：若依自身认证失败是 **HTTP 200 + body code 401**（`AuthenticationEntryPointImpl`）。
- 若依自身的匿名路径（`/login`、`/captchaImage`、`/register`、静态资源）是 8080 自己 SecurityConfig 的 permitAll，**与闸机白名单是两回事**，不属于本契约；不要据此把闸机白名单扩大。

**闸机约束**

- 对外 401 一律不区分"缺失/伪造/过期/吊销"（防探测），原因只写服务端日志。
- 闸机连不上 Redis 时 **fail-closed：一律 401，绝不放行**。

## 6. 身份与角色映射

**冻结结论**

- 数据归属身份 = **userId**（不可变；取自 Redis 值顶层 `userId`，回退 `user.userId`，提取路径见第 4 条）；同一账号跨设备登录指向同一数据空间。
  - 注意：此条相对计划文档原冻结的"按用户名"是一处修正（若依允许管理员改用户名，改名会使历史数据失联）。如坚持按用户名，需把"生产环境禁止改用户名"写进 Phase 6 部署手册。
- developer 判定：`user.admin == true`（等价于 `user.userId == 1`，见第 4 条）或 `user.roles[].roleKey ∈ {admin, developer}`。

**闸机约束**

- **不得用 `permissions`（如 `*:*:*`）判定角色**——只有 admin 有该权限位，普通 developer 角色没有，会误判。
- 角色判定只用 Redis 值中的事实，不信任何调用者传入的身份/角色头。

## 7. 配置与密钥

**冻结结论**

- 环境变量：`RUOYI_JWT_SECRET`、`RUOYI_REDIS_URL`；绝不入 Git（仓库铁律）。
- 不提供"关闭认证"开关；测试用 Mock 而非开关。
- 板端部署时**重新生成 secret**，不复制 PC 开发环境的 secret；若依侧 `token.secret` 用 Spring 占位符（`${TOKEN_SECRET:...}`）注入同一环境变量。

## 8. SSE 鉴权（Phase 4 前置，本契约新增）

**冻结结论**

- 现状：前端用 `EventSource`（`agent_platform/static/app.js`），浏览器 EventSource **无法设置自定义请求头**，闸机落地后 SSE 必 401。
- 冻结方案：前端改为 **fetch + ReadableStream** 读流（推荐）；或 SSE 端点额外接受同源 cookie 携带的 token。**禁止**用 query 参数传 token（会进访问日志）。

## 9. 前端令牌存储

**冻结结论**

- 若依前端把 token 存 cookie `Admin-Token`（js-cookie，非 HttpOnly，XSS 可读——自签 + 同源部署下接受此风险，后续可考虑 HttpOnly 化）；请求统一附加 `Authorization: Bearer <token>`。
- Phase 4 要求操作台与若依前端同源（同源才能读该 cookie）。

---

## 附录 A：真实样本（2026-08-20 取证，字节精确）

取证环境：RuoYi-Vue `springboot3`（pom version 3.9.2）本地实例（MySQL 3306 / Redis 6379 / 后端 8080，`D:\ruoyi-env\start-env.cmd` 一键启停）。脚本登录前按 TASK.md 记录的流程临时关闭验证码（改 `sys_config` + 删 Redis 缓存键 `sys_config:sys.account.captchaEnabled`），取证完成后已恢复 `true` 并经 `GET /captchaImage` 返回 `captchaEnabled=true` 复测确认。样本账号：user1（内置普通角色 `common`，userId=100）与 admin（`roleKey=admin`，userId=1）。样本文件另存于仓库外 `D:\ruoyi-env\secrets\`（phase2-*.txt / phase2-*.json）。

### A.1 真实 JWT 解码结果

| 账号 | header | payload |
|---|---|---|
| user1 | `{"alg": "HS512"}` | `{"sub": "user1", "login_user_key": "54c1e577-212a-48da-800c-4d65bc1e5424"}` |
| admin | `{"alg": "HS512"}` | `{"sub": "admin", "login_user_key": "b5c314d8-b721-49b4-a4c0-c638ea58d0ed"}` |

两枚 token 均为三段式、签名段 86 字符；payload 仅含 `sub` + `login_user_key`，无 `exp`/`iat`，与第 2 条一致。

### A.2 `GET login_tokens:{uuid}` 原始值全文（user1）

说明：redis-cli `GET` 输出末尾换行为终端行为，不属于值本身；值本体 4294 字符、单行、合法 UTF-8。Python 标准库 `json.loads` 在第 92 字符（`103L` 记法）即抛错失败——第 4 条"必须容错解析"的实证。`TTL` 取证时为 1788 秒（≈30 分钟，与 `token.expireTime=30` 一致）。

```text
{"@type":"com.ruoyi.common.core.domain.model.LoginUser","browser":"Curl 8.18.0","deptId":103L,"expireTime":1787241317737,"ipaddr":"127.0.0.1","loginLocation":"内网IP","loginTime":1787239517737,"os":"","permissions":Set["system:user:resetPwd","system:post:list","monitor:operlog:export","monitor:druid:list","system:menu:query","system:dept:remove","system:menu:list","tool:gen:edit","system:dict:edit","monitor:logininfor:remove","monitor:job:list","system:user:query","system:user:add","system:notice:remove","system:user:export","system:role:remove","monitor:job:edit","tool:gen:query","system:dept:query","system:dict:list","monitor:job:query","monitor:online:forceLogout","system:notice:list","system:dict:query","monitor:online:query","system:notice:query","system:notice:edit","monitor:online:list","tool:gen:import","system:post:edit","monitor:job:add","monitor:logininfor:list","tool:gen:list","system:dict:export","system:post:query","system:post:remove","system:config:edit","system:user:remove","system:config:list","system:menu:add","system:role:list","system:user:import","system:dict:remove","system:user:edit","system:post:export","system:config:export","system:role:edit","monitor:online:batchLogout","system:dept:list","system:config:query","monitor:operlog:remove","monitor:operlog:list","system:role:add","system:menu:remove","system:dict:add","monitor:logininfor:query","monitor:server:list","tool:build:list","monitor:logininfor:export","tool:swagger:list","system:dept:edit","system:post:add","monitor:job:changeStatus","tool:gen:preview","monitor:operlog:query","system:user:list","system:notice:add","monitor:job:remove","system:role:export","monitor:cache:list","system:config:add","monitor:logininfor:unlock","tool:gen:code","monitor:job:export","tool:gen:remove","system:role:query","system:menu:edit","system:dept:add","system:config:remove"],"token":"54c1e577-212a-48da-800c-4d65bc1e5424","user":{"admin":false,"createBy":"admin","createTime":"2026-08-20 18:55:13","delFlag":"0","dept":{"ancestors":"0,100,101","children":[],"deptId":103L,"deptName":"研发部门","leader":"若依","orderNum":1,"params":{"@type":"java.util.HashMap"},"parentId":101L,"status":"0"},"deptId":103L,"loginDate":"2026-08-20 18:55:27","loginIp":"127.0.0.1","nickName":"��ͨ�����û�","params":{"@type":"java.util.HashMap"},"roles":[{"admin":false,"dataScope":"2","deptCheckStrictly":false,"flag":false,"menuCheckStrictly":false,"params":{"@type":"java.util.HashMap"},"permissions":Set["system:user:resetPwd","system:post:list","monitor:operlog:export","monitor:druid:list","system:menu:query","system:dept:remove","system:menu:list","tool:gen:edit","system:dict:edit","monitor:logininfor:remove","monitor:job:list","system:user:query","system:user:add","system:notice:remove","system:user:export","system:role:remove","monitor:job:edit","tool:gen:query","system:dept:query","system:dict:list","monitor:job:query","monitor:online:forceLogout","system:notice:list","system:dict:query","monitor:online:query","system:notice:query","system:notice:edit","monitor:online:list","tool:gen:import","system:post:edit","monitor:job:add","monitor:logininfor:list","tool:gen:list","system:dict:export","system:post:query","system:post:remove","system:config:edit","system:user:remove","system:config:list","system:menu:add","system:role:list","system:user:import","system:dict:remove","system:user:edit","system:post:export","system:config:export","system:role:edit","monitor:online:batchLogout","system:dept:list","system:config:query","monitor:operlog:remove","monitor:operlog:list","system:role:add","system:menu:remove","system:dict:add","monitor:logininfor:query","monitor:server:list","tool:build:list","monitor:logininfor:export","tool:swagger:list","system:dept:edit","system:post:add","monitor:job:changeStatus","tool:gen:preview","monitor:operlog:query","system:user:list","system:notice:add","monitor:job:remove","system:role:export","monitor:cache:list","system:config:add","monitor:logininfor:unlock","tool:gen:code","monitor:job:export","tool:gen:remove","system:role:query","system:menu:edit","system:dept:add","system:config:remove"],"roleId":2L,"roleKey":"common","roleName":"普通角色","roleSort":2,"status":"0"}],"sex":"0","status":"0","userId":100L,"userName":"user1"},"userId":100L,"username":"user1"}
```

### A.3 admin 会话值身份片段（admin 判定 fixture）

admin 的 value 结构与 A.2 相同（差异：`permissions` 为 `Set["*:*:*", …]`、`user.admin` 为 `true`、角色数组仅一项）。身份相关字段从原始值逐字节摘出（首行截取自 `user` 对象开头，其余两段为完整片段）：

```text
"user":{"admin":true,"createBy":"admin","createTime":"2026-08-20 18:41:03","delFl …截断
"roles":[{"admin":true,"dataScope":"1","deptCheckStrictly":false,"flag":false,"menuCheckStrictly":false,"params":{"@type":"java.util.HashMap"},"roleId":1L,"roleKey":"admin","roleName":"超级管理员","roleSort":1,"status":"0"}]
"userId":1L,"username":"admin"}
```

admin 完整原始值字节同样留存于仓库外取证文件；Phase 3 解析器单测以 A.2 全文 + A.3 片段为准。

取证命令：`redis-cli KEYS "login_tokens:*"`、`redis-cli GET login_tokens:<uuid>`、`redis-cli TTL login_tokens:<uuid>`。Phase 3 解析器与单测必须以本附录样本为准。

## 附录 B：对 Phase 3/4 开发者的落地要点

- 闸机校验顺序：解析 `Authorization: Bearer` → PyJWT 验签（b64 解码密钥）→ 取 `login_user_key` → 查 Redis `login_tokens:{uuid}` 存在性 → 容错解析值取 userId/roles → 注入会话上下文。任一步失败 → 401 `auth_required`。
- 白名单仅 `GET /health`；其余路由（含 SSE、语音、文件、设置、Swagger）一律在门后。
- 会话映射：令牌验证通过后以 **userId** 作为数据归属身份接入现有会话隔离体系；HttpOnly Cookie 会话建立发生在令牌验证通过之后。
- 开发者控制台入口改为判断若依角色（`user.admin == true`（等价 `userId == 1`）或 roleKey ∈ {admin, developer}），退役旧环境变量密码门。
- SSE 端点按第 8 条改造前端，不能用 EventSource 直连。
- 测试覆盖（进 `tests/` 常规体系）：Mock 签发器（HS512 + 假 Redis）覆盖合法放行、缺失 401、伪造签名 401、过期 401、已吊销 401、角色映射（普通用户 vs developer/admin）、白名单放行；curl 实测无 token 401、带真实若依 token 200。

## 变更规则

若依升级新版本后，必须重新核验本契约的 1～4、6、9 条（签名与 claims 结构、续期/吊销行为、Redis 值格式与提取路径、admin/角色判定、前端 cookie 名），并更新附录 A 样本；核验结论与证据记录进 `.ai-team/TASK.md` 后才能推进对应 Phase。
