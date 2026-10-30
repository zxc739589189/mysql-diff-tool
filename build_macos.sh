#!/usr/bin/env bash
# ===== MySQL 数据对比工具 - macOS 打包脚本 =====
set -e
cd "$(dirname "$0")"

echo "[1/2] 安装依赖 ..."
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt pyinstaller

echo "[2/2] 开始打包 ..."
pyinstaller --noconfirm --clean MySQLDiffTool.spec

echo ""
echo "===== 打包完成！应用位于 dist/MySQLDiffTool.app ====="
echo "首次运行如被 Gatekeeper 拦截（未签名应用），执行："
echo "    xattr -cr dist/MySQLDiffTool.app"
