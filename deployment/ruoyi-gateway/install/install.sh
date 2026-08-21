#!/usr/bin/env bash
# RUOYI-AUTH-GATEWAY-001 Phase 6：板端一键安装（RK3588 / aarch64 / Ubuntu 24.04）
# 用法：cd 解压后的部署包目录 && sudo bash install.sh <公网IP或域名>
# 做哪些事：
#   1. apt 安装 JDK17/MySQL/Redis/nginx/openssl/python3(venv)/ufw/curl
#   2. 生成强随机密钥 → /etc/ruoyi-gateway/env（600 root；重复运行保留既有密钥）
#   3. MySQL 建库 ry-vue + 低权限账号 ry@127.0.0.1，导入若依 SQL + 生产加固 SQL
#   4. MySQL/Redis 强制只监听 127.0.0.1
#   5. 部署 jar + 若依外部配置（占位符注入密钥）+ 前端 dist + agent 源码 + venv
#   6. 生成自签证书（SAN=公网IP）、装 nginx 配置与 systemd 服务并启动
# 防火墙（ufw）规则本脚本只写不启用——SSH 远程执行时直接启用有锁死风险，
# 按《部署手册》第 7 节在确认 SSH 白名单后再执行 ufw enable。
set -euo pipefail

BUNDLE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PUBLIC_IP="${1:-}"

if [ "$(id -u)" -ne 0 ]; then
    echo "请用 root 运行：sudo bash install.sh <公网IP或域名>" >&2
    exit 1
fi
if [ ! -f "$BUNDLE_DIR/ruoyi/ruoyi-admin.jar" ]; then
    echo "找不到 $BUNDLE_DIR/ruoyi/ruoyi-admin.jar，请确认在部署包根目录运行。" >&2
    exit 1
fi
if [ "$(uname -m)" != "aarch64" ]; then
    echo "警告：当前架构 $(uname -m) 不是 aarch64，本包面向 RK3588；继续可能导致依赖不匹配。" >&2
fi

ENV_FILE=/etc/ruoyi-gateway/env
RUOYI_HOME=/opt/ruoyi
AGENT_HOME=/opt/agent-platform
UI_HOME=/var/www/ruoyi-ui

echo "== [1/9] 安装系统软件包（约几分钟）"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y openjdk-17-jre-headless mysql-server redis-server nginx openssl \
    python3 python3-venv python3-pip ufw curl || {
    echo "mysql-server 不可用，改试 mariadb-server"; apt-get install -y mariadb-server; }
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' || {
    echo "需要 Python 3.11+（本包要求，请使用 Ubuntu 24.04 或安装新版 Python）" >&2; exit 1; }

MYSQL_SVC=mysql
systemctl list-unit-files | grep -q '^mysql\.service' || MYSQL_SVC=mariadb

echo "== [2/9] 生成密钥文件 $ENV_FILE（已存在则保留原密钥）"
mkdir -p /etc/ruoyi-gateway
if [ ! -f "$ENV_FILE" ]; then
    JWT_SECRET="$(openssl rand -base64 96 | tr -d '\n')"
    DB_PASSWORD="$(openssl rand -hex 16)"
    cat > "$ENV_FILE" <<EOF
# RUOYI-AUTH-GATEWAY-001 板端环境（0600 root）。若依后端与 agent_platform 共享读取。
# 修改后执行 systemctl restart ruoyi agent-platform 生效。密钥泄露即重生成。
RUOYI_JWT_SECRET=$JWT_SECRET
RUOYI_REDIS_URL=redis://127.0.0.1:6379/0
# 网关拓扑默认值：登录页同源 /#/login，登出走 /prod-api/logout（留空/缺省即默认）
RUOYI_LOGOUT_URL=/prod-api/logout
# 模型：板上 RKLLM 厂商服务（127.0.0.1:8080，见 deployment/rk3588 的 vendor server 说明）
MODEL_PROVIDER=rkllm
RKLLM_SERVER_URL=http://127.0.0.1:8080/v1
RKLLM_MODEL_NAME=rkllm
RKLLM_TIMEOUT_SECONDS=30
RKLLM_QUEUE_TIMEOUT_SECONDS=2
RKLLM_MAX_CONCURRENCY=1
RKLLM_MAX_CONTEXT=4096
RKLLM_MAX_NEW_TOKENS=512
AGENT_HOST=127.0.0.1
AGENT_PORT=8000
AGENT_DATABASE_PATH=/var/lib/agent-platform/agent_platform.db
AGENT_AUDIT_DIR=/var/log/agent-platform/audit
AGENT_AUTHORIZED_FILE_ROOTS=/var/lib/agent-platform/authorized_files
AGENT_KNOWLEDGE_ROOTS=/var/lib/agent-platform/knowledge
AGENT_MEETING_OUTPUT_DIR=/var/lib/agent-platform/meeting_notes
AGENT_FILE_OPEN_ENABLED=false
AGENT_NETWORK_AVAILABLE=true
AGENT_TIMEZONE=Asia/Shanghai
RUOYI_DB_PASSWORD=$DB_PASSWORD
EOF
    chmod 600 "$ENV_FILE"
    echo "密钥已生成：$ENV_FILE"
else
    echo "检测到已有 $ENV_FILE，保留原值（如要换密钥请删除后重跑）。"
fi
set -a; . "$ENV_FILE"; set +a

echo "== [3/9] MySQL 建库、建账号、导入 SQL"
systemctl enable --now "$MYSQL_SVC"
# 强制只监听回环
BIND_CNF=$(grep -l -m1 '^bind-address' /etc/mysql/mysql.conf.d/*.cnf /etc/mysql/mariadb.conf.d/*.cnf 2>/dev/null | head -1 || true)
if [ -n "${BIND_CNF:-}" ]; then
    sed -i 's/^bind-address.*/bind-address = 127.0.0.1/' "$BIND_CNF"
else
    echo "bind-address = 127.0.0.1" >> /etc/mysql/mysql.conf.d/mysqld.cnf 2>/dev/null || true
fi
systemctl restart "$MYSQL_SVC"

mysql -uroot <<SQL
CREATE DATABASE IF NOT EXISTS \`ry-vue\` DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci;
CREATE USER IF NOT EXISTS 'ry'@'127.0.0.1' IDENTIFIED BY '$RUOYI_DB_PASSWORD';
GRANT ALL PRIVILEGES ON \`ry-vue\`.* TO 'ry'@'127.0.0.1';
FLUSH PRIVILEGES;
SQL
mysql -uroot --default-character-set=utf8mb4 ry-vue < "$BUNDLE_DIR/ruoyi/sql/ry_20260417.sql"
mysql -uroot --default-character-set=utf8mb4 ry-vue < "$BUNDLE_DIR/ruoyi/sql/quartz.sql"
mysql -uroot ry-vue < "$BUNDLE_DIR/ruoyi/harden-roles.sql"
echo "MySQL 就绪：库 ry-vue（账号 ry@127.0.0.1），普通角色菜单已清空。"

echo "== [4/9] Redis 只监听回环"
sed -i 's/^bind .*/bind 127.0.0.1/' /etc/redis/redis.conf
grep -q '^bind ' /etc/redis/redis.conf || echo "bind 127.0.0.1" >> /etc/redis/redis.conf
systemctl enable --now redis-server

echo "== [5/9] 部署文件与目录"
id -u ruoyi &>/dev/null || useradd --system --no-create-home --shell /usr/sbin/nologin ruoyi
id -u agent &>/dev/null || useradd --system --no-create-home --shell /usr/sbin/nologin agent
mkdir -p "$RUOYI_HOME" "$AGENT_HOME" "$UI_HOME" \
    /var/lib/agent-platform/{data,audit,authorized_files,knowledge,meeting_notes} \
    /var/log/agent-platform "$RUOYI_HOME/uploadPath"

install -o ruoyi -g ruoyi -m 644 "$BUNDLE_DIR/ruoyi/ruoyi-admin.jar" "$RUOYI_HOME/ruoyi-admin.jar"

substitute() {  # 用 Python 做占位符替换（密钥含 base64 特殊字符，sed 不可靠）
    python3 - "$1" "$2" <<'PYEOF'
import sys
src, dst = sys.argv[1], sys.argv[2]
env = {}
for line in open("/etc/ruoyi-gateway/env", encoding="utf-8"):
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        env[k] = v
text = open(src, encoding="utf-8").read()
for name in ("RUOYI_JWT_SECRET", "RUOYI_DB_PASSWORD"):
    text = text.replace("__" + name + "__", env[name])
open(dst, "w", encoding="utf-8").write(text)
PYEOF
}
substitute "$BUNDLE_DIR/install/ruoyi/application.yml" "$RUOYI_HOME/application.yml"
substitute "$BUNDLE_DIR/install/ruoyi/application-druid.yml" "$RUOYI_HOME/application-druid.yml"
chown ruoyi:ruoyi "$RUOYI_HOME/application.yml" "$RUOYI_HOME/application-druid.yml"
chmod 600 "$RUOYI_HOME/application.yml" "$RUOYI_HOME/application-druid.yml"   # 含数据库口令，仅服务用户可读

cp -a "$BUNDLE_DIR"/ruoyi-ui/. "$UI_HOME"/
cp -a "$BUNDLE_DIR"/agent-platform/. "$AGENT_HOME"/
chown -R ruoyi:ruoyi "$RUOYI_HOME"
chown -R agent:agent "$AGENT_HOME" /var/lib/agent-platform /var/log/agent-platform
chmod 750 /var/lib/agent-platform /var/log/agent-platform

echo "== [6/9] agent_platform 虚拟环境与依赖（约几分钟）"
python3 -m venv "$AGENT_HOME/venv"
"$AGENT_HOME/venv/bin/pip" install --no-cache-dir "$AGENT_HOME"

echo "== [7/9] 自签证书与 nginx"
if [ -z "$PUBLIC_IP" ]; then
    echo "未提供公网 IP/域名，稍后请手动执行：sudo bash $BUNDLE_DIR/tls/gen-self-signed.sh <公网IP或域名>"
else
    bash "$BUNDLE_DIR/tls/gen-self-signed.sh" "$PUBLIC_IP"
fi
[ -f /etc/nginx/nginx.conf ] && cp /etc/nginx/nginx.conf "/etc/nginx/nginx.conf.bak.$(date +%s)"
install -m 644 "$BUNDLE_DIR/nginx/nginx.conf" /etc/nginx/nginx.conf
nginx -t

echo "== [8/9] systemd 服务与开机自启"
install -m 644 "$BUNDLE_DIR/systemd/ruoyi.service" /etc/systemd/system/ruoyi.service
install -m 644 "$BUNDLE_DIR/systemd/agent-platform.service" /etc/systemd/system/agent-platform.service
mkdir -p /etc/systemd/system/nginx.service.d
install -m 644 "$BUNDLE_DIR/systemd/nginx-gateway-override.conf" /etc/systemd/system/nginx.service.d/gateway.conf
systemctl daemon-reload
systemctl enable ruoyi agent-platform nginx

echo "== [9/9] 启动服务"
systemctl restart ruoyi agent-platform
sleep 5
systemctl restart nginx
sleep 5
systemctl --no-pager --lines=0 is-active ruoyi agent-platform nginx "$MYSQL_SVC" redis-server

echo
echo "安装完成。防火墙规则已准备但未启用（避免远程 SSH 锁死）："
echo "  ufw allow 443/tcp"
echo "  ufw allow from <你的内网网段> to any port 22"
echo "  ufw enable    # 确认上面两条后再执行，见《部署手册》第 7 节"
echo
echo "下一步（《部署手册》第 5、6 节）："
echo "  1. 浏览器打开 https://$PUBLIC_IP（自签证书选继续访问）"
echo "  2. admin/admin123 登录并立即修改密码"
echo "  3. 角色管理新建 developer 角色（角色权限字符串=developer），给账号分配角色"
echo "  4. 用《安全验收清单》逐条验收"
echo "日志排查：journalctl -u ruoyi -e / journalctl -u agent-platform -e / journalctl -u nginx -e"
