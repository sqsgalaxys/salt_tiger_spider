# SaltTiger Library

把 SaltTiger 的书籍元数据整理成个人 SQLite 索引，并把每本书的元数据、来源和下载入口同步到 OneDrive。项目已从旧 Scrapy + MySQL 爬虫重写为 Python 3.10+ 的本地 CLI。

默认目录正是：

```text
C:\Users\<你的用户名>\OneDrive\30_Knowledge_笔记阅读学习\salttiger_book
```

在当前电脑上会解析为：

```text
C:\Users\sqsga\OneDrive\30_Knowledge_笔记阅读学习\salttiger_book
```

## 能做什么

- 从 `/archives/` 发现历史书籍，解析标题、出版日期、出版社、封面、官网、标签和下载入口。
- 用 SQLite 幂等更新，按 SaltTiger 详情 URL 去重。
- 在 OneDrive 中为每本书生成 `metadata.json`、`SaltTiger.url`、`Official.url` 和下载入口快捷方式。
- 对明确直链直接下载；也可通过百度官方 `bdpan` CLI 转存并下载百度网盘分享链接。
- 把你已经合法取得或手工下载的文件归档到对应书籍目录。
- 支持 `search`、`latest` 和完全离线的 HTML 导入。

百度网盘自动下载使用官方 OAuth 和官方 CLI，不读取或保存百度凭据，也不会绕过验证码。未安装/未登录时仍保留可点击的 `baidu_pan.url`。

## 安装

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"
```

检查默认目录和数据库：

```bash
st doctor
```

也可以显式指定目录或永久设置 `SALTTIGER_LIBRARY_DIR`：

```bash
st doctor --library "C:\Users\sqsga\OneDrive\30_Knowledge_笔记阅读学习\salttiger_book"
```

## 同步

SaltTiger 当前的 `robots.txt` 是 `Disallow: /`。默认网络请求会尊重它并停止。推荐从浏览器保存归档页和详情页后离线导入；只有在你确认获得许可或愿意显式承担低频访问责任时，才使用 `--allow-disallowed`。客户端固定单并发、请求间隔至少 3 秒，并带重试。

低频同步最新 20 条：

```bash
st sync --limit 20 --allow-disallowed
```

重复运行会跳过已入库 URL；需要重新解析时：

```bash
st sync --limit 20 --refresh --allow-disallowed
```

只有明确直链才下载文件：

```bash
st sync --limit 20 --download-direct --allow-disallowed
```

### 百度网盘自动下载

采用百度官方 [`baidu-netdisk/bdpan-storage`](https://github.com/baidu-netdisk/bdpan-storage)。官方目前只承诺 macOS、Linux 和 Windows WSL，未承诺 Windows 原生运行。

先在 WSL 中安装官方 Skill 和 `bdpan`，再按官方 `login.sh` 完成一次 OAuth 登录：

```bash
npx skills add https://github.com/baidu-netdisk/bdpan-storage/skills --skill baidu-drive
```

不要把授权码写入本项目配置。检查 CLI 与登录状态：

```bash
st bdpan-doctor
```

Windows 默认会尝试 `wsl.exe bdpan`。也可以覆盖命令：

```powershell
$env:SALTTIGER_BDPAN_COMMAND = "wsl.exe bdpan"
st bdpan-doctor
```

先预览待下载项，再明确确认转存和本地写入：

```bash
st download-pan --limit 20
st download-pan --limit 20 --confirm
```

失败任务不会标记为完成，可以修复登录/网络后重试：

```bash
st download-pan --limit 20 --retry-failed --confirm
```

也可以在抓取时串联完整流程：

```bash
st sync --limit 20 --allow-disallowed --download-pan --confirm-pan
```

每个分享链接会下载到隔离的临时目录，再安全复制到对应书籍目录；已有同名文件不会被覆盖。百度远端操作仍限制在官方的“我的应用数据/bdpan”范围内。

从浏览器保存的单个详情页离线导入：

```bash
st import-html page.html --url "https://salttiger.com/example-book/"
```

批量离线同步时，把归档保存为 `archives.html`，详情页按 slug 保存，例如 `detail-pages/example-book.html`：

```bash
st sync --archive-html archives.html --detail-html-dir detail-pages
```

如果某个详情 HTML 缺失，命令仍会尝试网络请求；在未传 `--allow-disallowed` 时会把该条记录为失败，不会绕过 robots。

## 使用书库

```bash
st latest --limit 20
st search "agent"
st search "SAP"
```

搜索结果第一列是书籍 ID。把手动下载的文件归档进去：

```bash
st import-file 382 "D:\Downloads\book.epub"
```

默认布局：

```text
salttiger_book/
├── .salttiger/library.sqlite3
└── books/
    └── example-book/
        ├── metadata.json
        ├── SaltTiger.url
        ├── Official.url
        ├── baidu_pan.url
        └── book.epub
```

## 开发

```bash
python -m pytest
python -m salttiger_library --help
```

旧版的 `python run.py` 仍作为 CLI 兼容入口，但不再需要 Scrapy、MySQL、PyMySQL 或 SQLAlchemy 1.x。

远程 WSL1、my-ubuntu/Tailscale 连接、Windows Task Scheduler、监控与通知的完整说明见
[生产运行手册](docs/remote-wsl1-production-runbook.md)。
