# SaltTiger 远程 WSL1 下载与生产运行手册

本文记录 `DESKTOP-1BL5PJ8` 上已经验证的连接链路、WSL1/bdpan
部署、一次性下载流程，以及后续定时运行、监控和通知方案。文档不包含
Windows、百度网盘或 Cloudflare 凭据。

## 1. 当前拓扑与已验证状态

```text
Codex / 本机 PowerShell
        |
        | cloudflared access tcp（仅监听 127.0.0.1）
        v
ssh.071395.xyz
        |
        v
my-ubuntu (developer, Tailscale 100.126.189.13)
        |
        | Tailscale；当前可经 DERP 中继
        v
DESKTOP-1BL5PJ8 (100.96.120.123 / LAN 192.168.8.181)
        |
        v
WSL1 Ubuntu-22.04 -> bdpan -> D: OneDrive
```

目标书库：

```text
D:\OneDrive\OneDrive\30_Knowledge_笔记阅读学习\salttiger_book
```

WSL 路径：

```text
/mnt/d/OneDrive/OneDrive/30_Knowledge_笔记阅读学习/salttiger_book
```

截至 2026-09-04 的实机核验：

- `Microsoft-Windows-Subsystem-Linux` 已启用；无待重启状态。
- `Ubuntu-22.04` 正在 WSL `VERSION 1` 运行。
- `VirtualMachinePlatform` 不在此 LTSC 映像中，因此不依赖 WSL2。
- `bdpan 3.8.7` 已安装并由用户交互式完成 OAuth。
- SaltTiger CLI 位于 `/opt/salttiger/venv/bin/st`。
- 适配器兼容 `bdpan 3.8.7` 的 `{"code": 0}` 成功响应；生产升级后应保留该回归测试。
- SQLite 有 20 本书和 20 个百度任务；登录前失败原因均为未认证。
- OneDrive 与 WSL 挂载均可写；实际下载使用 `.salttiger/staging` 隔离暂存，
  再以不覆盖策略归档到 `books/<slug>/`。

## 2. 连接与恢复

原 SSH 配置使用 `cloudflared access ssh`，但当前 Cloudflare 域名没有可识别的
Access Application。可临时使用通用 TCP 模式。

PowerShell 窗口 1：

```powershell
& "$env:USERPROFILE\.codexpro\bin\cloudflared.exe" access tcp `
  --hostname ssh.071395.xyz `
  --url 127.0.0.1:22224
```

PowerShell 窗口 2：

```powershell
ssh -p 22224 `
  -o HostKeyAlias=my-ubuntu-cloudflare-tcp-22224 `
  -o StrictHostKeyChecking=accept-new `
  developer@127.0.0.1
```

在 my-ubuntu 上：

```bash
tailscale ping -c 1 100.96.120.123
ssh sqsga@100.96.120.123
```

若目标 Tailscale 不通，已验证的备用链路是：

```text
本机 -> my-ubuntu -> Arch (100.116.135.101) -> 192.168.8.181:22
```

不要因为 `tailscale status` 中存在节点条目就判断在线；至少同时验证
`tailscale ping` 和 TCP 22。

## 3. 部署布局

```text
/opt/salttiger/venv/                 # Python 隔离环境
/opt/salttiger/bin/                  # 生产运行脚本
/root/.config/bdpan/                 # bdpan OAuth 配置；禁止同步或输出
/root/.config/salttiger/             # 可选通知配置；chmod 600
/var/log/salttiger/                  # 运行日志；不放 OneDrive
/run/lock/salttiger-pan.lock         # 防止计划任务重叠
D:/.../salttiger_book/.salttiger/    # SQLite、暂存和项目管理文件
D:/.../salttiger_book/books/         # 最终书籍文件
```

安装或升级 wheel：

```bash
python3 -m venv /opt/salttiger/venv
/opt/salttiger/venv/bin/python -m pip install /path/to/salttiger_library-*.whl
```

安装生产脚本：

```bash
install -D -m 0750 salttiger-pan-job.sh /opt/salttiger/bin/salttiger-pan-job.sh
```

OAuth 必须由用户本人交互完成：

```powershell
wsl -d Ubuntu-22.04 -- bdpan login --device-code --accept-disclaimer
```

不得把授权码、token、密码或完整 `~/.config/bdpan` 内容放进仓库、日志、
OneDrive 或聊天。

## 4. 手工运行与状态机

诊断：

```powershell
wsl -d Ubuntu-22.04 -- /opt/salttiger/venv/bin/st bdpan-doctor
```

仅预览：

```powershell
wsl -d Ubuntu-22.04 -- /opt/salttiger/venv/bin/st download-pan `
  --library /mnt/d/OneDrive/OneDrive/30_Knowledge_笔记阅读学习/salttiger_book `
  --limit 20 --retry-failed
```

明确执行：

```powershell
wsl -d Ubuntu-22.04 -- /opt/salttiger/venv/bin/st download-pan `
  --library /mnt/d/OneDrive/OneDrive/30_Knowledge_笔记阅读学习/salttiger_book `
  --limit 20 --retry-failed --confirm
```

状态流转：

```text
available/failed/downloading -> downloading -> synced
                                      |
                                      +---------> failed（可重试）
```

每项先下载到独立暂存目录。成功后才复制到对应书籍目录；同名同内容复用，
同名不同内容追加稳定哈希，不覆盖用户文件。异常中断留下的 `downloading`
任务可由 `--retry-failed` 纳入恢复。

## 5. Windows Task Scheduler 正式方案

WSL1 没有 systemd，不应把脱离终端的后台进程当成长期服务。正式调度由
Windows Task Scheduler 启动一个前台 `wsl.exe`，等待本次批处理完成后退出。

推荐动作：

- Program: `C:\Windows\System32\wsl.exe`
- Arguments:

  ```text
  -d Ubuntu-22.04 -- bash /opt/salttiger/bin/salttiger-pan-job.sh
  ```

- Start in: `C:\Windows\System32`
- 频率：每 1 小时一次；单次执行超时可设 8 小时。
- Multiple instances：`Do not start a new instance`。
- 勾选网络可用后运行、错过计划后尽快运行。
- 初期选择“仅用户登录时运行”，不需要把密码写进脚本。
- 真正无人值守时，在 Task Scheduler GUI 中选择“无论用户是否登录均运行”，
  让 Windows 安全保存账户凭据；不要在命令行或仓库保存密码。
- 不使用 `/IT` 作为无人值守任务，因为它只在用户已登录时运行。
- 不使用 SYSTEM：它不能可靠复用该用户的 WSL 发行版和 bdpan OAuth 状态。

首次上线验证：

1. 手工执行生产脚本并确认退出码。
2. 在 Task Scheduler 中手工点“Run”。
3. 检查 Last Run Result 与 History。
4. 检查 `Microsoft-Windows-TaskScheduler/Operational` 事件日志。
5. 核对 SQLite 状态与 `books/` 下实际文件，而不是只看任务显示成功。
6. 再验证注销用户后的计划触发；失败时退回“仅登录时运行”。

## 6. 监控与通知

生产脚本 `scripts/salttiger-pan-job.sh` 提供：

- `flock` 单实例锁；重叠执行返回 75。
- 每次先运行 `bdpan-doctor`。
- 仅处理 SQLite 已入库任务，不自动抓取网站。
- 日志写到 `/var/log/salttiger/pan-<UTC时间>.log`。
- 结束时记录退出码及 `available/downloading/synced/failed` 聚合，不记录链接。
- 可选 `SALTTIGER_NOTIFY_URL`，只推送退出码和聚合计数。

通知配置示例（文件本身不提交仓库）：

```bash
install -d -m 0700 /root/.config/salttiger
printf '%s\n' 'SALTTIGER_NOTIFY_URL=https://example.invalid/private-topic' \
  > /root/.config/salttiger/production.env
chmod 0600 /root/.config/salttiger/production.env
```

通知 URL 可能包含访问能力，禁止写入 OneDrive 或普通日志。上线前需要根据实际
使用的 ntfy/Webhook 服务做一次测试；当前仓库不会假定某个外部通知服务。

## 7. 新书发现策略

SaltTiger 当前 `robots.txt` 为 `Disallow: /`，因此计划任务不能默认运行
`st sync --allow-disallowed`。推荐把流程拆开：

```text
人工明确触发/许可的数据导入
        -> SQLite 新增 available 任务
        -> 每小时计划任务发现任务
        -> bdpan 转存与下载
        -> SQLite synced/failed
        -> 聚合通知
```

可选的合规入口：浏览器保存 `/archives/` 与详情 HTML 后使用 `st sync
--archive-html ... --detail-html-dir ...` 离线导入。只有确认得到站点许可后，
才单独设计低频网络同步任务。

## 8. 故障排查顺序

1. `cloudflared access tcp` 是否仍在监听本机端口。
2. 是否能登录 my-ubuntu。
3. `tailscale ping 100.96.120.123` 与目标 TCP 22 是否都成功。
4. `wsl -l -v` 是否仍显示 `Ubuntu-22.04 ... VERSION 1`。
5. D 盘 OneDrive 路径是否存在并可写，空间是否充足。
6. `bdpan-doctor` 是否显示 `Authenticated: yes`。
7. 是否存在旧运行；检查锁和 Task Scheduler 的 MultipleInstances 设置。
8. 查看本地生产日志的错误摘要，但不要复制 token、授权码或分享链接。
9. 失败任务使用预览命令确认范围后，再加 `--confirm` 重试。
