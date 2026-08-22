# 入口直达操作台 + 产品名落地：走查记录（PC 证据）

- 任务：`RUOYI-AUTH-GATEWAY-001`（Phase 6 后增量，用户 2026-08-23 决定）
- 日期：2026-08-23
- 证据级别：**PC 证据**（Windows 本地 nginx + 若依生产构建 + uvicorn，全回环），不代表板端结论；板端复验随 Phase 7
- 需求（用户原话归纳）：
  1. 登录后直达 agent 页面，中间不出现若依管理系统首页；管理系统隐藏，入口放到开发者页面按钮跳转。
  2. 登录页换为与 agent 适配的产品名（轻量档：仅改构建标题，不动若依源码）。

## 改动清单

| 位置 | 改动 | 说明 |
|---|---|---|
| `deployment/ruoyi-gateway/nginx/nginx.conf` | 443 server 新增 `location = / { return 302 /agent-api/; }` | 站点根直达操作台；`/index`、`/login`、`/system/user` 等真实路由不受影响 |
| `D:\ruoyi-env\nginx\conf\nginx.conf`（本地，仓库外） | 同上（同构） | PC 测试环境与板端生产形态保持一致 |
| `agent_platform/api/server.py` | `DEFAULT_LOGIN_URL` `/#/login` → `/login` | 若依生产构建是 history 路由；站点根被 302 接管后 hash 形式会被抢跳 |
| `agent_platform/config/settings.py` | 新增 `ruoyi_manage_url`（env `RUOYI_MANAGE_URL`，默认空） | 空 = 不显示管理入口（desktop/serve 拓扑）；反向代理拓扑置 `/index` |
| `agent_platform/api/server.py` 页壳注入 | 新增 `__RUOYI_MANAGE_URL__` 占位符 | 与 LOGIN/LOGOUT 同机制，html.escape 后注入 |
| `agent_platform/static/index.html` `developer.html` | body 新增 `data-manage-url`；developer 顶栏新增 `#manageLink`（默认 `hidden`） | 按钮只在开发者控制台存在，配置为空时保持隐藏 |
| `agent_platform/static/app.js` | `gatewayConfig` 增加 `manageUrl`；登录兜底改 `/login`；引导时接线 `#manageLink` | 静态兜底沿用 `shellConfig` 模式 |
| `deployment/ruoyi-gateway/install/install.sh` | env 生成新增 `RUOYI_MANAGE_URL=/index` | 板端拓扑默认显示管理入口 |
| `.env.example` | 新增 `RUOYI_MANAGE_URL=` 占位与两种拓扑说明 | |
| 若依前端（仓库外 `D:\ruoyi-env\RuoYi-Vue2`） | `.env.production`/`.env.development` `VUE_APP_TITLE` 若依管理系统 → 云湃 AI；`npm run build:prod` 重建 dist | 属"只改配置不改源码"（黑盒约束内）；deploy 打包经 `pack_deploy.py` 直接取该 dist，无需另拷 |

设计边界：若依源码零改动；统一登录门、角色映射、数据隔离、白名单与 401 契约全部不变。

## 自动化验证（2026-08-23）

- `pytest -q -p no:cacheprovider --basetemp <独立目录>`：**576 项全部通过**（exit=0；含工作区并行任务的 89 项 WIP 测试，它们亦绿）。
- `compileall agent_platform evaluation deployment` OK；`node --check agent_platform/static/app.js` OK；`bash -n install.sh` OK；`node .ai-team/check.mjs --base origin/main` Result: valid。
- `tests/test_frontend_shell.py` 断言更新：默认 `data-login-url="/login"`、默认 `data-manage-url=""`、注入 `/index`、原始占位符不外漏、developer 壳含 `#manageLink`。

## 实测走查（浏览器只走 http://localhost/，2026-08-23）

curl 层：

1. `GET /` → **302 → /agent-api/**（`Location: http://localhost/agent-api/`）
2. 跟随跳转后页壳注入 `data-login-url="/login" data-logout-url="/prod-api/logout" data-manage-url="/index"`
3. `GET /login` → 200，`<title>云湃 AI</title>`（新标题）
4. `GET /index` → 200（管理后台真实路由不受 302 影响）
5. `GET /agent-api/tasks`（无 token）→ 401 `auth_required`（闸机不受影响）
6. `nginx -t` 通过后 `-s reload`

浏览器层（IAB，验证码开启、答案经本机 Redis `captcha_codes:{uuid}` 读取）：

| # | 场景 | 结果 |
|---|---|---|
| 1 | 打开 `http://localhost/` | 自动落在 `http://localhost/agent-api/`，标题"云湃 AI"，登录闸机拦截 |
| 2 | user1 经 `/login` 登录（真实验证码） | 成功，落在若依 `/index`（登录标签页用后即关的既有形态） |
| 3 | 回操作台 | 闸机自动放行，身份 `user1 · 用户`，历史任务数据在 |
| 4 | 用户页管理入口 | 无 `#manageLink`（该按钮只存在于开发者控制台，符合设计） |
| 5 | 操作台"退出"按钮真实点击 | POST `/prod-api/logout` 吊销会话，回 `/login`（顺带补上 Phase 5 IAB 顶部按钮点不到的 UI 层空白，用户页按钮已人工路径验证） |
| 6 | dev1 登录 → `/agent-api/developer` | `#manageLink` 可见，href=`/index` |
| 7 | 点击"管理后台 ↗" | 新标签页打开 `http://localhost/index`（若依后台，标题"云湃 AI"） |

偏差记录（与 Phase 5 相同的 IAB 已知限制，非产品缺陷）：闸机"打开若依登录页"按钮的 `window.open` 被 IAB 拦截，走查用同标签页直接导航 `/login` 等价替代（cookie/轮询机制相同）；弹窗路径留人工走查。

## 复现

```powershell
D:\ruoyi-env\start-env.cmd
D:\ruoyi-env\nginx\nginx.exe        # 配置已含 location = / 302
cd /d "D:\my new work\cloud-flowing_0806"
cmd /c "set RUOYI_LOGOUT_URL=/prod-api/logout&& set RUOYI_MANAGE_URL=/index&& set MODEL_PROVIDER=mock&& .venv\Scripts\python.exe -m agent_platform.cli serve"
# 浏览器访问 http://localhost/ → 自动到操作台；登录页标题"云湃 AI"
```

## 追加（同日）：SPA 入口禁用启发式缓存

用户反馈"浏览器标题还是旧的"——nginx 静态 HTML 无 `Cache-Control` 时浏览器按启发式缓存旧 `index.html`（`/` 旧页面可直接来自本地缓存、不回源）。按用户确认，两份 nginx 各新增：

```nginx
location = /index.html {
    limit_req zone=gateway burst=60 nodelay;
    add_header Cache-Control "no-cache";          # 本地版
    # 部署包版额外重复三条安全头（add_header 在 location 级取消 server 级继承）
}
```

- 实测（本地）：`/login`、`/system/user`、`/index.html` 响应均带 `Cache-Control: no-cache`（try_files 回退经内部重定向落入 exact location）；哈希命名的 `/static/js/chunk-libs.*.js` 等资源无该头，保持启发式长缓存（文件名含内容哈希，重建即换名，无陈旧风险）。
- 部署包配置经 Windows 路径适配副本 `nginx -t` 通过（Phase 6 同法；证书用临时自签对，路径替换 root/mime/logs/pid）。
- 注意：`no-cache` 是"每次回源校验"（304 响应），不是禁存；改版后浏览器立即拿新入口页。存量旧缓存标签页仍需一次强刷（Ctrl+F5）。
- 同日追加（用户提出"登录后直达 agent"）：闸机 `check()` 成功路径新增 `loginWindow?.close()`——登录弹窗是本方脚本 `window.open` 打开的，令牌探测有效即自动关闭，用户不再看到弹窗内若依登录后跳转的管理首页（若依前端内部行为，未动其源码）。`node --check` 通过；curl 确认线上 app.js 已含新代码。IAB 拦 `window.open`，弹窗自动关闭留真实浏览器人工复验（弹窗路径本身 Phase 4 已验证）。

## 追加（同日）：修复语音播放 401（Phase 3 网关遗留缺陷）

用户实测报错 `ZipVoice · Failed to load because no supported source was found.`。定位（nginx access.log 铁证）：

```
POST /agent-api/tasks/1ba40275-*/speech        201   ← 合成成功（API.post 带令牌）
GET  /agent-api/tasks/1ba40275-*/speech/{ver}   401   ← <audio src> 播放，元素带不了 Authorization 头
```

**根因**：Phase 3 把语音端点关进 JWT 门后，SSE 按契约 §8 改成 fetch 流，但 `<audio>` 元素直连 audio_url 的播放路径漏改；Phase 4/5 走查矩阵未含语音播放（语音冒烟排期 Phase 7），缺陷潜伏至今。本次由用户人工测试触发。

**修复**（`agent_platform/static/app.js` `playTaskSpeech`）：与 SSE 同构——带 `Authorization` 头 fetch 音频为 blob，`URL.createObjectURL` 后交给 audio 元素播（替换前 `revokeObjectURL` 旧 URL；令牌不进 URL，符合契约 §8 精神；端点仍服务端校验会话，满足"音频读取必须再次校验会话权限"不变式）。

**验证**：IAB 真实浏览器端到端——dev1 会话提交 mock 任务（ea4dbba7，201+SSE+待办卡片）→ 点播放 → 状态行 `ZipVoice · news-female1 · 4.2 秒 · 24000 Hz`、停止按钮启用（真实播放中）→ 4.2 秒自然播完触发 ended 复位；nginx 日志同请求形态 `GET .../speech/{ver} 200 204016`（对照修复前 401）。`node --check` 通过。


## 遗留与关联

- 板端复验（302、`/login`、管理按钮、标题）并入 Phase 7 验收走查。
- 登录页深度定制（agent 内置登录卡片，中量档）未做：按用户决定先落地轻量档，后续按真实用户反馈再立项；若启动需修订 Phase 4 冻结的"弹窗到若依登录页"机制并在 TASK.md Decisions 记录。
