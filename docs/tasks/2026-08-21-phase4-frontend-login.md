# Phase 4 前端登录对接：本地全链路走查记录（PC 证据）

- 任务：`RUOYI-AUTH-GATEWAY-001` Phase 4
- 日期：2026-08-21
- 证据级别：**PC 证据**（Windows 本地若依实例 + uvicorn + Vue dev 代理），不代表板端/公网结论
- 走查方式：浏览器自动化（IAB）+ curl + redis-cli/mysql（仓库外 `D:\ruoyi-env`）

## 环境

| 组件 | 端口 | 说明 |
|---|---|---|
| MySQL 8.0.43 / Redis 5.0.14.1 | 3306 / 6379 | `D:\ruoyi-env` 便携栈 |
| 若依后端（springboot3, JDK17） | 8080 | `ruoyi-admin.jar` |
| 若依前端（RuoYi-Vue2 dev） | 8081 | `vue.config.js` 增加 `/agent-api` 代理 → `127.0.0.1:8000`（仓库外配置，可用 `AGENT_API_TARGET` 覆盖） |
| agent_platform FastAPI | 8000 | `MODEL_PROVIDER=mock` 环境变量覆盖启动（仅影响模型，认证闸机全程生效）；`.env` 注入 `RUOYI_*` 与 `RUOYI_LOGOUT_URL=/dev-api/logout` |

同源拓扑与计划文档第 2 节生产形态一致：若依前端为站点根，操作台挂 `/agent-api/`，浏览器只访问 `http://localhost:8081/agent-api/`。

## 走查矩阵（全部通过）

| # | 场景 | 结果 |
|---|---|---|
| 1 | curl `/agent-api/health`（无 token） | 200（白名单经代理有效） |
| 2 | curl `/agent-api/tasks`（无 token） | 401 `{"code":"auth_required"}` |
| 3 | curl `/agent-api/`（页壳） | 200，注入 `data-login-url="/#/login"`、`data-logout-url="/dev-api/logout"`，资源相对引用 |
| 4 | 浏览器未登录打开 `/agent-api/` | 登录闸机对话框拦截（"需要登录后使用"）；`退出`按钮与`开发者控制台`入口正确隐藏 |
| 5 | 点击"打开若依登录页" | 弹出若依登录页（含验证码） |
| 6 | user1 登录（真实验证码） | 登录成功；操作台 800ms 轮询自动检测 `Admin-Token`，闸机解除、无需刷新 |
| 7 | 登录后界面 | 身份显示 `user1 · 用户`；页脚无开发者入口（`hidden`） |
| 8 | 提交 AI 任务 | `POST /tasks` 201 → SSE fetch 流（服务端日志 `GET /tasks/{id}/events` 200）→ 实时任务区更新至"已完成"；"添加待办 准备Phase4验收材料 高优先级"创建待办 #3 并渲染结构化卡片 |
| 9 | user1 直访 `/agent-api/developer` | 加载页壳后由前端角色闸机弹回 `/agent-api/`（URL 变更、无开发者侧栏） |
| 10 | user1 登出 | 页面回到若依登录页；redis `login_tokens:*` 清空（`POST /dev-api/logout` 服务端吊销生效） |
| 11 | dev1 登录（脚本化，验证码临时关闭→恢复） | 身份 `dev1 · 开发者`；页脚显示`开发者控制台`；近期任务为空（与 user1 数据空间隔离的界面佐证） |
| 12 | 进入开发者控制台 | 总览加载：8 工具、24 HTTP 操作（`/openapi.json` 带认证拉取成功）、检查器/设置可用 |
| 13 | dev1 登出 | 回若依登录页，redis 无残留会话 |
| 14 | 验证码恢复复测 | `GET /captchaImage` 返回图片（enabled） |

自动化截图在会话记录中留档（登录闸机、任务结果等）；正式截图/录屏归档按计划属 Phase 5 验收内容。

## 走查中发现并修复的缺陷

1. **`[hidden]` 失效**：`.button{display:inline-flex}` 覆盖了 `hidden` 属性的 UA 样式，导致匿名/普通用户看到`退出`与`开发者控制台`入口。修复：styles.css 增加 `[hidden]{display:none!important}`。
2. **`/developer` 浏览器导航 401**：Phase 3 将 `/developer` 路由放在服务端令牌门后（匿名 401、user 303），但浏览器导航/链接点击无法携带 `Authorization` 头，开发者点入口会得到 401 JSON。修复：`/developer` 改为匿名页壳（与契约 §5 页壳模型一致），登录与角色校验由 app.js 前端闸机执行；数据端点仍在服务端门后。同步更新 `test_ruoyi_auth.py`、`test_agent_api.py` 断言（303→200）与 `test_frontend_shell.py`。

## 复现

```powershell
D:\ruoyi-env\start-env.cmd          # MySQL/Redis/8080/8081（vue.config.js 已含 /agent-api 代理）
Set-Location 'D:\my new work\cloud-flowing_0806'
.\.venv\Scripts\python.exe -m agent_platform.cli serve   # .env 已含 RUOYI_* 与 RUOYI_LOGOUT_URL=/dev-api/logout
# 浏览器打开 http://localhost:8081/agent-api/，用 user1 / dev1 登录走查
```

测试账号密码在仓库外 `D:\ruoyi-env\secrets\RUOYI_TEST_USERS.txt`；`RUOYI_TOKEN_SECRET.txt` 为两侧共享密钥（不入库）。
