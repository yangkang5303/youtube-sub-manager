# 申请 Google OAuth 凭证（最详细版）

这份文档解决整个项目里**唯一一个真正麻烦的步骤**：拿到 `config/client_secrets.json`。

全程大约 3~5 分钟，只需要一个 Google 账号。**不需要**信用卡，**不需要**通过 Google 审核。

> 💡 如果你更喜欢"跟着提示走"，可以直接跑交互式引导，它会把这几个页面按顺序打开并帮你校验：
>
> ```bash
> python3 scripts/setup.py
> ```

> 📌 界面语言：Google Cloud Console 会跟随你的账号语言，所以下面的按钮我给出**中英对照**，
> 比如「桌面应用 / Desktop app」。找不到时按英文找一般没问题。

---

## 先回答两个常见疑问

**为什么不能用作者（或别人）现成的凭证？**

有两个硬性原因：

1. **安全**：`client_secret` 一旦公开就等于泄露，任何人都能冒充这个应用。
2. **配额**：Google 给每个项目每天 **10,000 单位**的 YouTube API 配额（大约够刷新 250 个订阅一次）。
   如果所有人共用一个项目，几个人的订阅加在一起会瞬间耗尽配额，**所有人都用不了**。

所以正确做法是"每人自备一份"。你申请到的凭证只属于你，也只消耗你自己的配额。

**这些凭证会泄露我的隐私吗？**

不会。`client_secrets.json` 只标识"哪个应用在请求授权"，**不含你的账号信息**。真正的访问凭证是授权完成后生成的
`config/token.json`，那个文件才需要保密 —— 而本项目已经把它加进 `.gitignore` 了。

---

## 第 1 步：创建项目

打开 <https://console.cloud.google.com/projectcreate>

- 「项目名称 / Project name」随便填，例如 `youtube-sub-manager`
- 「位置 / Location」保持默认（无组织）即可
- 点「创建 / Create」，等几秒让它建好
- **创建完后确认左上角的项目选择器显示的是这个新项目**（很容易忘，后面配置就跑到别的项目去了）

> 已经有项目也可以直接用，不一定要新建。

---

## 第 2 步：启用 YouTube Data API v3

打开 <https://console.cloud.google.com/apis/library/youtube.googleapis.com>

- 确认页面顶部显示的是你刚才那个项目
- 点蓝色的「启用 / Enable」按钮
- 等它跳转到"已启用 API"页面

> ⚠️ **这一步跳过是最常见的错误**。不启用的话，应用能授权成功，但一拉数据就报
> `403 accessNotConfigured`。

---

## 第 3 步：配置 OAuth 同意屏幕

打开 <https://console.cloud.google.com/auth/overview>

新版控制台会引导你走一个 "Get started" 流程，依次填：

| 字段 | 填什么 |
| --- | --- |
| 应用名称 / App name | 随便，例如 `YouTube Sub Manager`。授权页面上会显示这个名字 |
| 用户支持邮箱 / User support email | 选你自己的邮箱 |
| 受众 / Audience | 选「**外部 / External**」（个人 Gmail 账号只有这一个选项） |
| 联系邮箱 / Contact information | 填你自己的邮箱 |
| 同意政策 / Agree to policy | 勾选同意 |

填完点「创建 / Create」。

### 把自己加成测试用户

如果你的发布状态还是「测试 / Testing」，只有被列进**测试用户**名单的账号才能授权：

- 打开 <https://console.cloud.google.com/auth/audience>
- 在「测试用户 / Test users」区点「添加用户 / Add users」
- 填**你自己要授权那个 YouTube 账号的 Gmail 地址**
- 保存

> 用错账号是第二常见的坑：比如你用 A 账号建的项目，却在浏览器里用 B 账号授权，
> 就会看到「访问被阻止 / Access blocked」。

### 🔑 强烈建议：把发布状态改成「正式 / In production」

这是**省掉每 7 天重新授权一次**的关键。

Google 的规则是：OAuth 应用处于「测试 / Testing」状态时，签发的 refresh token **只有 7 天有效期**，
过期后必须重新走一遍授权。改成「正式 / In production」后，refresh token 就不再过期。

- 在 <https://console.cloud.google.com/auth/audience> 页面点「发布应用 / Publish app」，确认即可
- 因为只有你自己一个用户，**不需要**提交 Google 审核
- 代价：授权时会看到一个「Google hasn't verified this app / 此应用未经验证」的警告页

遇到那个警告页时这样过：

1. 点左下角「高级 / Advanced」
2. 点「继续前往 xxx（不安全）/ Go to xxx (unsafe)」
3. 继续授权

这是正常的，因为应用是你自己建的，Google 只是没审核过它。

---

## 第 4 步：创建 OAuth 客户端 ID

打开 <https://console.cloud.google.com/auth/clients>

1. 点「创建客户端 / Create client」
2. 「应用类型 / Application type」→ **必须选「桌面应用 / Desktop app」** ⚠️
3. 「名称 / Name」随便填，例如 `yt-sub-manager-desktop`
4. 点「创建 / Create」
5. 弹出窗口里点「下载 JSON / Download JSON」

> **为什么必须是「桌面应用」？**
> 桌面应用类型允许使用 `http://localhost:<任意端口>` 这种**回环地址**接收授权回调
> （这是 [Google 官方为已安装应用推荐的方式](https://developers.google.com/youtube/v3/guides/auth/installed-apps?hl=zh-cn)）。
> 「Web 应用」类型则必须登记一个固定的 HTTPS 域名，本地自建服务用不了。
>
> 桌面应用类型**不需要**你手动填重定向 URI，Google 会自动放行 localhost 的任意端口。

---

## 第 5 步：把文件放到正确位置

下载下来的文件名类似：

```
client_secret_1234567890-abcdefghijklmnop.apps.googleusercontent.com.json
```

把它**复制到项目的 `config/` 目录，并重命名为 `client_secrets.json`**：

```bash
# 假设文件还在下载目录里（macOS / Linux）
mv ~/Downloads/client_secret_*.json config/client_secrets.json
```

```powershell
# Windows PowerShell
Move-Item $env:USERPROFILE\Downloads\client_secret_*.json config\client_secrets.json
```

最终结构必须是：

```
你的项目目录/
└── config/
    └── client_secrets.json     ← 就是这个文件
```

> 懒得改名也没关系：`python3 scripts/setup.py` 会自动去 `~/Downloads`、`~/下载`、`~/Desktop`
> 等常见位置找它，找到后帮你复制并改名。

---

## 第 6 步：验证

```bash
python3 scripts/setup.py --check
```

看到 `✓ ... 可用` 就说明这一步彻底完成了。接下来回到 [README 的快速开始](../README.md#-快速开始docker推荐) 启动应用。

---

## 常见错误对照表

| 你看到的报错 | 原因 | 怎么修 |
| --- | --- | --- |
| `redirect_uri_mismatch` | 客户端类型选成了「Web 应用」，或填了错误的重定向 URI | 重新建一个「**桌面应用**」类型的客户端 |
| `Access blocked: This app's request is invalid` / 访问被阻止 | 授权时用的账号不在测试用户名单里 | 在[受众页面](https://console.cloud.google.com/auth/audience)把该账号加进「测试用户」 |
| `403 accessNotConfigured` / `YouTube Data API has not been used in project ...` | 忘了启用 API | 回到[第 2 步](#第-2-步启用-youtube-data-api-v3)启用 YouTube Data API v3 |
| `403 quotaExceeded` | 当天 10,000 单位配额用完了 | 等太平洋时间午夜重置；或调大 `REFRESH_INTERVAL_SECONDS` 少刷几次 |
| `invalid_grant: Token has been expired or revoked` | 应用还在「测试」状态，refresh token 满 7 天过期了；或你手动撤销过授权 | 重新授权；建议把发布状态改成「正式」永久解决 |
| `此应用未经验证 / Google hasn't verified this app` | 应用发布到正式但没过 Google 审核 | 正常现象。点「高级 → 继续前往」即可 |
| 授权页一直显示「等待授权中…」 | 浏览器所在的机器访问不到回调端口 | 见 [deployment.md 的授权排错](deployment.md) |
| `[Errno 98] Address already in use` | 回调端口 8899 被别的程序占用 | 见 [deployment.md 的端口排错](deployment.md) |

---

## 关于 API 配额

- 每个项目每天 **10,000 单位**（免费，太平洋时间午夜重置）
- 本项目的消耗主要在拉订阅列表和频道详情，**一次全量刷新约 40 单位**（以 250 个订阅计）
- 按默认设置（数据缓存 6 小时、只有打开页面才刷新），正常使用**远不会**触及上限
- 消耗细节见 [internals.md](internals.md)

---

## 撤销授权 / 彻底清除

想收回给本应用的权限：

- 打开 <https://myaccount.google.com/permissions>，找到你创建的应用名，点「移除访问权限」
- 然后删掉本地的 `config/token.json` 即可（下次打开会要求重新授权）

想连凭证一起删掉：删本地 `config/client_secrets.json`，再到
[Google Cloud Console 的客户端页面](https://console.cloud.google.com/auth/clients)删除该 OAuth 客户端。

---

## 安全提醒

- ❌ **不要把 `config/client_secrets.json` 或 `config/token.json` 提交到 Git、发到群里、或贴到 issue 里**
- ✅ 本项目已经用 `.gitignore` 忽略它们；推代码前可以跑一下 `git status` 确认没被跟踪
- ✅ 万一不小心泄露了：到 Google Cloud Console 删除该 OAuth 客户端，重新建一个即可（旧凭证立即失效）
