---
name: douyin-downloader
description: 操作本仓库 Mac 本地正式抖音合集下载工具，查询、确认、重试和导出原文元数据。
---

真实入口为 `douyin_local/web.py`，并非仅有说明文档。
在项目目录启动 `uv run --locked --no-sync python -m douyin_local.web`，或 Mac 双击启动脚本。
用户在自己的可见浏览器登录，输入任意单集链接，查看正式合集名称/ID/数量，明确确认后执行。
输出目录默认为 `~/Downloads/抖音合集下载/<mix_id>/`；`metadata.json` 即持久化清单及原文导出。
只对用户拥有或获得授权的公开作品操作；遇到 403、限流或验证必须暂停正常认证，不能绕过。
不得上传 Cookie 或视频到云端；不得把离线测试结果当作真实下载成功。
上游审计与 API 差异见 `docs/AUDIT.md`；Mac 验收见 `docs/MAC_ACCEPTANCE.md`。
