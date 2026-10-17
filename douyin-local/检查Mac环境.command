#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
if [ "$(uname -s)" != Darwin ]; then echo '[FAIL] 请在 macOS 运行'; exit 1; fi
arch=$(uname -m)
case "$arch" in arm64|x86_64) ;; *) echo '[FAIL] 不支持的 CPU'; exit 1;; esac
version=$(sw_vers -productVersion)
major=${version%%.*}
if [ "$major" -lt 13 ]; then echo '[FAIL] 需要 macOS 13 或更新版本（Playwright Chromium）'; exit 1; fi
space=$(df -Pk "$HOME" | awk 'END {print $4}')
if [ "$space" -lt 5242880 ]; then echo '[FAIL] 请至少腾出 5 GiB 空间，再预留视频容量'; exit 1; fi
echo "[OK] macOS $version / $arch"
echo '[OK] 安装最少可用空间 5 GiB；下载前请按剧集容量另留空间'
for url in https://github.com https://pypi.org https://files.pythonhosted.org https://www.douyin.com; do
  if curl --connect-timeout 10 --max-time 20 -IsS "$url" >/dev/null; then echo "[OK] 可连接 $url"; else echo "[FAIL] 无法连接 $url"; exit 1; fi
done
echo '上述连接检查不代表抖音接口或下载已通过。'
