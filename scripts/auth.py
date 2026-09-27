#!/usr/bin/env python3
"""无浏览器环境（Docker / 远程主机）下的 Google OAuth 授权工具.

**更省事的做法**：直接打开应用网页，它会把授权链接显示在页面上
（`/authorize` 页面，带「前往 Google 授权」按钮和自动跳转），不需要看终端。

只有在没有浏览器 / 想纯命令行操作时才用它：

    docker compose exec app python scripts/auth.py

然后：
  1. 终端会打印一个 Google 授权 URL
  2. 把它复制到**宿主机**（你的 Mac）浏览器打开
  3. 同意授权后，浏览器会跳转到 http://localhost:<OAUTH_PORT>/?code=...
     该端口已在 docker-compose.yml 里映射到容器（默认 8899）
  4. 脚本收到 code，自动写入 config/token.json
     之后执行 docker compose restart app 让应用重新加载凭证

如果该端口被占用，改 docker-compose.yml 里的 OAUTH_PORT **和** ports 映射
（两处必须一致）后重启容器。
"""

import http.server
import os
import socketserver
import sys
import urllib.parse

# oauthlib 默认禁止 http 回调；localhost 是官方允许的例外，这里显式放行
os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")

try:
    from google_auth_oauthlib.flow import Flow
except ImportError:
    sys.exit("缺少依赖，请先 pip install -r requirements.txt")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.path.abspath(os.environ.get("CONFIG_DIR") or os.path.join(BASE_DIR, "config"))
CLIENT_SECRETS = os.path.join(CONFIG_DIR, "client_secrets.json")
TOKEN_PATH = os.path.join(CONFIG_DIR, "token.json")

PORT = int(os.environ.get("OAUTH_PORT", "8899"))

# 回调地址：
#   默认 http://localhost:<OAUTH_PORT>/（本仓库 docker-compose.yml 用 8899）
#   —— 适用于「桌面应用」类型的 OAuth 客户端
#   若用 Tailscale Serve 提供 HTTPS，且 OAuth 客户端是「Web 应用」，
#   可设 OAUTH_REDIRECT_URI=https://<机器名>.<tailnet>.ts.net/ 并在 Google 后台登记该地址
REDIRECT_URI = os.environ.get("OAUTH_REDIRECT_URI") or f"http://localhost:{PORT}/"

SCOPES = [
    "https://www.googleapis.com/auth/youtube.force-ssl",
    "https://www.googleapis.com/auth/youtube.readonly",
]

_received = {}

PAGE = """<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<title>授权结果</title><style>
body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
background:#15171b;color:#d6dade;display:grid;place-items:center;height:100vh;margin:0}}
.box{{text-align:center;padding:40px 48px;border:1px solid #2b2f36;border-radius:14px;background:#1b1e23}}
h1{{font-size:20px;margin:0 0 8px;color:#f0f2f5}}
p{{color:#9aa2ac;font-size:14px;margin:0}}
</style></head><body><div class="box"><h1>{title}</h1><p>{detail}</p></div></body></html>"""


class CallbackHandler(http.server.BaseHTTPRequestHandler):
    """接收 Google 的 ?code=... 回调，处理一次即可退出."""

    def do_GET(self):  # noqa: N802 (stdlib naming)
        params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        _received.update({k: v[0] for k, v in params.items()})

        if "code" in params:
            html = PAGE.format(title="✅ 授权成功", detail="可以关闭此页面，回到终端查看结果。")
        elif "error" in params:
            html = PAGE.format(title="❌ 授权失败", detail=params.get("error", ["未知错误"])[0])
        else:
            html = PAGE.format(title="⏳ 等待回调", detail="未收到 code 参数。")

        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass  # 静音 stdlib 访问日志


def main():
    if not os.path.exists(CLIENT_SECRETS):
        sys.exit(f"找不到凭证文件: {CLIENT_SECRETS}\n"
                 f"请把 Google Cloud Console 下载的 client_secret_*.json 放到 config/client_secrets.json")

    flow = Flow.from_client_secrets_file(CLIENT_SECRETS, SCOPES)
    flow.redirect_uri = REDIRECT_URI

    auth_url, _ = flow.authorization_url(access_type="offline", prompt="consent")

    print("=" * 72)
    print("请在浏览器打开下面的链接完成授权：")
    print()
    print(auth_url)
    print()
    print(f"回调地址: {REDIRECT_URI}")
    if REDIRECT_URI.startswith("http://localhost") or REDIRECT_URI.startswith("http://127."):
        print("→ 若浏览器不在本机，请用 SSH 隧道把此端口转发过去：")
        print(f"   ssh -N -L {PORT}:localhost:{PORT} <这台机器的地址>")
    print(f"正在监听 0.0.0.0:{PORT} 等待回调 ... (Ctrl+C 取消)")
    print("=" * 72)

    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("0.0.0.0", PORT), CallbackHandler) as httpd:
        httpd.handle_request()   # 只处理第一个请求

    if "error" in _received:
        sys.exit(f"授权被拒绝: {_received['error']}")
    if "code" not in _received:
        sys.exit("没有收到授权码，请重试。")

    flow.fetch_token(code=_received["code"])

    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(TOKEN_PATH, "w", encoding="utf-8") as f:
        f.write(flow.credentials.to_json())

    print(f"\n✅ 授权成功，凭证已写入 {TOKEN_PATH}")
    print("现在可以重启容器：docker compose restart app")


if __name__ == "__main__":
    main()
