#!/usr/bin/env bash
# RUOYI-AUTH-GATEWAY-001 Phase 6：自签证书一键脚本（证书路线已冻结为自签）
# 用法：sudo bash gen-self-signed.sh <公网IP或域名> [有效期天数，默认3650]
# 产物：/etc/ruoyi-gateway/tls/server.crt、server.key（key 权限 600）
set -euo pipefail

TARGET=${1:?用法: gen-self-signed.sh <公网IP或域名> [有效期天数]}
DAYS=${2:-3650}
OUT=/etc/ruoyi-gateway/tls

mkdir -p "$OUT"

if [[ "$TARGET" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    SAN="IP:$TARGET"
else
    SAN="DNS:$TARGET"
fi

openssl req -x509 -newkey rsa:3072 -nodes \
    -keyout "$OUT/server.key" -out "$OUT/server.crt" \
    -days "$DAYS" \
    -subj "/CN=$TARGET/O=cloud-flowing/OU=ruoyi-gateway" \
    -addext "subjectAltName=$SAN"

chmod 600 "$OUT/server.key"

echo "自签证书已生成：$OUT/server.crt"
echo "浏览器首次访问会提示"连接不是私密连接"——这是自签证书的预期现象，选择"高级→继续访问"即可（计划第 8 节问题 10：接受自签警告）。"
