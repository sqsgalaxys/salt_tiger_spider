---
name: salt-tiger-library-sync
description: "维护 SaltTiger Library 的本地索引与 OneDrive 物化流程。"
---

<!-- codex-session-skill:v1 -->
# Workflow

1. 先运行 doctor 检查环境和目标目录。
2. 默认使用本地归档 HTML 导入；只有获得明确授权时才启用受限网络同步。
3. 同步后使用 latest 或 search 核对新增条目。
4. 将云盘分享链接保留为快捷方式，不自动处理需要账号、验证码或授权的下载。
5. 仅启用明确直链下载；将手工取得的文件通过 import-file 归档。
6. 修改解析、同步或存储逻辑后运行测试套件。

## Guardrails

- 不要默认绕过 robots 规则。
- 不要写入凭据或自动化处理第三方账号验证。
- 不要将失败同步标记为完成。
- 保留已有 OneDrive 文件，避免覆盖或删除未确认内容。
