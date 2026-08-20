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

- [ ] Phase 1 本地跑通若依：JDK 17 + MySQL 8 + Redis + Node 18 环境就绪；能在若依界面建用户/分角色（普通用户、developer）；F12 可见 Bearer 三段式 JWT。
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

## Completed

- Phase 0（2026-08-20）：计划文档第 8 节答案回填并同步正文（账户分离含义、Phase 3 会话映射按账号隔离、Phase 6 证书脚本定自签）；`PRE-DELIVERY-FIXES-001` 归档补齐至 `docs/tasks/2026-08-19-pre-delivery-fixes.md`；本 TASK.md 建立；PROJECT.md 认证模型描述修订。

## 前置任务暂缓项（SMOKE-DEMO-FIXES-001 遗留，2026-08-20 用户决定暂不实施）

- 人工冒烟剩余项：ASR 连续两段转写拼接（S5 前端，需真机麦克风）；如演示需真实打开文件，本地 `.env` 置 `AGENT_FILE_OPEN_ENABLED=true` 重启 desktop（已知 FIXPLAN D1 风险由演示负责人决定）。
- desktop 模式全量人工冒烟清单：待 PR #10 合并后人工执行。
- 澄清挂起 + resume、三闸门收敛、FIXPLAN 批次 D：按 SMOKE-FIXPLAN"范围外"另立任务。

## Pending

- Phase 1～7 全部未开始（逐项见 Acceptance scenarios）。

## Next step

- Phase 1：PC 安装 JDK 17、MySQL 8、Redis、Node.js 18+，本地跑通若依（clone RuoYi-Vue `springboot3` 分支、建库导 SQL、配置 `application-druid.yml`/`application.yml`、启动前后端、建"普通用户/developer"角色与测试账号、立即改 admin 默认密码、F12 确认 Bearer token）。启动前先生成强随机 `token.secret`（环境变量思路，不入库），为 Phase 3 复用做准备。

## Verification

- [x] Phase 0（2026-08-20，纯文档变更）：`node .ai-team/check.mjs --base origin/main` 通过（Result: valid）；全量 `pytest -q -p no:cacheprovider` 474 项全部通过（分支自 origin/main `a19f3c4`，无代码变更，作基线留证；系统 pytest-current 临时目录权限故障，改用 `--basetemp` 独立目录运行）。
- [ ] Phase 1 起各 Phase 验收证据逐项补录。

## Handoff note

- From: `ZCode`
- To: `spacemeowfish/reviewer`
- Summary: Phase 0 立项完成——计划文档第 8 节 12 题答案回填（1～3 暂缓至部署期、自签证书路线选定、数据按账号隔离），TASK.md/PROJECT.md 建立或修订，PRE-DELIVERY 归档补齐，冒烟任务未完成项以"前置任务暂缓项"并入本文件保留。下一动作：Phase 1 本地跑通若依。
