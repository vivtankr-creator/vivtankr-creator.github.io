# 上游与 F2 审计

审计提交：`amibaren/douyin-DL-skills@7ae3b47eed16a9a4fd88378cd985d8bf9619be89`。
原始 `skills/` 与 AGENTS.md 保存在 upstream/ 作为固定源码参考。本地入口不导入上游 Cookie、日志或 TaskManager 模块。

| 范围 | 源码结论 | 本交付处理 |
| --- | --- | --- |
| 依赖 | requirements.txt 使用 f2>=0.0.1.7，其余未锁；没有锁文件 | f2==0.0.1.7，uv.lock 锁定全部解析依赖及分发哈希 |
| 合集查询 | core.py 的 `get_mix_info_by_video_url(video_url)` 返回 success/mix_id/mix_name/mix_desc/total_videos/message；有 mix_id 时 total_videos 是“查看详情”字符串，无 mix 时也可能 success=True | 从原始 mix_info 读取正式 ID 和 statis.total，缺 mix 拒绝，未知总数不报齐全 |
| 合集下载 | `download_mix_by_id(mix_id, mix_name='', progress_callback=None, file_progress_callback=None, max_counts=None, interval='all')` 使用 F2 fetch_user_mix_videos；每次 create_download_tasks 返回后即累计 to_download 数量，随后 success=True | 独立逐集状态及 MP4/长度/可用 ffprobe/SHA-256 校验，检查文件后才计入已下载 |
| 分页和顺序 | F2 handler 使用 cursor/has_more 迭代；去重计数和重游标保护不足，上游有估计总数 100 的进度展示 | 全量查询后确认，游标去重和上限，作品 ID 去重，明确平台集序优先，否则原分页顺序；不按文案或发布时间猜顺序 |
| 原文 | F2 filter.desc 会 replaceT 清理；部分文件名又删标签、截断 | 使用原始 JSON title/desc；可读文件名独立清理，不覆盖原文 |
| 登录 | cookie_manager.py 在项目根写 douyin_cookie.txt，并在日志打印部分 sessionid/user_id；get_cookie 可能隐式启动浏览器，refresh_cookie 默认 headless=True | 不导入这些模块。自己的可见浏览器私有资料目录，显式本机登录，Cookie 不转交 CDN、不入日志/清单/源码 |
| F2 默认请求 | model.py 合成 Windows/Edge 等参数并在导入时请求 Token；crawler 合成签名 | 不使用这些请求模型/爬虫。使用真实浏览器 UA 和普通同源请求/本页面详情响应；拒绝后不生成签名绕过 |
| F2 下载底层 | BaseDownloader._download_chunks 吞部分异常；BaseCrawler transport 使用 verify=False，默认自动重试，close 会创建未使用同步 client | StrictF2Downloader 复用 F2 execute_tasks 和 aclient 接口，覆盖传输/关闭：校验证书，手动检查每次重定向域名、状态、长度、MP4；403/429 立即抛出暂停，无自动重试 |
| TaskManager 错误 | V3 持久化 task/video 状态，但依赖上游 success 结果；web 部分后台路径在处理循环后设 completed，不能据此证明磁盘文件有效 | 不复用成功语义。单 worker 串行，原子持久化每集状态；意外中断为待重试，按真实计数判完整 |
| 并发和路径 | 上游 kwargs 常用 5 个任务/连接，mix_name 直接参与目录；数据库/日志相对 cwd | 全局单下载任务、逐集串行+间隔，稳定 ID 子目录，安全文件名与路径边界，拒绝符号链接；资料与输出移出源码 |
| Web/CLI | POST /api/mix-info 使用上面 result；POST /api/download-mix 入队非完成。refresh-cookie CLI 存在；export <task_id> --output 使用 TaskManager 导出。web 默认 host=0.0.0.0 | 保留查询/确认 API 名称，新的响应直接是清单；不兼容上游 ApiResponse/task_id，export 使用 metadata.json。仅 127.0.0.1，Host/Origin 和每次启动令牌 |

未盲目运行上游安装、启动脚本，未调用其真实下载测试。当前依赖中的 browser-cookie3、pyexecjs 等来自 F2 分发依赖，本应用不调用；F2 依赖较旧，仍有维护与兼容风险。

**已验证范围**：安装固定 F2、导入基础下载器、执行器调用、实际 loopback HTTPS MP4 传输、错误与文件校验，以及本地 UI。**未验证范围**：真实抖音详情/分页接口能否接受当前浏览器会话、签名媒体 URL 与 CDN 实际传输、Mac 架构及浏览器安装。

上游没有 LICENSE 文件；不能将无许可证理解为允许任意公开再分发。本交付为用户审阅保留固定来源，正式公开发布前应确认授权。
