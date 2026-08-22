# 若依认证网关：本地测试指引（2026-08-21，Phase 5 交付后）

- 适用：不熟悉网关实现的评审人 / 测试人，在 Windows PC 上手工验证整套认证链路
- 证据级别：**PC 证据**（本地全回环），板端结论要等 Phase 7
- 配套文档：`docs/tasks/2026-08-20-ruoyi-auth-gateway-plan.md`（计划）、`docs/contracts/ruoyi-auth-gateway.md`（对接契约）、`docs/tasks/2026-08-21-phase5-nginx-e2e.md`（本次走查证据）

## 1. 一句话架构

```
浏览器 ──→ http://localhost/（nginx 80 端口，唯一入口）
              ├── /            若依前端（登录页、账号管理）
              ├── /prod-api/   若依后端（8080，账号与登录）
              └── /agent-api/  云湃 AI 操作台（8000，JWT 闸机）
```

- 访问云湃 AI 的一切 API 都要求带若依签发的令牌（`Authorization: Bearer <jwt>`）；没有有效令牌一律 401。
- 账号、密码只存在若依（MySQL）；云湃 AI 只"验票"不存密码，并按账号隔离业务数据。
- 只有 `GET /health` 和静态页面是白名单；SSE、语音、文件、设置、文档全部在登录后。

## 2. 软件路径清单

### 仓库内（D:\my new work\cloud-flowing_0806，git）

| 路径 | 内容 |
|---|---|
| `agent_platform/api/middleware.py` | JWT 闸机中间件（401 判定处） |
| `agent_platform/core/ruoyi_auth.py` | 验签 + 查若依 Redis 会话 |
| `agent_platform/static/app.js` `index.html` `developer.html` | 操作台前端（登录闸机、角色界面） |
| `docs/contracts/ruoyi-auth-gateway.md` | 对接契约（冻结） |
| `docs/tasks/2026-08-20-ruoyi-auth-gateway-plan.md` | 任务计划（第 3 节决策冻结） |
| `.ai-team/TASK.md` | 任务进度与交接 |
| `.env`（gitignore，不入库） | 本地密钥/配置（`RUOYI_JWT_SECRET` 等） |
| `docs/tasks/phase5-evidence/` | 截图与 nginx 配置快照 |

### 仓库外（D:\ruoyi-env，无空格联接，全便携免安装）

| 路径 | 内容 |
|---|---|
| `mysql\` `mysql-data\` | MySQL 8（3306，库 `ry-vue`） |
| `redis\` | Redis 5（6379） |
| `jdk\` | JDK 17 |
| `RuoYi-Vue\` | 若依后端（springboot3，jar 跑 8080，黑盒不改源码） |
| `RuoYi-Vue2\` | 若依前端（Node 18 构建，`dist` 由 nginx 直接服务） |
| `node18\` | Node 18.20.8 |
| `nginx\` | nginx 1.30.4（80 端口，配置 `conf\nginx.conf`） |
| `apache-maven-3.9.9\` | Maven |
| `secrets\` | 测试账号密码、`token.secret`（**铁律：绝不入库**） |
| `start-env.cmd` / `stop-env.cmd` | 一键启停 MySQL/Redis/8080/8081 |
| `tmp\` | 联调取证文件（phase5-*.txt） |

## 3. 启动步骤（从零到可测）

```powershell
# ① 底栈：MySQL 3306 / Redis 6379 / 若依后端 8080 / 若依前端 dev 8081（8081 本次可不用）
D:\ruoyi-env\start-env.cmd

# ② 若依前端生产构建（改过前端或 dist 不存在时才需要；现在已构建好）
cd /d D:\ruoyi-env\RuoYi-Vue2
set PATH=D:\ruoyi-env\node18;%PATH%
npm run build:prod

# ③ nginx（80 端口）
D:\ruoyi-env\nginx\nginx.exe

# ④ 云湃 AI 操作台后端（Nginx 拓扑的环境变量覆盖启动，不改 .env）
cd /d "D:\my new work\cloud-flowing_0806"
cmd /c "set RUOYI_LOGOUT_URL=/prod-api/logout&& set RUOYI_MANAGE_URL=/index&& set MODEL_PROVIDER=mock&& .venv\Scripts\python.exe -m agent_platform.cli serve"
```

自检（三条路径都通）：

```powershell
curl -I http://localhost/                     # 302 → /agent-api/（2026-08-23 起站点根直达操作台）
curl http://localhost/login                   # 若依登录页（HTML，标题"云湃 AI"）
curl http://localhost/agent-api/health        # {"status":"ok",...}
curl http://localhost/agent-api/tasks         # 401 {"code":"auth_required",...}
```

> 当前机器上这四步都已就绪且在运行，可直接开测。

## 4. 测试账号（密码在 D:\ruoyi-env\secrets\RUOYI_TEST_USERS.txt / RUOYI_ADMIN_PASSWORD.txt）

| 账号 | 角色 | 预期表现 |
|---|---|---|
| user1 | 普通用户 | 任务页可用；**看不到**开发者入口；直访开发者页被弹回 |
| dev1 | developer | 任务页 + 开发者控制台都可用 |
| admin | 若依超管 | 若依后台（建账号、停用/启用账号） |

## 5. 验证码怎么处理

验证码**保持开启**（安全清单要求）。登录页显示的是数学题图片（如 `7+6=?`）。自动化时不需要 OCR：若依把答案存在本机 Redis：

```
# uuid 从登录页的取码请求拿（curl /prod-api/captchaImage 响应里有 uuid 字段）
D:\ruoyi-env\redis\redis-cli.exe get captcha_codes:<uuid>   # 返回答案，TTL 2 分钟
```

人工测试直接看图算就行。

## 6. 手工测试清单（照着点）

浏览器只访问 `http://localhost/`，不要直连 8080/8081/8000。

1. **未登录被拦**：打开 `http://localhost/` → 自动跳到操作台 `/agent-api/` 并弹出"需要登录后使用"闸机，无退出按钮、无开发者入口（2026-08-23 起站点根直达操作台，不再落在若依管理系统首页）。
2. **登录**：点"打开若依登录页"（或直接开 `http://localhost/login`）→ user1 登录（含验证码）→ 操作台约 1 秒内自动放行（无需刷新）。
3. **普通用户界面**：左上角身份显示 `user1 · 用户`；页脚**没有**"开发者控制台"。
4. **用 AI 功能**：输入"添加待办 准备测试材料 高优先级"→ 提交 → 实时状态走到"已完成"，渲染待办结构化卡片（当前 mock 模型，响应确定性）。
5. **角色边界**：user1 直访 `http://localhost/agent-api/developer` → 自动弹回任务页。
6. **登出**：点右上"退出" → 回到若依登录页；再打开操作台回到闸机状态。
7. **开发者**：dev1 登录 → 身份 `dev1 · 开发者`，页脚出现"开发者控制台"→ 进去看到"已注册能力 8 / HTTP 操作 24"；注意 dev1 的近期任务为空（与 user1 数据隔离）。顶栏有"管理后台 ↗"按钮 → 新标签页打开若依管理系统（账号/停启用管理入口，普通用户页无此按钮）。
8. **数据隔离**：user1 建的待办，dev1/admin 登录后看不到；同一账号换浏览器登录看到的是同一份数据。
9. **停用账号**（admin 经"管理后台"按钮或直访 `http://localhost/system/user` → 搜 user1 → 状态开关停用）：
   - user1 再登录 → 被拒（"用户已封禁"）；
   - 已登录的 user1 会话不受影响（设计如此：禁用只挡新登录，立即踢人靠下一步强退）；
   - 恢复：把开关切回启用。

## 7. 强退 / 伪造令牌（进阶，curl + redis-cli）

```powershell
# 强退：删掉 Redis 里的会话键，该 token 立即失效（agent 侧与若依侧都 401）
D:\ruoyi-env\redis\redis-cli.exe keys login_tokens:*
D:\ruoyi-env\redis\redis-cli.exe del login_tokens:<uuid>

# 带 token 调接口看效果
curl -H "Authorization: Bearer <token>" http://localhost/agent-api/auth/me
# 有效 → {"role":"user","username":"user1","user_id":100}；被删/伪造 → 401 auth_required
```

## 8. 收尾

- 停操作台：serve 窗口 Ctrl+C；
- 停 nginx：`D:\ruoyi-env\nginx\nginx.exe -s stop`；
- 停底栈：`D:\ruoyi-env\stop-env.cmd`。

## 9. 已知要点与坑

- 若依前端生产构建是 history 模式路由：后台页面用 `/system/user` 这类真实路径，nginx 已配置回退。
- 内置"普通角色"目前仍带系统管理菜单（Phase 2 已发现，Phase 6 清理），user1 登录若依后台会看到系统管理入口——属已知待办，不影响本清单结论。
- 密码管理器可能在登录表单残留 admin/admin123 旧填充，提交前覆盖成目标账号。
- 本机自动化（IAB）的两个已知限制：弹窗被拦截（用第二标签页代替）、页面顶部固定栏按钮点不到（登出改走 HTTP 验证）——人工测试不受影响。
