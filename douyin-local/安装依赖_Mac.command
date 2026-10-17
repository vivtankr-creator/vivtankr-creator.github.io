#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
trap 'echo "[FAIL] 安装未完成。请保留此窗口中的非敏感错误，修复后重新运行。"; read -r -p "按回车关闭" _' ERR
bash './检查Mac环境.command'
echo '将安装：独立 uv 0.9.4、托管 Python 3.12、锁定依赖、Chromium。无需 Xcode 或现有 Python。'
echo '工具保存在 ~/Library/Application Support/DouyinLocal/tools，Python 和浏览器使用各自用户缓存。'
read -r -p '同意下载并安装？输入 INSTALL：' consent
if [ "$consent" != INSTALL ]; then echo '未安装'; exit 0; fi
arch=$(uname -m)
case "$arch" in arm64) target=aarch64-apple-darwin;; x86_64) target=x86_64-apple-darwin;; esac
tools="$HOME/Library/Application Support/DouyinLocal/tools"
mkdir -p "$tools"
chmod 700 "$tools"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
asset="uv-$target.tar.gz"
base='https://github.com/astral-sh/uv/releases/download/0.9.4'
curl --fail --location --proto '=https' --tlsv1.2 "$base/$asset" -o "$tmp/$asset"
curl --fail --location --proto '=https' --tlsv1.2 "$base/$asset.sha256" -o "$tmp/checksum"
expected=$(awk '{print $1}' "$tmp/checksum")
actual=$(shasum -a 256 "$tmp/$asset" | awk '{print $1}')
if [ "$expected" != "$actual" ]; then echo '[FAIL] uv 校验和不匹配'; exit 1; fi
tar -xzf "$tmp/$asset" -C "$tmp"
install -m 700 "$tmp/uv-$target/uv" "$tools/uv"
"$tools/uv" python install 3.12
"$tools/uv" sync --locked --no-dev --python 3.12
"$tools/uv" run --locked --no-dev python -m playwright install chromium
chmod u+x './启动抖音合集下载.command' './检查Mac环境.command'
echo '[OK] 依赖安装完成。真实下载尚未验证。请双击 启动抖音合集下载.command'
read -r -p '按回车关闭' _
