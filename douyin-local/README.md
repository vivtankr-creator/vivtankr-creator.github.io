# Mac 本地抖音合集批量下载

状态：**代码和离线验证已实现；not tested on Mac；真实抖音合集查询及下载尚未验证**。

输入合集任意一集的分享链接，查询正式合集及全部分页，确认后串行下载。逐集保留原始标题（平台未提供时为 null）和文案，持久化清单、校验文件、统计缺集、支持关闭后继续及失败重试。番茄视频上传不在本阶段范围内。

## 在 Mac 安装和启动

1. 下载本交付分支源码 ZIP 并解压，进入 `douyin-local` 文件夹。不要从旧的 `main` 分支下载。
2. 双击 `检查Mac环境.command`，要求 macOS 13+、Apple Silicon 或 Intel、至少 5 GiB 安装空间（视频另计），可连接 GitHub、PyPI、抖音及 Playwright 浏览器下载源。
3. 双击 `安装依赖_Mac.command`。阅读提示并输入 `INSTALL` 后才安装。脚本下载固定版本 uv、验证 SHA-256，安装独立 Python 3.12、锁定依赖和 Chromium，无需 Xcode、系统 Python 或 Homebrew。
4. 双击 `启动抖音合集下载.command`。默认浏览器打开 <http://127.0.0.1:8080>，终端需保持打开。
5. 点“打开抖音登录窗口”，在新出现的**可见 Chromium** 内正常扫码登录。不会读取或解密你现有 Chrome 的登录数据，不需要导出 Cookie。
6. 输入任意单集链接并查询，核对合集名、ID、总数、顺序。勾选授权及合集确认后开始。403、429 或验证码会停止后续下载，请正常登录/验证后明确点击重试。
7. 在进度表查看每集状态；“打开输出文件夹”进入 Finder。重启后可从历史任务继续。点击重试会跳过已通过校验的文件，重试失败和未完成的集数。

脚本未签名/未公证，未生成 `.app`、`.dmg` 或 Apple 安装包。若 macOS 阻止运行，请先查看源码，再按系统提供的单个文件“仍要打开”流程操作；不要全局关闭 Gatekeeper。若 ZIP 解压后没有执行权限，可在终端进入该文件夹运行：

```bash
chmod u+x ./*.command
bash ./安装依赖_Mac.command
```

安装失败时不要将其当成已安装：保留终端的非敏感错误信息。Playwright 的浏览器下载可能受网络限制，需要正常网络访问 `cdn.playwright.dev`、`playwright.download.prss.microsoft.com`。本项目不修改网络策略或绕过阻断。

## 输出和配置

默认路径：`~/Downloads/抖音合集下载/<mix_id>/`。目录按稳定的合集 ID 命名，避免合集改名后重复下载。

- `<aweme_id>_<可读文案>.mp4`：安全截断的文件名，不影响原文。
- `metadata.json`：每集 `aweme_id`、`original_title`、`original_description`、`source_url`、`mix_id`、`episode_order`、`local_file`、`download_status`、`error`、SHA-256、尝试次数；合集含 expected/discovered/downloaded/failed/missing 计数和完整性状态。
- `expected_count` 缺失时不会声称齐全；明确集序优先，否则保持平台分页顺序并显示依据。缺集可能来自权限、平台下架或接口变化，不能据此访问不可见作品。
- 先检查 HTTP 状态、长度、MP4 `ftyp`，若系统有 `ffprobe` 还会检查视频流；没有 ffprobe 时仅是签名及长度级验证，不能保证完整解码。重跑额外核对 SHA-256。文件级恢复会重新下载该集，不拼接未核实 Range 的残片。

更改目录或端口（终端进入项目目录后）：

```bash
bash ./启动抖音合集下载.command --output "$HOME/Movies/抖音合集" --port 8081
```

本机登录资料仅保存在 `~/Library/Application Support/DouyinLocal/browser/`，受私有目录权限和进程 umask 限制，不写入项目、stdout 或元数据，不发送到云端。下载 CDN 不接收浏览器 Cookie。某些需要额外鉴权的媒体可能因此不可下载；该情况保留失败并由实机验证确认，不扩大授权或绕过限制。

## 开发及云端验证

```bash
uv sync --locked
uv run --locked python -m pytest -q
uv run --locked ruff check douyin_local tests
bash -n ./*.command
uv run --locked python -m douyin_local.web --no-open
```

离线测试不需要抖音、Cookie 或账号。UI 测试使用系统 Chromium（`TEST_CHROMIUM` 可指定路径）；缺少时明确 skip。真实本机 HTTPS 测试使用临时可信证书和生成的视频，不访问抖音。

F2 固定为 0.0.1.7，实际调用其 BaseDownloader 执行器和客户端接口，严格传输覆盖原本吞异常、关闭 TLS 校验的行为。合集查询使用自己的可见浏览器页面正常同源接口及自身详情响应，不使用 F2 的合成指纹/签名请求模型。**F2 依赖可安装与离线传输通过，不代表抖音 CDN 真实可下载；正常同源分页接口是否接受当前会话也尚待 Mac 验证。**

更多证据见 [测试报告](docs/TEST_REPORT.md)、[上游审计](docs/AUDIT.md)、[Mac 实机验收](docs/MAC_ACCEPTANCE.md)。

## 卸载

停止终端中的程序，删除项目文件夹及其中 `.venv`。若要清除本工具登录状态和独立 uv，可在 Finder 删除 `~/Library/Application Support/DouyinLocal/`。视频单独保存在输出目录，按需删除。uv Python 缓存和 Playwright 浏览器缓存可能被其他应用共用，不自动移除；可通过 uv 的 `python dir`、`cache dir` 和 Playwright 文档确认路径后手动管理。

上游没有发现 LICENSE，已保留来源和固定提交记录；公开再分发前需要澄清上游授权。仅处理自己拥有或获授权的下载，遵守平台条款、限流及内容权限。
