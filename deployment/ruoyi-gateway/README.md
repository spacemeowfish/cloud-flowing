# deployment/ruoyi-gateway —— 若依认证网关部署包（RUOYI-AUTH-GATEWAY-001 Phase 6）

板端（RK3588，aarch64，Ubuntu 24.04）部署交付物。全部面向"不懂原理的执行者"：照《部署手册》按顺序执行即可。PC 证据到此为止，板端结论只由 Phase 7 验收产生（`docs/tasks/2026-08-20-ruoyi-auth-gateway-plan.md` 第 3 节证据分级）。

## 交付物清单

| 文件 | 用途 | 在板上的位置 |
|---|---|---|
| `nginx/nginx.conf` | 最终网关配置：443 + 三条转发 + 登录端点限流 + 安全头 + HTTP→HTTPS 跳转 | `/etc/nginx/nginx.conf` |
| `systemd/ruoyi.service` | 若依后端（JDK 17 起 jar） | `/etc/systemd/system/ruoyi.service` |
| `systemd/agent-platform.service` | agent_platform FastAPI（JWT 闸机） | `/etc/systemd/system/agent-platform.service` |
| `systemd/nginx-gateway-override.conf` | nginx 依赖顺序（在 ruoyi/agent 之后启动） | `/etc/systemd/system/nginx.service.d/gateway.conf` |
| `install/install.sh` | 板端一键安装（装软件、建库导 SQL、生成密钥、装服务） | 解压后根目录运行一次 |
| `install/ruoyi/application.yml`、`application-druid.yml` | 若依外部配置模板（只改配置不改源码；密钥用占位符注入） | `/opt/ruoyi/` |
| `install/harden-roles.sql` | 生产加固：清空内置"普通角色"的菜单绑定 | 安装时自动执行 |
| `tls/gen-self-signed.sh` | 自签证书一键脚本（SAN=公网 IP，证书路线已冻结为自签） | `/etc/ruoyi-gateway/tls/` |
| `pack_deploy.py` | **PC 侧**组装脚本：把仓库源码 + 若依 jar/SQL/前端 dist 打成 tar.gz | 在开发机运行 |
| `部署手册.md` | 裸机板子 → 可访问的每一步命令 | 随包一起传上板 |
| `安全验收清单.md` | 计划第 7 节五条门禁，逐条附验证命令 | 随包一起传上板 |

## 依赖的仓库外资产（打包时由 pack_deploy.py 从本机 `D:\ruoyi-env` 取）

- `D:\ruoyi-env\RuoYi-Vue\ruoyi-admin\target\ruoyi-admin.jar`（PC 已构建）
- `D:\ruoyi-env\RuoYi-Vue\sql\ry_20260417.sql`、`quartz.sql`
- `D:\ruoyi-env\RuoYi-Vue2\dist\`（前端生产构建）
- 仓库自身源码（`git archive`，`.env`/secrets 天然不含）

## 验证状态

- Phase 6 走查（PC）：`bash -n` 全部脚本语法通过；nginx 配置经本机 nginx 1.30.4 `-t` 语法校验通过（临时目录适配）；`pack_deploy.py` 实际组装出 tar.gz 并逐项核对内容（证据 `docs/tasks/2026-08-21-phase6-deploy-package.md`）。
- 板端真实安装/运行：Phase 7 由部署人按《部署手册》执行后验收。
- 旧的 `deployment/rk3588/` PoC 材料中 `DEVELOPER_PASSWORD` 引用已随本 Phase 清理（Phase 3 决策遗留）；RKLLM 厂商服务等 PoC 内容不在本包范围。
