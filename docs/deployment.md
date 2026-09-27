# 部署指南（Docker）

本文档带你在一台**目标主机**（部署机 / 服务器，可以是 Mac、Linux、NAS）上，用 Docker 把这个项目从零跑到能用。

## 本文档适合谁看

- 你拿到的是这个项目的代码，想在**另一台机器**上长期运行，而不是在自己电脑上跑一下
- 你机器上只有 Docker（Docker Desktop 或 Docker Engine + Compose），不想装 Python 环境
- 你已经准备好了 Google OAuth 凭证（如果还没有，先看 [google-oauth.md](google-oauth.md)，那边有从零申请 `client_secrets.json` 的完整步骤）

全程只需要 Docker + Docker Compose。所有命令都可以直接复制粘贴，涉及你自己信息的地方用 `<尖括号>` 标出，替换掉即可。

| 占位符 | 含义 | 举例 |
| --- | --- | --- |
| `<用户名>` | 目标主机上的登录用户名 | `ubuntu`、`yourname` |
| `<主机地址>` | 目标主机的地址（IP 或域名） | `192.168.1.50` |
| `<部署机 IP>` | 目标主机在局域网中的 IP | `192.168.1.50` |

> 本文档只出现占位符，不会出现任何具体的 IP、主机名或用户名。

---

## 一、需要准备的 3 类文件

| 类别 | 文件 | 说明 |
| --- | --- | --- |
| **项目代码** | `app.py`、`templates/`、`static/`、`scripts/`、`requirements.txt` | 必需 |
| **容器配置** | `Dockerfile`、`docker-compose.yml`、`.dockerignore` | 必需 |
| **Google 凭证** | `config/client_secrets.json`、`config/token.json` | **必需，且只能你自己提供** |

`config/` 里的这两个文件已被 `.gitignore` / `.dockerignore` 排除，既不会被提交、也不会打进镜像，必须手动放到目标主机上。

> **强烈建议把已经授权好的 `config/token.json` 一起复制过去**：这样目标主机上完全不需要重新走 Google 授权流程（access token 会用它里面的 refresh_token 自动续期）。
>
> 申请 `client_secrets.json` 的详细步骤见 [google-oauth.md](google-oauth.md)。

---

## 二、在目标主机上准备

登录目标主机，确认 Docker 可用并建好项目目录：

```bash
# 1. 确认 Docker 与 Compose 可用
docker --version
docker compose version

# 2. 建一个项目目录（路径随意，下文以此为例）
mkdir -p ~/youtube-sub-manager && cd ~/youtube-sub-manager
```

如果 `docker compose version` 报错，装一下 Compose 插件（Linux）：

```bash
sudo apt-get update && sudo apt-get install -y docker-compose-plugin
```

---

## 三、把项目复制过去

### 方式 A：rsync（推荐，一条命令，含凭证）

在**你放代码的那台机器**上执行（把 `<用户名>@<主机地址>` 换成目标主机的 SSH 登录方式）：

```bash
cd ~/coding/youtube-sub-manager        # 改成你自己的项目路径
rsync -av --delete \
  --exclude '.venv' --exclude '__pycache__' --exclude '.git' \
  --exclude 'cache' --exclude 'data' \
  ./ <用户名>@<主机地址>:~/youtube-sub-manager/
```

### 方式 B：先打包再拷贝

```bash
cd ~/coding/youtube-sub-manager        # 改成你自己的项目路径
tar --exclude='.venv' --exclude='__pycache__' --exclude='.git' \
    --exclude='cache' --exclude='data' \
    -czf /tmp/yt-sub-manager.tar.gz .
scp /tmp/yt-sub-manager.tar.gz <用户名>@<主机地址>:~/

# 然后在目标主机上解压
mkdir -p ~/youtube-sub-manager
tar -xzf ~/yt-sub-manager.tar.gz -C ~/youtube-sub-manager
```

### 方式 C：直接 git clone

代码已在 GitHub 上时最省事，但**凭证仍要单独传**（它们不在仓库里）：

```bash
git clone <仓库地址> ~/youtube-sub-manager
cd ~/youtube-sub-manager
mkdir -p config

# 在本机执行，把两个凭证文件传上去
scp config/client_secrets.json config/token.json \
    <用户名>@<主机地址>:~/youtube-sub-manager/config/
```

传完后在目标主机上确认文件在位：

```bash
ls -l ~/youtube-sub-manager/config/
# 应该能看到 client_secrets.json 和 token.json
```

---

## 四、启动

```bash
cd ~/youtube-sub-manager

# 首次：创建挂载用的宿主机目录（不存在的话 Docker 会建成 root 所有，后面写数据会失败）
mkdir -p config data cache output

# 构建并后台启动
docker compose up -d --build

# 看日志（首次构建要装依赖，约 1~3 分钟）
docker compose logs -f app
```

日志出现下面这行就说明 Web 服务起来了（`Ctrl+C` 退出日志跟踪，容器不会停）：

```
[INFO] Listening at: http://0.0.0.0:8765
```

---

## 五、验证

```bash
# 健康检查（不需要授权也能访问）
curl -s http://localhost:8765/healthz
# => {"ok":true,"authorized":true,"last_updated":"...", ...}

# 容器健康状态
docker compose ps
# STATUS 一列应显示 (healthy)
```

两个字段的含义：

| 字段 | 含义 |
| --- | --- |
| `ok` | Web 服务正常响应 |
| `authorized` | `token.json` 有效。为 `false` 时按第七节重新授权 |

然后浏览器打开 `http://localhost:8765`（在目标主机本机），或换成对应的访问地址（见下一节）。

---

## 六、局域网 / Tailscale / 公网怎么访问

**只要容器端口发布到宿主机，其它设备就能直接访问，不需要改应用配置。** 前端全部使用相对路径，没有写死 `localhost`，所以从任何主机名或 IP 打开都能正常工作。

### 场景 → 用哪个地址

| 场景 | 用什么地址 | 需要做什么 |
| --- | --- | --- |
| 目标主机本机 | `http://localhost:8765` | 无 |
| 同一局域网（手机、笔记本） | `http://<部署机 IP>:8765` | 无，确认防火墙放行 |
| Tailscale / WireGuard 等组网 | `http://<组网 IP>:8765` | 无，两端都要在线 |
| Tailscale MagicDNS | `http://<机器名>.<tailnet>.ts.net:8765` | 无，需开启 MagicDNS |
| 公网 | `https://<你的域名>` | **强烈建议**加反向代理 + HTTPS + 访问口令 |

### 查自己机器的地址

```bash
# macOS：局域网 IP
ipconfig getifaddr en0

# Linux：局域网 IP
hostname -I

# Tailscale：组网 IP 与 MagicDNS 名称
tailscale ip -4
tailscale status | head -3
```

### 坑 ①：macOS 防火墙

如果**局域网能访问、Tailscale 不能**（或反过来），先怀疑防火墙拦了 Docker 的端口转发。

打开「系统设置 → 网络 → 防火墙」，允许 `Docker` 接受传入连接即可。

### 坑 ②：重新授权时不能用域名 / 组网地址

Google 的**「桌面应用（Desktop app）」类型 OAuth 客户端只允许 `http://localhost` 作为回调地址**，不接受域名、也不接受 Tailscale / 局域网 IP 地址。

所以当 token 失效需要重新授权时，**不能**指望「从笔记本浏览器打开组网地址 → 点授权」就能跑通。三种应对方式：

| 情况 | 做法 |
| --- | --- |
| **A. 浏览器就在目标主机上** | 直接在目标主机上打开应用，点「前往 Google 授权」即可，无需额外配置 |
| **B. 你从笔记本远程访问** | 用 SSH 隧道把回调端口转发到你本机，然后通过 `localhost` 访问应用 |
| **C. 想用 HTTPS 域名授权** | 用 `tailscale serve` 提供 HTTPS，并把 OAuth 客户端改成「Web 应用」类型 |

**情况 A** —— 如果目标主机是带桌面的 Mac / Windows，直接在那台机器上开浏览器访问 `http://localhost:8765`，点授权按钮即可。

**情况 B** —— 在**你面前的笔记本**上开一条 SSH 隧道，把目标主机的回调端口 8899 映射到本机：

```bash
# 在笔记本上执行，保持这个终端不要关
ssh -N -L 8899:localhost:8899 <用户名>@<主机地址>
```

然后**用 `http://localhost:8765` 打开应用**（注意不是 `<部署机 IP>:8765`），点「前往 Google 授权」并同意。此时浏览器访问的 `localhost:8899` 会被隧道转发到目标主机上的回调服务，授权才能完成。

> 容器里 `OAUTH_BIND_ADDR` 已经是 `0.0.0.0`，端口也已经在 `docker-compose.yml` 里映射出来了，所以隧道直接可用。

**情况 C** —— 想用域名 + HTTPS 授权，需要把 OAuth 客户端换成「**Web 应用**」类型，并把最终地址登记到 Google 后台。用 Tailscale Serve 把容器端口以 HTTPS 暴露给 tailnet：

```bash
# 目标主机上执行：把本地 8899 通过 HTTPS(443) 暴露给 tailnet
tailscale serve --bg --https=443 http://127.0.0.1:8899

# 查看分配到的域名，形如 https://<机器名>.<tailnet>.ts.net
tailscale serve status
```

然后在 Google Cloud Console 的 OAuth 客户端里，把 `https://<机器名>.<tailnet>.ts.net/` 加为**已获授权的重定向 URI**，再发起授权：

```bash
docker compose exec -e OAUTH_REDIRECT_URI="https://<机器名>.<tailnet>.ts.net/" \
  app python scripts/auth.py
```

### ⚠️ 安全提醒

**这个应用本身没有任何账号体系。** 任何能访问该地址的设备都可以：

- 查看你的全部订阅、频道分类、更新频率
- **一键退订你的频道**（会真的调用 YouTube API）

在私有组网里风险相对可控（只有你自己的设备能进），但如果：

- 网络里有你不太信任的成员设备，或
- 端口直接暴露在公共局域网（咖啡厅、公司、宿舍网络）

**建议开启访问口令**（浏览器原生登录框，不需要改前端代码）：

```yaml
# docker-compose.yml
environment:
  ACCESS_USER: "admin"
  ACCESS_PASSWORD: "换一个强密码"
```

```bash
docker compose up -d      # 重新创建容器后生效
```

开启后，除 `/healthz` 外所有页面和接口都要求登录。

> HTTP Basic 的口令是明文传输的。
> 在 Tailscale / WireGuard 这类加密网络里没问题；但在**公共局域网或公网**上，请配合 HTTPS 使用（例如上面的 `tailscale serve`，或自建 Nginx / Caddy 反向代理）。
>
> 更彻底的做法：用 Tailscale ACL 限制只有你自己的设备能访问该端口。

---

## 七、重新授权（token 失效时）

### 网页流程（首选）

正常情况下打开应用会自动跳到 `/authorize` 页面，页面上有：

- 「**前往 Google 授权 →**」按钮
- 明文列出的完整授权链接（方便复制到别的浏览器或设备打开）

点击按钮 → 在 Google 页面同意 → 页面会**自动跳回应用**，凭证自动写入 `config/token.json`，**不需要重启容器**。

> 授权页面每 2 秒轮询一次状态，完成后自动跳转，不用手动刷新。
> 页面会等待回调最多 `OAUTH_TIMEOUT_SECONDS`（默认 600 秒），超时后自动释放回调端口，所以中途放弃也不会把端口一直占住。
> 如果从远程访问、回调只能走 `localhost`，先按第六节「情况 B」开好 SSH 隧道，再照常点按钮。

### 备选：纯命令行授权

只有在**没有办法用浏览器**（或想脚本化）时才用这条路径。新版网页流程已经覆盖了同样的功能，优先用上面那种。

```bash
# ① 在目标主机上启动授权脚本，终端会打印一个 Google 授权链接
cd ~/youtube-sub-manager
docker compose exec app python scripts/auth.py

# ② 把链接复制到你电脑的浏览器打开，同意授权
#    浏览器会跳到 http://localhost:8899/?code=... （这个 localhost 经 SSH 隧道
#    或端口映射指向目标主机），脚本收到 code 后自动写入 config/token.json

# ③ 让应用重新加载凭证
docker compose restart app
```

> 为什么不能直接用组网地址或域名授权？因为 OAuth 客户端是「**桌面应用**」类型，Google 只允许 `http://localhost` 作为回调地址。想用域名 + HTTPS，见第六节「情况 C」（需要改用「Web 应用」类型客户端）。

---

## 八、关于 refresh token 的 7 天有效期

**正常情况下永远不需要反复授权。** `config/token.json` 里保存了 `refresh_token`，access token 每小时过期后会自动续期（应用启动时、每次调用 API 前都会检查）。

**但有一个坑**：如果 Google Cloud 的 **OAuth 同意屏幕处于「测试（Testing）」状态**，Google 签发的 refresh token **只有 7 天有效期** —— 也就是每周都得重新授权一次。

发布状态可以在这里查看：

<https://console.cloud.google.com/apis/credentials/consent>

| 发布状态 | refresh token 寿命 |
| --- | --- |
| **测试 (Testing)** | **7 天**，到期必须重新授权 |
| **正式 (In production)** | 长期有效（除非被撤销、改了密码、或 6 个月未使用） |

**建议改成「正式」**：个人自用**不需要**通过 Google 验证，点「发布应用」即可。

之后授权时会看到「**Google hasn't verified this app**」警告页，这是正常的 —— 因为只有你自己一个用户，不需要走 Google 的验证流程。点「**高级**」→「**继续前往（不安全）**」就能通过。

> 依据：[Google 官方文档](https://developers.google.cn/nest/device-access/reference/errors/authorization) ——
> "Refresh tokens can stop working after 7 days if the client ID is not approved…
> a service or user account needs to get their OAuth 2.0 client ID approved and put into production to get longer token lifespans."

---

## 九、数据持久化与备份

**所有状态都在宿主机的挂载目录里，`docker compose down`（甚至删掉容器）都不会丢。**

| 宿主机路径 | 内容 | 丢了会怎样 |
| --- | --- | --- |
| `./config/token.json` | OAuth 凭证 | 需要重新授权（见第七节） |
| `./config/client_secrets.json` | OAuth 客户端 | 需要重新从 Google 下载（见 [google-oauth.md](google-oauth.md)） |
| `./data/data.db` | 订阅快照 + 你的自定义标签 | 下次启动重新拉一次（约 20 秒），**自定义标签无法恢复** |
| `./cache/` | 频道头像缓存 | 后台自动重新下载（约 1.4MB） |
| `./output/` | 导出的 JSON | 仅备份用途 |

对应 `docker-compose.yml` 里的挂载：

```yaml
volumes:
  - ./config:/app/config      # client_secrets.json + token.json
  - ./data:/app/data          # SQLite 订阅快照
  - ./cache:/app/cache        # 头像缩略图缓存
  - ./output:/app/output      # 导出的 subscriptions.json
```

### 备份

```bash
cd ~/youtube-sub-manager

# 打包凭证 + 数据（最关键的两个目录）
tar -czf ~/yt-backup-$(date +%F).tar.gz config data

# 想连头像缓存一起备份，就加上 cache
tar -czf ~/yt-backup-$(date +%F)-full.tar.gz config data cache
```

> 把备份文件放到**另一台机器**上。备份包含 `token.json`，等于你的 YouTube 授权凭证，注意保管，不要提交到公开仓库。

### 恢复

```bash
cd ~/youtube-sub-manager
tar -xzf ~/yt-backup-2025-01-01.tar.gz    # 解出 config/ 和 data/
docker compose up -d
```

---

## 十、环境变量

全部在 `docker-compose.yml` 的 `environment:` 里设置，改完执行 `docker compose up -d` 生效。

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `PORT` | `8765` | 容器内 Web 服务监听端口 |
| `DB_PATH` | `/app/data/data.db` | SQLite 位置，必须在挂载的 volume 内，否则重建容器会丢数据 |
| `THUMB_DIR` | `/app/cache/thumbs` | 频道头像缓存目录 |
| `REFRESH_INTERVAL_SECONDS` | `21600` | 本地快照的「新鲜度」阈值（秒）：超过它，下次打开页面才重新调 API。默认 6 小时 |
| `AUTO_REFRESH_SECONDS` | `0` | 后台定时刷新间隔（秒），`0` = 关闭。设 `7200` 可每 2 小时自动刷新（约占日配额 32%） |
| `TZ` | `Asia/Shanghai` | 时区，影响日志时间戳 |
| `ACCESS_USER` | `admin` | 访问口令的用户名 |
| `ACCESS_PASSWORD` | *(空)* | 设置后启用访问口令（HTTP Basic）。空 = 不启用 |
| `OAUTH_PORT` | `8899` | OAuth 回调端口，**必须和 `ports` 里的映射一致**（见下方说明） |
| `OAUTH_BIND_ADDR` | `0.0.0.0` | 回调服务监听地址。**容器内必须绑 `0.0.0.0`**，否则端口映射转发不进来 |
| `OAUTH_OPEN_BROWSER` | `0` | 是否自动打开浏览器。容器内没有浏览器，保持 `0` |
| `OAUTH_TIMEOUT_SECONDS` | `600` | 等待回调的超时秒数，超时自动释放回调端口 |
| `OAUTH_REDIRECT_URI` | *(空)* | 自定义 OAuth 回调地址。仅第六节「情况 C」（Web 应用类型客户端 + HTTPS）才需要 |
| `FLASK_DEBUG` | `0` | 设 `1` 开启自动重载，**仅本地开发用，生产别开** |

### `OAUTH_PORT` 与端口映射必须一致

`docker-compose.yml` 里有**两处**和回调端口相关，改一个就必须改另一个：

```yaml
ports:
  - "8765:8765"   # Web 界面
  - "8899:8899"   # ← 左边是宿主机端口，右边是容器内端口
environment:
  OAUTH_PORT: "8899"   # ← 必须等于上面映射的端口
```

简单记法：**`ports` 里两个数字要相同，且都要等于 `OAUTH_PORT`。** 左边是宿主机（Google 回调打到的位置），右边是容器内监听的位置。

改完记得重建容器，并同步修改 SSH 隧道里的端口号：

```bash
docker compose up -d
```

---

## 十一、日常运维

```bash
docker compose logs -f app      # 跟踪日志
docker compose restart app      # 重启
docker compose down             # 停止并删除容器（宿主机数据保留）
docker compose up -d --build    # 改代码后重新构建并启动
docker compose pull             # 更新基础镜像
```

---

## 十二、平滑升级 / 迁移到新机器

### 平滑升级（同一台机器）

数据都在挂载卷里，直接重建容器即可，不会丢：

```bash
cd ~/youtube-sub-manager

# 同步最新代码（在源机器上执行；注意排除 data/cache，别用旧数据覆盖线上数据）
rsync -av --exclude '.venv' --exclude '__pycache__' --exclude '.git' \
      --exclude 'data' --exclude 'cache' \
      ./ <用户名>@<主机地址>:~/youtube-sub-manager/

# 在目标主机上重新构建
docker compose up -d --build
```

> 升级前建议先备份（见第九节）。
> `--exclude 'data'` 很重要：它会保留目标主机上已有的数据库和自定义标签。

### 迁移到新机器

1. **旧机器上备份**

   ```bash
   cd ~/youtube-sub-manager
   tar -czf ~/yt-migrate.tar.gz config data
   ```

2. **把代码和备份传到新机器**

   ```bash
   rsync -av --exclude '.venv' --exclude '__pycache__' --exclude '.git' \
         --exclude 'data' --exclude 'cache' \
         ./ <用户名>@<新主机地址>:~/youtube-sub-manager/
   scp ~/yt-migrate.tar.gz <用户名>@<新主机地址>:~/
   ```

3. **新机器上恢复并启动**

   ```bash
   cd ~/youtube-sub-manager
   mkdir -p config data cache output
   tar -xzf ~/yt-migrate.tar.gz          # 覆盖 config/ 和 data/
   docker compose up -d --build
   curl -s http://localhost:8765/healthz # 确认 authorized 为 true
   ```

因为带上了 `token.json`，新机器**不需要重新授权**。确认无误后再停掉旧机器上的容器。

### 版本核对：确认容器的代码是新的

改了代码、重建了容器，但界面还是老样子？用这两步定位：

```bash
# ① 看后端返回的 features 字段（最可靠）
curl -s http://localhost:8765/healthz | python3 -m json.tool

# ② 看前端资源版本号
curl -s http://localhost:8765/healthz | grep -o '"app_js":[0-9]*'
```

- `/healthz` **没有 `features` 字段** → 容器里跑的还是旧代码，`docker compose up -d --build` 没生效
- 有 `features` → 后端是新的

另外，应用页面标题下方会显示一行小字 `前端 v… · 后端 v…`（前端 JS 和后端 `app.py` 的文件修改时间）。

- 重建容器后这两个数字应该变化
- 一直不变 → 容器里的文件还是旧的（重建没生效，或 rsync 没同步）
- 这行小字由后端模板渲染，所以只要能看见它，后端就是新版

前端资源现在带版本号（`/static/js/app.js?v=…`），文件改动后版本号会自动变化，浏览器会当成新文件重新下载，**通常不需要手动清缓存**。实在不行做一次硬刷新：

| 平台 | 快捷键 |
| --- | --- |
| macOS Chrome / Edge | `Cmd + Shift + R` |
| macOS Safari | `Cmd + Option + R` |
| Windows / Linux 浏览器 | `Ctrl + Shift + R` |
| 手机 | 清除该站点数据 |

### 旧版本可能踩到的坑：数据库写到容器内部

用很旧的版本部署时，容器可能**不认** `DB_PATH` 环境变量，把数据库写进容器内部，于是每次重建都会丢订阅数据。花 30 秒确认一下：

```bash
docker compose exec app printenv DB_PATH
docker compose exec app ls -l /app/data.db /app/data/ 2>&1
```

| 现象 | 含义 |
| --- | --- |
| 有 `/app/data/data.db`，`/app/data.db` 不存在 | ✅ 正常，数据落在挂载卷里 |
| 出现 `/app/data.db`，而 `/app/data/` 是空的 | ⚠️ 旧版代码忽略了 `DB_PATH`，数据写在容器内部，重建即丢 |

第二种情况下想保留已有数据再升级：

```bash
# 1. 先把旧位置的数据拷进挂载卷
docker compose exec app cp /app/data.db /app/data/data.db

# 2. 用最新代码重新构建（新版会读取 DB_PATH）
docker compose up -d --build

# 3. 确认数据在挂载卷里
docker compose exec app ls -l /app/data/data.db
```

---

## 十三、排错

**页面报「缺少 OAuth 凭证文件」**

`config/client_secrets.json` 不在挂载目录里。检查：

```bash
docker compose exec app ls -l /app/config/
```

申请方法见 [google-oauth.md](google-oauth.md)。

**`/healthz` 返回 `authorized: false`**

token 缺失或失效 → 按第七节重新授权。注意：如果 `docker compose exec` 里能看到文件、但宿主机对应目录里没有，说明路径写错了，检查 `docker-compose.yml` 的 `volumes`。

**授权页报 `[Errno 98] Address already in use`**

回调端口（默认 `8899`）被别的程序占用了。新版不会因为「一次没走完的授权」把端口占死（超时会自动释放），所以出现这个提示基本都是真的有别的程序在用这个端口。

```bash
# 看看是谁占了（macOS / Linux 通用）
lsof -nP -iTCP:8899 -sTCP:LISTEN
```

换一个空闲端口，**两处必须改成同一个值**：

```yaml
ports:
  - "8899:8899"     # 例如改成 "9899:9899"
environment:
  OAUTH_PORT: "9899"   # 同步改成 9899
```

```bash
docker compose up -d     # 生效
```

如果用 SSH 隧道，隧道参数里的端口也要一起改。

**端口冲突（Web 界面起不来）**

改 `docker-compose.yml` 里 Web 界面的映射，左边宿主机端口可以随意改：

```yaml
ports:
  - "18765:8765"   # 宿主机 18765 → 容器 8765
```

**构建慢 / 卡在 pip**

国内网络可以换镜像源，在 `Dockerfile` 的 `pip install` 之前加一行：

```dockerfile
RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple
```

**Apple Silicon 与 Intel 混用**

`python:3.12-slim` 是 multi-arch 镜像，两台机器上都会自动选对架构。若要把本机构建的镜像直接拷到另一架构的机器，构建时需显式指定：

```bash
docker build --platform linux/amd64 -t yt-sub-manager:amd64 .
```

**刷新很慢**

首次或手动点「🔄 刷新数据」要遍历几百个频道，约 20~60 秒，属正常。之后都走本地 SQLite，毫秒级返回。

**局域网能通但组网 / Tailscale 不通**

macOS 上先检查防火墙是否拦截了 Docker 的端口转发（见第六节「坑 ①」）。
