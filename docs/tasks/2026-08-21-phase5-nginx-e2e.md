# Phase 5 Nginx 本地全链路联调：走查记录（PC 证据）

- 任务：`RUOYI-AUTH-GATEWAY-001` Phase 5
- 日期：2026-08-21
- 证据级别：**PC 证据**（Windows 本地 nginx 1.30.4 + 若依生产构建 + uvicorn，全回环），不代表板端/公网结论；Phase 7 复用本走查矩阵作板端验收模板
- 走查方式：浏览器自动化（IAB）+ curl + redis-cli/mysql（仓库外 `D:\ruoyi-env`）；浏览器只访问 `http://localhost/`（Nginx 80 端口），全程未直连 8080/8081/8000
- 证据目录：`docs/tasks/phase5-evidence/`（截图 01～08 + 本阶段 nginx.conf 快照）

## 环境

| 组件 | 端口 | 说明 |
|---|---|---|
| nginx 1.30.4（便携 ZIP） | 127.0.0.1:80 | `D:\ruoyi-env\nginx`，配置快照 `phase5-evidence/nginx.conf.phase5-pc`；唯一浏览器入口 |
| 若依前端（生产构建 dist） | 静态 | `RuoYi-Vue2` `npm run build:prod`（Node 18），`VUE_APP_BASE_API=/prod-api`，history 模式路由 |
| 若依后端（springboot3） | 8080 | `/prod-api/` 经 Nginx 转发（前缀剥离） |
| agent_platform FastAPI | 8000 | `/agent-api/` 经 Nginx 转发（前缀剥离，与 Phase 4 dev 代理同构）；`MODEL_PROVIDER=mock`；`RUOYI_LOGOUT_URL=/prod-api/logout` 环境变量覆盖启动（未改仓库 .env） |
| MySQL / Redis | 3306 / 6379 | 便携栈 |

三条 location（快照文件全文见 `phase5-evidence/nginx.conf.phase5-pc`，摘要）：

- `/` → 若依前端 dist（`try_files $uri $uri/ /index.html`）
- `/prod-api/` → `http://127.0.0.1:8080/`（前缀剥离）
- `/agent-api/` → `http://127.0.0.1:8000/`（前缀剥离；`proxy_buffering off` + `proxy_read_timeout 3600s` 保 SSE 流式；含 `limit_req zone=gateway burst=60 nodelay` 防御基线，Phase 6 收敛到登录端点）

## 走查矩阵（Phase 4 14 项模板，全部通过）

| # | 场景 | 结果 |
|---|---|---|
| 1 | curl `/agent-api/health`（无 token） | 200（白名单经 Nginx 有效） |
| 2 | curl `/agent-api/tasks`（无 token） | 401 `{"code":"auth_required"}` |
| 3 | curl `/agent-api/`（页壳） | 200，注入 `data-login-url="/#/login"`、`data-logout-url="/prod-api/logout"`（生产拓扑默认值） |
| 4 | 浏览器未登录打开 `/agent-api/` | 登录闸机对话框"需要登录后使用"；无退出按钮、无开发者入口（截图 01） |
| 5 | 打开若依登录页 | 若依登录页含验证码（截图 02）。**偏差**：IAB 拦截 `window.open` 弹窗，改用同源第二标签页直接打开 `/#/login`（cookie/轮询机制不变） |
| 6 | user1 登录（真实验证码开启） | 登录成功；操作台 800ms 轮询自动检测 `Admin-Token`，闸机自动解除、无需刷新（nginx 日志：`POST /prod-api/login` 200 → `GET /agent-api/auth/me` 200） |
| 7 | 登录后界面 | 身份 `user1 · 用户`；页脚无开发者入口（截图 03） |
| 8 | 提交 AI 任务 | `POST /agent-api/tasks` 201 → SSE fetch 流 `GET /agent-api/tasks/e8e158f5-*/events` 200（均经 80 端口，access.log 佐证）→ 待办 #4 结构化卡片渲染（截图 04） |
| 9 | user1 直访 `/agent-api/developer` | 页壳加载后前端角色闸机弹回 `/agent-api/`（URL 变更、无开发者侧栏） |
| 10 | user1 登出 | `POST /prod-api/logout`（经 Nginx）→ 服务端吊销：同 token 再调 `/auth/me` 立即 401；浏览器新开操作台页回到闸机状态且残留 cookie 被清空（截图 05） |
| 11 | dev1 登录（真实验证码开启） | 身份 `dev1 · 开发者`；页脚显示`开发者控制台`；近期任务为空（与 user1 4 条任务隔离，界面佐证；截图 06） |
| 12 | 进入开发者控制台 | 总览加载：已注册能力 8（预期 8 工具）、HTTP 操作 24（来自 OpenAPI）、隔离任务账本 0（截图 07） |
| 13 | dev1 登出 | `POST /prod-api/logout` → 401；redis `login_tokens:*` 无残留会话 |
| 14 | 验证码状态复测 | 全程 `captchaEnabled=true`（从 Phase 4 的临时关闭改为全程开启，见下"验证码解法"）；最终复测 `captchaEnabled: True` |

## 补充剧本（用户指定三条）

### A. 伪造 token → 401

三种伪造形态均经 Nginx 调 `/agent-api/tasks`，全部 401 `auth_required`（原始输出 `D:\ruoyi-env\tmp\phase5-forged.txt`）：

- CASE1 错误密钥 HS512 签名（随机 64B 密钥签合法形态 payload）→ 401
- CASE2 正确密钥签名但 `login_user_key` 为随机 uuid（Redis 无此会话，等价"已吊销"路径）→ 401
- CASE3 乱码 token `not.a.jwt` → 401

对外不区分三种失败形态，均为同一 401（防探测，契约 §5）。

### B. 强退（删 Redis 会话键）→ 立即 401

脚本化 user1 登录（验证码开启）→ `GET /agent-api/auth/me` 200（`user1/user_id:100`）→ `redis-cli DEL login_tokens:{uuid}`（返回 1）→ 同 token 再调：

- agent 侧 `/auth/me` → 401 `auth_required`（立即生效，不依赖 TTL）
- 若依侧 `/prod-api/getInfo` → body `{"msg":"...认证失败...","code":401}`（HTTP 200 包裹，Phase 2 已知形态）

原始输出 `D:\ruoyi-env\tmp\phase5-force-logout.txt`。

### C. 禁用账号（含"禁用 ≠ 吊销"实测）

admin 经若依后台 UI（`/system/user`，history 模式路由）搜索 user1 → 状态开关 → 确认"停用"（截图 08）→ DB 复核 `status=1`。随后实测：

1. **新登录被拒**：user1 脚本化登录 → 若依返回 `{"msg":"用户已封禁，请联系管理员","code":500}` ✓
2. **既有会话不受影响**（契约冻结的"禁用≠吊销"实证）：停用前签发的 token 仍 `auth/me` 200 ✓
3. **强退即失效**：对同一 token `DEL login_tokens:{uuid}` → 立即 401 ✓

恢复：DB `UPDATE sys_user SET status='0'`（等效后台"启用"，UI 开关第二次点击因表格未刷新呈幂等停用，走查备注见下）→ 脚本化登录重新签发 token 成功 → 登出清理。原始输出 `D:\ruoyi-env\tmp\phase5-disable-verify.txt`、`phase5-reenable-verify.txt`。

**结论**：剧本"禁用账号 → 立即 401"的正确执行形态 = 禁用（挡新登录）+ 强退（删 Redis key 吊销既有会话），两步都已验证；Phase 7 板端验收表按此两步写。

## 额外佐证

- 同源 cookie 与角色映射：admin 会话存在时操作台显示 `admin · 开发者`、开发者入口可见、数据空间独立为空（第三个账号的空间隔离佐证）。
- nginx access.log 关键行（全部经 80 端口）：`POST /prod-api/login 200` → `GET /agent-api/auth/me 200` → `POST /agent-api/tasks 201` → `GET /agent-api/tasks/{id}/events 200`（SSE）→ `POST /prod-api/logout 200` → 吊销后 `GET /agent-api/auth/me 401`。

## 走查备注与偏差（如实记录）

1. **IAB 弹窗拦截**：闸机按钮 `window.open` 被 IAB 拦截，改为第二标签页同源打开 `/#/login`（cookie 同源、轮询机制完全相同）；弹窗路径本身在 Phase 4 已验证。
2. **顶部固定栏按钮无法自动化点击**：操作台页头 `退出` 按钮位于视口 y<50（被 IAB 顶部工具条区域覆盖），合成点击不触发（点击管线对中部元素如提交任务、状态开关均正常）。登出吊销改在 HTTP 层验证（同 `/prod-api/logout` 路径，见矩阵 10/13），按钮 UI 行为以 Phase 4 走查为证。
3. **验证码解法（改进）**：本阶段验证码全程开启（Phase 4 曾临时关闭）。浏览器登录页取码时，若依把答案写入本机 Redis `captcha_codes:{uuid}`；以环境所有者身份读取该值填入表单，登录仍走真实服务端验证码校验链路（答案错误必拒），比"临时关验证码"证据更强。
4. 若依生产构建为 **history 模式路由**（如 `/system/user`），与 Phase 4 dev 服务器形态的 hash 路由不同——生产形态事实，nginx `try_files` 回退已覆盖。
5. 登录表单出现浏览器密码管理器残留填充（`admin/admin123` 旧快照），每次显式覆盖后提交，不影响结果。
6. 停用开关第二次点击因列表未刷新呈幂等"停用"，恢复启用改走 DB UPDATE（与 `changeUserStatus` 同语义）；"停用"方向证据来自 UI 操作本身。

## 复现

```powershell
D:\ruoyi-env\start-env.cmd           # MySQL/Redis/8080/8081（8081 本次未用）
cd /d D:\ruoyi-env\RuoYi-Vue2 && set PATH=D:\ruoyi-env\node18;%PATH% && npm run build:prod
D:\ruoyi-env\nginx\nginx.exe        # 80 端口，配置见 phase5-evidence/nginx.conf.phase5-pc
# FastAPI（Nginx 拓扑环境变量覆盖，不改 .env）：
cd /d "D:\my new work\cloud-flowing_0806"
cmd /c "set RUOYI_LOGOUT_URL=/prod-api/logout&& set MODEL_PROVIDER=mock&& .venv\Scripts\python.exe -m agent_platform.cli serve"
# 浏览器只访问 http://localhost/（若依登录 + http://localhost/agent-api/ 操作台）
```

测试账号密码在仓库外 `D:\ruoyi-env\secrets\`（不入库）。
