# 第一阶段验收报告

报告日期：2026-10-17（用户时区 Asia/Shanghai）。

- **Upstream pinned SHA**：`7ae3b47eed16a9a4fd88378cd985d8bf9619be89`。
- **Files changed**：`douyin_local/` 真实 Python 实现及本地 HTML；`tests/` 单元/集成/浏览器测试；`pyproject.toml`、`uv.lock`；三个 Mac `.command` 脚本；`README.md`、`docs/`；`.agents/skills/douyin-downloader/SKILL.md`；上游固定参考 `upstream/`。交付在现有仓库的独立 `douyin-local/` 子目录，附独立 CI。
- **Cloud automated test results**：33 项通过、0 跳过。包含原始文案和 nullable 标题、分享链接、正式合集不存在、分页合并/游标停滞、集序/去重、缺集统计、恢复/失败重试、不重复下载、损坏文件、路径边界、本地 Host/Origin/令牌、真实浏览器确认与 HTML 安全展示、默认浏览器自动打开、403/429 暂停、重定向拒绝、无 Cookie CDN 请求和实际 loopback HTTPS MP4 传输。测试输入为本地夹具及生成的视频；不是抖音网络成功证据。
- **Cloud code/static checks**：ruff 通过；Python compileall 通过；三个脚本分别 bash -n 通过；uv lock/sync --locked 通过。pytest 有 1 条第三方 Starlette/AnyIO 弃用警告，无失败。
- **F2 验证**：安装并导入 `f2==0.0.1.7`，真实执行 BaseDownloader.execute_tasks，使用受 TLS 校验保护的 HTTPX 客户端流传输生成的 MP4，经长度/ftyp/本环境 ffprobe 校验后保存。原 F2 默认传输与请求模型有安全和错误语义问题，已覆盖或不使用，细节见 AUDIT.md。未通过真实抖音 CDN 验证。
- **Mac package built**：no。交付源码、可双击脚本及源码 ZIP；Linux 未构建、签名、公证 `.app`/`.dmg`/`.pkg`。Apple Silicon 与 Intel 的 uv 0.9.4 发布 checksum 地址可访问，安装脚本分别选择对应架构；不能等同于在两种架构实机安装通过。
- **Tested on real Mac**：no，`not tested on Mac`。
- **Actual formal mix ID/episode count discovered**：unavailable。没有在云端调用抖音接口。
- **Real files downloaded**：untested。只生成/传输了本地测试视频，没有真实抖音视频。
- **Access limitations**：云端策略不允许抖音域名；Playwright 配套 Chromium 下载被代理明确拒绝，未绕过。UI 测试实际使用预装 `/usr/bin/chromium`。Mac 安装 Chromium 的下载步骤待实机验证。普通同源 detail/mix 请求可能被抖音拒绝，不能保证可替代其当前网页调用；若拒绝则暂停并记录未验收，不合成签名绕过。
- **Security limitations**：仅本机服务；随机请求令牌、Host/Origin 校验、单进程锁、无远端上传、私有浏览器资料目录；浏览器 Cookie 不转发 CDN，不支持需要额外凭证的媒体。没有 ffprobe 时只能做 MP4 签名/长度和重跑哈希检查，不保证完整解码。浏览器会话仍需用户保护本机账号。F2 传递依赖较旧。上游未提供 LICENSE，正式公开再分发前须澄清授权。
- **User actions left for Mac**：下载该分支源码 → 运行环境检查 → 阅读安装提示并输入 INSTALL → 双击启动 → 可见窗口登录 → 输入有权下载的单集链接 → 核对正式合集 → 确认下载 → 按 MAC_ACCEPTANCE.md 记录真实数量、播放、原文、顺序及重试结果。无需提供 Cookie。
- **Next stage**：只有真实下载验收通过后，实施番茄原文上传、字段映射及平台许可执行。

证据命令（项目目录）：

```bash
uv sync --locked
uv run --locked python -m pytest -q
uv run --locked ruff check douyin_local tests
uv run --locked python -m compileall -q douyin_local
for script in ./*.command; do bash -n "$script"; done
```

GitHub CI 的远程执行结果应以对应 Actions run 为准，本文云端结果来自当前 Codex 云工作区，不虚构未运行的远程 CI。
