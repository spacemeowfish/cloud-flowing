"""RUOYI-AUTH-GATEWAY-001 Phase 6：PC 侧部署包组装脚本。

把仓库源码（git archive，天然不含 .env/密钥）+ 仓库外若依资产（jar/SQL/前端 dist）
组装成 `ruoyi-gateway-bundle.tar.gz`，供板端 install.sh 使用。

用法（开发机，本仓库根目录的 venv）:
    .venv/Scripts/python.exe deployment/ruoyi-gateway/pack_deploy.py
    .venv/Scripts/python.exe deployment/ruoyi-gateway/pack_deploy.py --ruoyi-env D:/ruoyi-env --output D:/out/bundle.tar.gz

默认从 ``D:/ruoyi-env`` 取：
    RuoYi-Vue\\ruoyi-admin\\target\\ruoyi-admin.jar
    RuoYi-Vue\\sql\\ry_20260417.sql、quartz.sql
    RuoYi-Vue2\\dist\\（前端生产构建）
"""

from __future__ import annotations

import argparse
import io
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

BUNDLE_MANIFEST = [
    "install.sh",
    "nginx/nginx.conf",
    "systemd/ruoyi.service",
    "systemd/agent-platform.service",
    "systemd/nginx-gateway-override.conf",
    "tls/gen-self-signed.sh",
    "ruoyi/ruoyi-admin.jar",
    "ruoyi/application.yml",
    "ruoyi/application-druid.yml",
    "ruoyi/sql/ry_20260417.sql",
    "ruoyi/sql/quartz.sql",
    "ruoyi/harden-roles.sql",
    "ruoyi-ui/",
    "agent-platform/",
    "docs/部署手册.md",
    "docs/安全验收清单.md",
]


def fail(message: str) -> "NoReturn":
    print(f"[pack] 错误：{message}", file=sys.stderr)
    raise SystemExit(1)


def run_git_archive(repo: Path) -> io.BytesIO:
    proc = subprocess.run(
        ["git", "-C", str(repo), "archive", "--format=tar", "HEAD"],
        capture_output=True,
        check=True,
    )
    return io.BytesIO(proc.stdout)


def copy_tree(src: Path, dst: Path) -> None:
    dst.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        target = dst / item.name
        if item.is_dir():
            shutil.copytree(item, target, dirs_exist_ok=True)
        else:
            shutil.copy2(item, target)


def main() -> None:
    parser = argparse.ArgumentParser(description="组装 ruoyi-gateway 部署包")
    parser.add_argument("--ruoyi-env", default=r"D:\ruoyi-env", help="若依环境目录（jar/SQL/dist）")
    parser.add_argument("--output", default=None, help="输出 tar.gz 路径（默认 deployment/ruoyi-gateway/dist/）")
    args = parser.parse_args()

    pkg_dir = Path(__file__).resolve().parent
    repo = pkg_dir.parent.parent
    env = Path(args.ruoyi_env)

    jar = env / "RuoYi-Vue" / "ruoyi-admin" / "target" / "ruoyi-admin.jar"
    sql_main = env / "RuoYi-Vue" / "sql" / "ry_20260417.sql"
    sql_quartz = env / "RuoYi-Vue" / "sql" / "quartz.sql"
    dist = env / "RuoYi-Vue2" / "dist"
    for required in (jar, sql_main, sql_quartz, dist):
        if not required.exists():
            fail(f"缺少仓库外资产：{required}（先构建若依后端/前端，或指定 --ruoyi-env）")

    out = Path(args.output) if args.output else pkg_dir / "dist" / "ruoyi-gateway-bundle.tar.gz"
    out.parent.mkdir(parents=True, exist_ok=True)

    staging = pkg_dir / "dist" / "bundle-staging"
    if staging.exists():
        shutil.rmtree(staging)
    (staging / "ruoyi" / "sql").mkdir(parents=True)

    # ① 部署包自身文件
    shutil.copy2(pkg_dir / "install" / "install.sh", staging / "install.sh")
    copy_tree(pkg_dir / "nginx", staging / "nginx")
    copy_tree(pkg_dir / "systemd", staging / "systemd")
    copy_tree(pkg_dir / "tls", staging / "tls")
    (staging / "install" / "ruoyi").mkdir(parents=True, exist_ok=True)
    shutil.copy2(pkg_dir / "install" / "ruoyi" / "application.yml", staging / "install" / "ruoyi" / "application.yml")
    shutil.copy2(pkg_dir / "install" / "ruoyi" / "application-druid.yml", staging / "install" / "ruoyi" / "application-druid.yml")
    (staging / "docs").mkdir(exist_ok=True)
    for doc in ("部署手册.md", "安全验收清单.md"):
        shutil.copy2(pkg_dir / doc, staging / "docs" / doc)

    # ② 若依资产（仓库外）
    shutil.copy2(jar, staging / "ruoyi" / "ruoyi-admin.jar")
    shutil.copy2(sql_main, staging / "ruoyi" / "sql" / "ry_20260417.sql")
    shutil.copy2(sql_quartz, staging / "ruoyi" / "sql" / "quartz.sql")
    shutil.copy2(pkg_dir / "install" / "harden-roles.sql", staging / "ruoyi" / "harden-roles.sql")
    copy_tree(dist, staging / "ruoyi-ui")

    # ③ 仓库源码（仅 agent_platform 包与 pyproject，.env/密钥天然不含）
    archive = run_git_archive(repo)
    with tarfile.open(fileobj=archive, mode="r:") as tar:
        for member in tar.getmembers():
            if member.name.startswith("agent_platform/") or member.name == "pyproject.toml":
                tar.extract(member, path=staging / "agent-platform", filter="data")

    # ④ 打 tar.gz（顶层目录 ruoyi-gateway-bundle/）
    with tarfile.open(out, "w:gz") as tar:
        for item in sorted(staging.iterdir()):
            tar.add(item, arcname=f"ruoyi-gateway-bundle/{item.name}")

    size_mb = out.stat().st_size / 1024 / 1024
    print(f"[pack] 完成：{out}（{size_mb:.1f} MB）")
    print("[pack] 内容清单：")
    with tarfile.open(out, "r:gz") as tar:
        for name in sorted(tar.getnames()):
            print(f"  {name}")
    shutil.rmtree(staging)


if __name__ == "__main__":
    main()
