# YouTube Subscription Manager

> 把 YouTube 的订阅列表变成一个能搜索、能分类、能批量清理的看板。
> 数据全部存在**你自己**的机器上，不需要第三方服务。

[![License: MIT](https://img.shields.io/badge/license-MIT-3da639?style=flat-square)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-3776ab?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![Docker](https://img.shields.io/badge/docker-compose-2496ed?style=flat-square&logo=docker&logoColor=white)](docker-compose.yml)

<!--
  📸 加一张截图会让 README 好看很多（GitHub 上第一印象很重要）：
  1. 把应用跑起来，截一张主界面图，存成 docs/screenshot.png
  2. 把下面这行前面的 # 去掉即可
-->
<!-- ![界面截图](docs/screenshot.png) -->

---

## 这是什么

YouTube 官方只能一页页翻你的订阅，想找"那个做菜频道"、想清理已经不再看的账号，都很痛苦。
这个工具把订阅数据同步到本地，然后给你一个看板：

- 🔍 **秒级搜索**，不用等 YouTube 转圈
- 🏷 **分类整理**，用 YouTube 自带的主题分类（科技 / 音乐 / 游戏 …）
- ✅ **批量退订**，多选后一次性清理
- ✎ **自定义标签**，打上"常看 / 想取关 / 教程"这类属于自己的标签
- 📅 **活跃度排序**，一眼看出哪些频道已经几个月没更新

## ✨ 功能

- **订阅看板** — 频道卡片显示头像、订阅数、视频数、最近上传时间、全部主题分类
- **多分类筛选** — 一个频道常有 2~3 个分类，全部保留，点任意标签即可筛选
- **搜索** — 按频道名实时过滤，纯前端完成，输入即出结果
- **排序** — 按名称 / 订阅数 / 视频数 / 最近更新排序
- **批量退订** — 多选后一次性退订（会真的调用 YouTube API）
- **自定义标签** — 批量打标签、单个移除、可撤销；标签只存本地，不消耗 API 配额
- **活跃度** — 「今天 / 3天前 / 2个月前」按读取时刻实时计算，不会因为数据是几小时前拉的就失真
- **头像本地缓存** — 几百个频道也只从本机取图，不会触发 Google CDN 的 429 限流
- **深色 / 浅色主题** — 跟随系统，可手动切换，刷新不闪屏
- **访问口令（可选）** — 用浏览器原生登录框保护界面，适合放到局域网 / Tailscale
- **数据全本地** — SQLite 存在自己机器上，除了 YouTube 官方 API 不连任何第三方

---

## 🚀 快速开始（Docker，推荐）

需要先装好 [Docker Desktop](https://www.docker.com/products/docker-desktop/)（Windows / macOS）
或 Docker Engine + Compose（Linux）。

### 第 1 步 · 克隆项目

```bash
git clone https://github.com/<你的用户名>/youtube-sub-manager.git
cd youtube-sub-manager

# 建好数据挂载目录（不建的话 Docker 可能建成 root 属主，Linux 上会写不进去）
mkdir -p config data cache output
```

### 第 2 步 · 拿到 Google 凭证

这是唯一稍微麻烦的一步：你需要一个**属于自己**的 Google OAuth 凭证
（原因见 [为什么不能共用凭证](#为什么不能共用作者现成的凭证)）。

**方式 A：跟着向导走（推荐，什么都不用装）**

```bash
docker compose build                              # 先构建镜像，向导在镜像里
docker compose run --rm app python scripts/setup.py
```

向导会把该点的页面按顺序给你（能自动打开浏览器），一步步告诉你点哪里，
最后自动去 `~/Downloads`、`~/下载`、`~/Desktop` 里找你下载下来的文件，校验并放好。

> 本机已经装了 Python 3 的话，也可以直接 `python3 scripts/setup.py`，效果一样。

**方式 B：完全手动**

照着 **[docs/google-oauth.md](docs/google-oauth.md)** 一步步点，大约 3~5 分钟。
最后必须得到这个文件：

```
config/client_secrets.json
```

> ⚠️ 创建的 OAuth 客户端类型**必须选「桌面应用 / Desktop app」**，不是「Web 应用」。

### 第 3 步 · 启动

```bash
docker compose up -d
```

### 第 4 步 · 浏览器里授权

打开 **<http://localhost:8765>**，会自动跳到授权页：

1. 点「**前往 Google 授权**」
2. 选择你的 Google 账号 → 同意
3. 如果出现「此应用未经验证」的警告页，点「**高级**」→「**继续前往 …（不安全）**」——
   这是正常的，因为应用是你自己建的，Google 没审核过它
4. 授权完页面会**自动跳回**看板，开始同步你的订阅（约 10~30 秒）

### 更新到新版本

```bash
git pull
docker compose up -d --build
```

数据都在 `config/`、`data/`、`cache/` 里，重建容器不会丢。

---

## 🐍 不用 Docker：本地运行

需要 Python 3.10 或更高版本。

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 准备好 config/client_secrets.json（见上一节）
python3 app.py
```

打开 <http://localhost:8765> 即可。本地运行时会自动用 `localhost` 的随机端口接收授权回调，
不需要额外配置端口。

---

## ❓ 常见问题

### 为什么每隔 7 天就要我重新授权一次？

因为你的 OAuth 应用还停留在「**测试 / Testing**」发布状态，Google 规定这种状态签发的
refresh token **只有 7 天有效期**。

**永久解决办法**：到 [Google Auth Platform 的受众页面](https://console.cloud.google.com/auth/audience)
把发布状态改成「**正式 / In production**」。只有你自己一个用户，不需要 Google 审核，
只是授权时会多一个"未经验证"的警告页（点「高级 → 继续前往」即可）。

详见 [docs/google-oauth.md](docs/google-oauth.md) 里「强烈建议：把发布状态改成正式」一节。

### 会不会消耗我的 YouTube 配额？会影响我的账号吗？

- 每个 Google Cloud 项目每天有 **10,000 单位**免费配额，**一次全量刷新约消耗 268 单位**
  （以 256 个订阅计），默认 6 小时缓存下每天只占约 **11%**
- 默认「不打开页面就不刷新」，所以放着不管时**完全不消耗**
- 走的是 YouTube 官方 Data API，和你在网页上用 YouTube 是同一套授权机制，不会导致封号
- 细节见 [docs/internals.md](docs/internals.md#刷新机制与-api-配额)

### 我的数据会被上传到哪里吗？

不会。除了访问 YouTube 官方 API 拉取你自己的订阅数据以外，应用**不连接任何第三方服务器**：

| 数据 | 存在哪 |
| --- | --- |
| OAuth 凭证 | 本机 `config/`（已 gitignore） |
| 订阅快照、自定义标签 | 本机 SQLite 数据库 |
| 频道头像 | 本机 `cache/thumbs/` |

### 为什么不能共用作者现成的凭证

两个硬性原因：

1. **安全** —— `client_secret` 一旦公开就等于泄露
2. **配额** —— 配额是按 Google Cloud 项目算的，共用项目 = 共用每天 10,000 单位，
   几个人一起用会瞬间耗尽，**所有人都用不了**

所以必须每人申请一份，反正一次性 3~5 分钟。

### 端口被占用了怎么办？

| 端口 | 用途 | 怎么改 |
| --- | --- | --- |
| `8765` | Web 界面 | `.env` 里的 `APP_PORT` |
| `8899` | OAuth 授权回调 | `.env` 里的 `OAUTH_PORT`，**同时**要改 `docker-compose.yml` 里 `ports` 的对应行（两处必须一致） |

```bash
# 查是谁占了（macOS / Linux）
lsof -nP -iTCP:8899 -sTCP:LISTEN
```

更多排错见 **[docs/deployment.md](docs/deployment.md)**。

### 支持 Windows / 群晖 NAS / 树莓派吗？

支持。只要那个平台能跑 Docker + Docker Compose 就行：

- **Windows** — 装 Docker Desktop，用 PowerShell 执行同样的命令
- **群晖 / 威联通 NAS** — 用 Container Manager，或 SSH 进去用 `docker compose`
- **树莓派 / ARM 小主机** — `python:3.12-slim` 是多架构镜像，会自动选对架构

### 退订是真的会退订吗？

是。批量退订会真的调用 YouTube API 移除订阅，**没有二次确认弹窗**
（但操作后底部提示里可以**撤销**）。请谨慎使用。

---

## 🔒 隐私与安全

- ✅ 凭证与数据默认全部被 `.gitignore` 排除，不会被误提交
- ✅ **推代码前建议跑一次 `git status`**，确认没有 `config/`、`data/`、`cache/` 被跟踪
- ⚠️ **本应用没有账号体系**：任何能访问到该地址的人都能查看你的全部订阅，并且可以真的退订。
  所以**对外暴露前请设置访问口令**：

  ```bash
  cp .env.example .env
  # 编辑 .env，填入 ACCESS_PASSWORD=你的强密码
  docker compose up -d
  ```

  注意 HTTP Basic 认证是明文传输的，只应在**局域网 / Tailscale 等可信网络**中使用；
  真要暴露到公网，请套一层 HTTPS 反向代理。
- ⚠️ 万一凭证泄露：到 Google Cloud Console 删掉那个 OAuth 客户端，重新建一个即可，旧凭证立即失效。

---

## 📁 目录结构

```
youtube-sub-manager/
├── app.py                    # Flask 后端 + SQLite 缓存
├── docker-compose.yml
├── Dockerfile
├── .env.example              # 环境变量模板
├── config/
│   ├── client_secrets.json   # OAuth 凭证（你要自己准备，已 gitignore）
│   └── token.json            # 授权后的 token（自动生成，已 gitignore）
├── data/data.db              # 订阅快照（自动生成，已 gitignore）
├── cache/thumbs/             # 头像缓存（自动生成，已 gitignore）
├── scripts/
│   ├── setup.py              # 交互式配置引导
│   ├── auth.py               # 命令行授权（备选）
│   └── sync_labels.py        # 多环境同步自定义标签
├── docs/                     # 详细文档
├── static/                   # 前端 CSS / JS
└── templates/                # Jinja2 模板
```

---

## 📚 更多文档

| 文档 | 内容 |
| --- | --- |
| [docs/google-oauth.md](docs/google-oauth.md) | 从零申请 Google OAuth 凭证（含常见报错对照表） |
| [docs/deployment.md](docs/deployment.md) | 部署到服务器 / NAS，局域网、Tailscale、远程授权、备份升级 |
| [docs/internals.md](docs/internals.md) | 缓存机制、API 配额测算、自定义标签同步、界面参数、HTTP API |

## 🛠 想改代码 / 调参数

常用的几个环境变量（完整列表见 [.env.example](.env.example) 与
[docs/deployment.md](docs/deployment.md#十环境变量)）：

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `APP_PORT` | `8765` | Web 界面端口 |
| `REFRESH_INTERVAL_SECONDS` | `21600` | 本地快照新鲜度阈值（6 小时），越小数据越新、越费配额 |
| `AUTO_REFRESH_SECONDS` | `0` | 后台定时刷新间隔，`0` = 关闭 |
| `ACCESS_PASSWORD` | *(空)* | 设置后启用访问口令 |

---

## 🤝 参与贡献

欢迎提 Issue 和 PR，见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 📄 License

[MIT](LICENSE) © 2026 Maxwell ano

## ⚠️ 免责声明

本项目通过 YouTube Data API v3 访问你自己的账号数据，与 YouTube / Google 无任何关联。
批量退订是**不可逆**的真实操作（虽然界面上可撤销），请自行确认后再执行。
