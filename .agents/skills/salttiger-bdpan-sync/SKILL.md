---
name: salttiger-bdpan-sync
description: "将已入库的 SaltTiger 百度网盘任务安全下载并归档到书籍目录。"
---

<!-- codex-session-skill:v1 -->
# Workflow

1. 先运行 bdpan-doctor，确认 bdpan 或受支持运行环境可用。
2. 确认百度网盘登录由用户完成后，再执行下载命令。
3. 使用带确认参数的 download-pan 处理待下载任务，并限制批次大小。
4. 下载后检查任务状态和书籍目录中的归档文件。
5. 对 failed 或 available 状态任务执行重试，不覆盖已有文件。

## Guardrails

- 不要保存、输出或请求用户的百度网盘凭据。
- 不要在未确认前执行会覆盖本地文件的操作。
- 仅处理用户有权访问和保存的分享内容。
- bdpan 不可用时停止下载并报告环境缺口。
