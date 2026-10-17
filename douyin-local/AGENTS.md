# 本地抖音合集工具

- 运行 `uv sync --locked`，`uv run --locked python -m pytest -q`，`uv run --locked ruff check douyin_local tests`。
- 上游参考固定于 upstream/PIN.md；原 AGENTS.md 位于 upstream/AGENTS.md，适用于其源码子目录。
- 程序入口 `python -m douyin_local.web`；只绑定 127.0.0.1，保持同源校验与随机本地令牌。
- Cookie、浏览器资料、视频、用户日志不得提交，不得向云端要求用户提供登录状态。
- 平台阻断必须暂停；不添加指纹伪造、验证码绕过、签名合成、Chrome Cookie 解密。
- 合集查询先于用户确认；不转为整用户作品下载。
- 自动化测试是本地夹具验证，不能用来宣称真实抖音下载成功。
- Mac 实机验证状态必须保持 `not tested on Mac`，直到收到可复核的实机结果。
