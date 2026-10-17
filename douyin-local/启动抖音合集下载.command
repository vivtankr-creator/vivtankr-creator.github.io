#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
if [ "$(uname -s)" != Darwin ]; then echo '[FAIL] 请在 Mac 运行'; exit 1; fi
tools="$HOME/Library/Application Support/DouyinLocal/tools"
if [ ! -x "$tools/uv" ] || [ ! -d .venv ]; then
  echo '请先运行 安装依赖_Mac.command'; read -r -p '按回车关闭' _; exit 1
fi
echo '仅启动本机 http://127.0.0.1:8080；关闭窗口或按 Ctrl+C 停止。'
echo '真实登录及下载测试需在此 Mac 完成；网页会打开默认浏览器。'
"$tools/uv" run --locked --no-sync --no-dev python -m douyin_local.web "$@"
