# Current Task

- ID: `PC-ROLE-UI-001`
- Title: `精简用户界面与开发者控制台分离`
- Status: `handoff`
- Owner: `Codex`
- Next owner: `spacemeowfish/reviewer`

## Goal

为 RK3588 开发板演示提供两种简单界面：普通用户免登录使用通用任务入口，开发者通过仓库外环境变量密码进入现有完整控制台。复用现有任务 API、SSE 生命周期、确认、取消和结果能力，不建设完整商业认证、用户管理或 RBAC 系统。

TTS、ASR 和唤醒词不在本任务中修改；本功能完成后再继续真实模型验收与 TTS 音质评估。

## Acceptance scenarios

- [x] `/` 仅显示通用任务入口、真实阶段进度、近期任务、确认、取消、结果和错误。
- [x] 页面底部提供低干扰开发者入口，正确 `DEVELOPER_PASSWORD` 可进入 `/developer`，错误密码不能进入。
- [x] 未登录访问 `/developer`、`/admin/*`、完整能力信息、任务审计、日志和 Swagger/OpenAPI 被拒绝。
- [x] `X-Agent-Role` 和 `X-Session-Id` 不能伪造角色或浏览器任务会话。
- [x] 登录令牌和浏览器会话令牌仅保存在服务端内存/HttpOnly Cookie；登出或服务重启后开发者会话失效。
- [x] 普通用户仍可提交、查看、确认、取消自己的任务，接收 SSE 并读取自己的结果。
- [x] 开发者控制台保留当前任务、设置、工具契约、接口检查、审计、运行状态和手动退出。
- [x] 开发者可手动刷新最近最多 200 条内存脱敏日志；日志不包含秘密、Cookie、原始任务内容或本机绝对路径。
- [x] 默认监听 `127.0.0.1`；显式使用非回环地址时必须配置 `DEVELOPER_PASSWORD`，否则启动失败。
- [x] 桌面和移动视口的任务输入、阶段进度、确认区和结果区不重叠。

## Invariants

- 现有任务状态机、策略、确认、取消、幂等、审计、工具契约和会话数据隔离保持不变。
- 密码只从 Git 外的 `.env` 或系统环境变量读取，不写入前端、日志、API 响应或仓库默认值。
- 普通用户匿名使用；本次只存在 `user` 和 `developer` 两种界面模式，不代表完整多用户身份系统。
- 不实现自动降权、失败次数限制、锁定、登录审计、账户/角色数据库、CSRF 框架或持久会话数据库。
- 局域网访问仅面向受信任开发网络预览，不宣称生产级网络安全，也不允许默认公网暴露。
- TTS、ASR、唤醒词、真实模型质量和 RK3588 性能验收不因本任务改变结论。

## Decisions

- 开发者密码使用常量时间比较；成功后生成随机内存令牌并写入 HttpOnly、SameSite Cookie。
- 浏览器任务会话由服务端生成的 HttpOnly Cookie 标识，不再信任调用者提供的角色或会话请求头。
- 普通页和开发者页共享同一份前端任务/SSE/确认/结果实现，仅按页面模式呈现不同功能。
- 最近日志使用有界内存处理器，手动刷新，不增加日志 SSE、搜索、下载、清理或任意文件读取。
- RuoYi 仅借鉴普通界面与管理界面分离，不引入 Java、Shiro、MyBatis 或完整 RBAC。

## Completed

- 评测默认路径修复已由 PR #6 合并到 `main`，本分支从合并后的 `main` 创建。
- 已冻结本任务的精简范围、验收场景、不变量和架构决策。
- 已实现服务端开发者内存令牌、HttpOnly 浏览器会话、登录/退出/身份接口和统一开发者依赖。
- 已保护管理接口、完整能力信息、任务审计、日志和 Swagger/OpenAPI，并移除角色/会话请求头信任。
- 已拆分普通任务页与 `/developer` 完整控制台，两者复用任务、SSE、确认、结果、TTS 和语音逻辑。
- 已实现最近 200 条有界脱敏内存日志及手动刷新页面。
- 已增加非回环监听密码门禁，并同步 PC、RK3588 systemd/容器示例与使用说明。
- 已在真实浏览器提交任务、完成开发者登录/退出、查看日志并验证服务重启后的令牌失效。

## Pending

- 等待仓库所有者审查、CI 和合并。
- 合并后继续真实模型验收与 TTS 音质评估；TTS、ASR 和唤醒词代码未在本任务修改。

## Next step

提交并推送 `codex/role-based-ui`，创建 PR 交由仓库所有者审查；合并后从最新 `main` 启动真实模型验收与 TTS 音质评估。

## Verification

- [x] 聚焦 API、设置、日志、语音、TTS 和 RK3588 测试：43 项通过
- [x] `.\\.venv\\Scripts\\python.exe -m pytest --collect-only -q -p no:cacheprovider`：收集 419 项
- [x] `.\\.venv\\Scripts\\python.exe -m pytest -q -p no:cacheprovider`：419 项通过
- [x] `.\\.venv\\Scripts\\python.exe -m compileall -q agent_platform evaluation deployment packaging scripts`
- [x] `node --check agent_platform/static/app.js`
- [x] `git diff --check`
- [x] `node .ai-team/check.mjs --base origin/main`
- [x] 浏览器桌面视口：普通任务提交、七阶段、结果、登录、控制台、日志和退出通过，无控制台错误
- [x] 浏览器 `390x844`：页面 `scrollWidth=375`，输入、按钮、进度、结果和开发者控制台无页面级横向溢出
- [x] 服务重启：旧开发者 Cookie 失效，`/developer` 重定向回普通页重新登录

## Handoff note

- From: `Codex`
- To: `spacemeowfish/reviewer`
- Summary: 已完成精简 `user/developer` 双界面、内存开发者会话、服务端浏览器会话、受保护开发接口、脱敏日志和 RK3588 配置门禁；聚焦 43 项与全量 419 项通过，桌面/移动真实浏览器验收通过。请重点审查 Cookie 授权边界、普通页共享任务逻辑和板端容器密码传递；本 PR 不包含 TTS、ASR、唤醒词或真实模型质量改动。
