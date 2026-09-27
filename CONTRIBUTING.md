# 参与贡献

欢迎提 Issue 和 PR！这个项目本来是自用工具，能帮到更多人当然更好。

## 🐛 提 Bug 之前

先在 [常见问题](README.md#-常见问题) 和 [docs/](docs) 里搜一下，
不少问题（7 天重新授权、配额、端口占用）都已经有答案了。

提 Issue 时请**务必**附上：

- 运行方式（Docker / 本地 Python）和操作系统
- 复现步骤
- 相关日志：`docker compose logs --tail=100 app`

> ⚠️ **提交前请检查日志和截图，删掉 `client_secrets.json` / `token.json` 的内容。**
> 那是你的账号凭证，贴出来等于泄露。

## 💻 本地开发

```bash
git clone https://github.com/<你的用户名>/youtube-sub-manager.git
cd youtube-sub-manager
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 准备好 config/client_secrets.json（见 docs/google-oauth.md）
python3 app.py          # http://localhost:8765
```

本地运行不需要 Docker。没有凭证也能启动 —— 页面会引导你去配置。

## ✅ 提交 PR 之前

请跑一遍测试，确保没把东西改坏：

```bash
python3 -m unittest discover -s tests -v
```

测试是**纯标准库 unittest**，不联网、不需要真实凭证（用假的 flow 对象跑 OAuth 回调逻辑），
所以在你自己的机器上应该几秒就跑完。

如果你改了 Docker 相关的东西，也顺手验证一下镜像能起来：

```bash
docker compose up -d --build
curl -s http://localhost:8765/healthz
```

## 📐 代码约定

- **Python**：PEP 8，4 空格缩进，注释和文档字符串用中文（和现有代码保持一致）
- **注释写"为什么"**，不要写"是什么" —— 变量名已经说明了是什么
- **前端**：原生 JS + CSS，不引入构建工具和框架，保持"克隆下来就能跑"
- **不要新增依赖**，除非有充分理由（`requirements.txt` 越短越好上手）
- **不要提交** `config/`、`data/`、`cache/`、`output/` 里的任何东西

## 🔒 安全红线

以下内容**一律不接受**进仓库，PR 里出现会直接关闭：

- 任何真实的 `client_secrets.json` / `token.json` / access token / refresh token
- 真实的订阅数据、频道列表、数据库文件
- 你自己的内网 IP、域名、主机名、用户名

CI 里有一个 `secret-scan` 任务会自动检查这些，别抱侥幸心理 🙂

## 📄 License

提交 PR 即表示你同意你的贡献以 [MIT License](LICENSE) 授权。
