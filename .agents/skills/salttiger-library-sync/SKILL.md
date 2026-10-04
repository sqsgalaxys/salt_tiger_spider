---
name: salttiger-library-sync
description: "将 SaltTiger 书籍元数据同步到本地 SQLite 和 OneDrive 目录，并安全处理下载入口。"
---

<!-- codex-session-skill:v1 -->
# Workflow

1. 先运行 doctor，确认书库目录和数据库可用。
2. 默认执行 sync 时遵守 robots；只有获得明确授权后才传入允许抓取的选项。
3. 需要时使用限制数量的同步，先验证少量记录再扩大范围。
4. 只有在用户明确要求且链接为明确直链时启用直链下载。
5. 对网盘分享链接保留快捷方式，不自动操作账号、验证码或第三方客户端。
6. 使用 latest 或 search 核对入库结果；手工下载完成后使用 import-file 归档实际文件。

## Guardrails

- 不要绕过 robots、登录、验证码、访问控制或下载限制。
- 不要覆盖已有文件；保留冲突处理和失败重试能力。
- 不要将凭据、令牌或个人路径写入仓库。
