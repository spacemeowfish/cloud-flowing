# Phase 6 部署包产出：走查记录（PC 证据）

- 任务：`RUOYI-AUTH-GATEWAY-001` Phase 6
- 日期：2026-08-21
- 证据级别：**PC 证据**（交付物在 PC 上完成并通过语法/组装走查）；板端真实安装运行属 Phase 7 验收
- 交付物目录：`deployment/ruoyi-gateway/`（索引见其 `README.md`）

## 交付物（对照计划 Phase 6 节六项）

| 计划要求 | 交付物 |
|---|---|
| nginx.conf 最终配置（443 + 三条转发 + 限流） | `nginx/nginx.conf`：443 + 80→301 跳转、`/` 静态（history 回退）、`/prod-api/`→8080（前缀剥离）、`/agent-api/`→8000（前缀剥离 + SSE 非缓冲 + 3600s 读超时）；限流收敛到登录端点（`zone=login 10r/m burst=5` 挂 `location = /prod-api/login`）+ 全站基线（30r/s burst=60，沿用 Phase 5 实测值）；安全头（nosniff/SAMEORIGIN/referrer-policy）；家宽封 443 时改 8443 的注释指引 |
| systemd unit ×3 + 开机自启 | `systemd/ruoyi.service`（JDK17，-Xms512m -Xmx1024m，After=mysql/redis，Restart=always）、`systemd/agent-platform.service`（venv `cli serve`，After=ruoyi/redis，EnvironmentFile 共享密钥）、`systemd/nginx-gateway-override.conf`（nginx 依赖顺序 drop-in，装到 `/etc/systemd/system/nginx.service.d/`） |
| 安装脚本（ARM64 安装、SQL 导入、环境变量模板） | `install/install.sh`：apt 装 JDK17/MySQL(或 mariadb 回退)/Redis/nginx/openssl/python3.11+/ufw；`openssl rand` 生成强随机 `RUOYI_JWT_SECRET`(128 字符 base64) 与 DB 口令 → `/etc/ruoyi-gateway/env`(600 root，重跑保留)；MySQL 建库 `ry-vue` + 低权限账号 `ry@127.0.0.1` + 导入 ry_20260417/quartz + `harden-roles.sql`；MySQL/Redis 强制 bind 127.0.0.1；若依外部配置模板（`application.yml`/`application-druid.yml`，占位符经 Python 注入，规避 base64 特殊字符 sed 陷阱）；前端 dist → `/var/www/ruoyi-ui`；agent 源码 + venv（`pip install .`，与 PoC 容器同基线）；装 systemd + `systemctl enable`；ufw 规则只写不启用（防远程 SSH 锁死，手册第 7 节手动 enable） |
| 自签证书脚本 | `tls/gen-self-signed.sh`：openssl RSA3072、SAN=IP（IP 自动识别，域名走 DNS）、有效期默认 10 年、key 600；证书路线冻结为自签（计划第 8 节问题 10） |
| 部署手册 | `部署手册.md`：9 节——准备清单、PC 打包、传包、一键安装、路由器端口映射（含家宽封 80/443 → 8443 预案）、首次登录改密与角色/账号建设（roleKey=developer 必须一字不差）、部署人自测、防火墙顺序（先放行后 enable）、常见问题、运维速查；DDNS 预留一句（动态 IP 属部署期问题，计划第 8 节问题 1） |
| 安全验收清单 | `安全验收清单.md`：计划第 7 节五条逐条附验证命令（外网 curl 301/telnet 不通、netstat 回环绑定、admin123 失效、captchaImage=true + maxRetryCount=5 + nginx 登录限流、板上直连 8000 全 401），附 Phase 7 追加项（free -h、重启自愈、带认证语音冒烟、禁用两步剧本） |

## 设计决策（本 Phase 新增，已同步 TASK.md）

1. **限流收敛到登录端点**（Phase 5 决策的落实）：`limit_req zone=login rate=10r/m burst=5 nodelay` 只作用于 `location = /prod-api/login`；配合若依内置 `user.password.maxRetryCount=5 / lockTime=10`（配置模板保留原值）双层防爆破。
2. **Druid 监控控制台关闭**：`application-druid.yml` 模板 `statViewServlet.enabled: false`（默认口令 ruoyi/123456 的公网风险，属"只改配置"范围）。
3. **普通角色菜单清空**（Phase 2 预发现的安全待办落实）：`harden-roles.sql` 删除 `sys_role_menu WHERE role_id=2`，普通用户登录若依只见首页；业务入口在 `/agent-api/`，与若依菜单无关。
4. **密钥注入机制**：若依 `application.yml` 外部化覆盖 jar 内配置（Spring Boot 机制），`token.secret` 用 `${RUOYI_JWT_SECRET}`→占位符由 install.sh 经 Python 替换（base64 特殊字符不能用 sed）；`/opt/ruoyi/*.yml` 收紧为 600。
5. **MySQL 低权限账号**：不再用 root 跑业务，`ry@127.0.0.1` 只授 `ry-vue` 库。
6. **防火墙不自动启用**：install.sh 只提示命令，`ufw enable` 留手册第 7 节人工执行（远程部署防 SSH 锁死）。
7. **rk3588 旧材料清理**（Phase 3 决策遗留）：compose×2 移除 `DEVELOPER_PASSWORD: ${...:?...}` 必填项、docker/install.sh 移除密码必填校验与透传、benchmark_profiles.py 移除 env 透传与 main 校验、`.env.rk3588.example` 删除该变量并注明门已退役、README/两份 USAGE 文档改为指向若依网关。`deployment/rk3588/acceptance-checklist.md` 等 PoC 验收材料未动。

## 走查证据（PC，可复核）

- 脚本语法：`bash -n` 通过 ×3（install.sh、gen-self-signed.sh、rk3588/docker/install.sh）；`sh -n` 通过 rk3588 install.sh；`compileall deployment` OK（含修改后的 benchmark_profiles.py）。
- nginx 配置：本机 nginx 1.30.4 `nginx -t` 通过（`syntax is ok / test is successful`）。**校验方法说明**：Windows 上绝对路径按盘符解析，故以 sed 把 `/etc/...`、`/var/...` 路径改写为 `D:/ruoyi-env/nginx/...` 临时副本后校验（仅路径适配，指令语法原样）；"user" 指令在 Windows 被忽略的告警为平台差异，板上有效。
- 打包链路实跑：`pack_deploy.py` 从真实资产（`D:\ruoyi-env` 的 jar 86MB/SQL×2/dist + `git archive HEAD` 源码）组装出 `deployment/ruoyi-gateway/dist/ruoyi-gateway-bundle.tar.gz`（78.2 MB，dist/ 已 gitignore）；清单逐项核对：install.sh、nginx.conf、systemd×3、tls 脚本、jar、SQL×2、harden-roles.sql、ruoyi-ui 全量 dist、agent-platform 源码（含 pyproject.toml 与 static 前端）、docs×2 齐备。
- 模板注入实测：占位符替换函数在 PC 上以含 base64 特殊字符（`+/=`）的测试密钥运行，替换后无残留占位符、`yaml.safe_load` 解析通过。
- 包内卫生：tar 清单无 `.env`/密钥文件；模板在包内仍是 `__RUOYI_JWT_SECRET__` 占位符；包内检索不到 `D:\ruoyi-env\secrets` 真实密钥片段。

## 未验证项（板端，Phase 7）

- 真实 apt 安装与 MySQL 服务名差异（mysql/mariadb 回退逻辑未经真实板验证）；
- systemd 三个 unit 的真实启动与开机自启；
- 自签证书在浏览器端的实际表现（openssl `-addext` 需 openssl 3.x，Ubuntu 24.04 满足；PC 的 Git Bash openssl 1.0 不支持故未全链验证证书脚本，仅 `bash -n`）；
- 若依外部配置覆盖 jar 内配置的实机生效（Spring Boot 机制，Phase 1 PC 侧已用同机制跑通，板上未复测）；
- 公网拓扑、端口收敛、限流 503 实测（《安全验收清单》第 1/2/4 条的外网部分）。

## 复现

```powershell
# PC：组装部署包
cd /d "D:\my new work\cloud-flowing_0806"
.\.venv\Scripts\python.exe deployment/ruoyi-gateway/pack_deploy.py
# 板端（Phase 7）：解压后
tar -xzf ruoyi-gateway-bundle.tar.gz && cd ruoyi-gateway-bundle
sudo bash install.sh <公网IP>
# 然后照 docs/部署手册.md 第 5～7 节完成改密、建角色、防火墙与验收
```
