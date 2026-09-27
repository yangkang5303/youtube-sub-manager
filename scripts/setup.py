#!/usr/bin/env python3
"""交互式配置引导：手把手帮你拿到 config/client_secrets.json.

Google 的 OAuth 凭证申请是整个项目里最麻烦的一步（要建项目、启用 API、
配同意屏幕、建「桌面应用」客户端、下载 JSON），这个脚本把这一步变成
「跟着提示点」。

特点：
  * **只用 Python 标准库**，不需要 pip install，也不需要装 Docker；
  * 可以在宿主机跑，也可以在容器里跑（`docker compose run --rm app python scripts/setup.py`），
    因为 config/ 是挂载进去的，容器内外看到的是同一个目录；
  * 会顺手去 ~/Downloads / ~/下载 找你已经下载好的 client_secret_*.json，
    省得你手动改名和挪位置。

用法：

    python3 scripts/setup.py              # 交互式引导
    python3 scripts/setup.py --check      # 只校验现有配置，不交互（适合脚本/CI）
    python3 scripts/setup.py --no-open    # 不尝试自动打开浏览器
"""

import argparse
import glob
import json
import os
import sys

# Windows 的控制台默认不是 UTF-8，先把输出流掰成 UTF-8，避免中文乱码。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 与 app.py 保持同一套路径规则，这样在容器里也能正确指向挂载进来的 config/
CONFIG_DIR = os.path.abspath(os.environ.get("CONFIG_DIR") or os.path.join(BASE_DIR, "config"))
CLIENT_SECRETS = os.path.join(CONFIG_DIR, "client_secrets.json")

# Google Cloud 控制台的直达链接（省得用户在一堆菜单里找）
URLS = {
    "project": "https://console.cloud.google.com/projectcreate",
    "api": "https://console.cloud.google.com/apis/library/youtube.googleapis.com",
    "consent": "https://console.cloud.google.com/auth/overview",
    "clients": "https://console.cloud.google.com/auth/clients",
}

# 去哪儿找用户刚下载下来的凭证文件
SEARCH_DIRS = [
    CONFIG_DIR,
    BASE_DIR,
    os.path.expanduser("~/Downloads"),
    os.path.expanduser("~/下载"),
    os.path.expanduser("~/Desktop"),
    os.path.expanduser("~/桌面"),
]


def line(char="─", width=72):
    print(char * width)


def step(n, title):
    print()
    line()
    print(f"  第 {n} 步 · {title}")
    line()


def load_and_validate(path):
    """校验凭证文件。返回 (data, error_message)。"""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        return None, f"这个文件不是合法的 JSON（{e}）。可能下载不完整，请重新下载。"
    except OSError as e:
        return None, f"读取失败：{e}"

    if not isinstance(data, dict):
        return None, "文件内容不是预期的 JSON 对象。"

    if "installed" in data:
        cred = data["installed"]
        if not cred.get("client_id") or not cred.get("client_secret"):
            return None, "文件里缺少 client_id 或 client_secret 字段。"
        return data, None

    if "web" in data:
        return None, (
            "这是「Web 应用」类型的 OAuth 客户端，本项目需要「桌面应用」类型。\n"
            "    原因：桌面应用才能用 http://localhost 回环地址接收授权回调，\n"
            "    而 Web 应用必须登记一个固定的 HTTPS 域名。\n"
            "    → 请回到 Google Cloud Console，重新创建一个「桌面应用」类型的 OAuth 客户端。"
        )

    return None, "无法识别的凭证格式（既没有 installed 也没有 web 字段）。"


def find_candidates():
    """在常见位置找 client_secret*.json（排除已经就位的那个）。"""
    found = []
    for d in SEARCH_DIRS:
        if not d or not os.path.isdir(d):
            continue
        for pattern in ("client_secret*.json", "client_secrets.json"):
            for p in glob.glob(os.path.join(d, pattern)):
                p = os.path.abspath(p)
                if p == os.path.abspath(CLIENT_SECRETS):
                    continue          # 已经在目标位置了
                if p not in found:
                    found.append(p)
    return found


def install(src):
    """把凭证文件复制到 config/client_secrets.json。"""
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(src, "rb") as f:
        blob = f.read()
    with open(CLIENT_SECRETS, "wb") as f:
        f.write(blob)
    try:
        os.chmod(CLIENT_SECRETS, 0o600)   # 凭证文件收紧权限
    except OSError:
        pass


def open_pages(urls):
    """尽力打开浏览器；容器里没有浏览器就静默失败。"""
    try:
        import webbrowser
    except ImportError:
        return False
    opened = False
    for u in urls:
        try:
            opened = webbrowser.open(u, new=2) or opened
        except Exception:
            pass
    return opened


def print_instructions(open_browser):
    print("""
这一步需要你在浏览器里操作 Google Cloud Console，大约 3~5 分钟。
整个过程只在**你自己的** Google 账号下建一个项目，凭证不会发给任何人。

下面 4 个页面我按顺序列出来了，建议按顺序做完，不要跳步。
""")
    for i, (key, title) in enumerate([
        ("project", "创建（或选择一个）项目"),
        ("api", "启用「YouTube Data API v3」—— 不启用后面会报 403"),
        ("consent", "配置 OAuth 同意屏幕：用户类型选「外部」，"
                    "填应用名和你的邮箱；在「受众 / Audience」里把自己加成测试用户"),
        ("clients", "创建凭据 → OAuth 客户端 ID → 应用类型必须选「桌面应用」→ 创建后下载 JSON"),
    ], 1):
        print(f"  {i}. {title}")
        print(f"     {URLS[key]}")

    print("""
  最后一步很关键：下载下来的文件名类似
      client_secret_1234567890-abcdefg.apps.googleusercontent.com.json
  把它复制到本项目的 config/ 目录，并重命名为
      client_secrets.json

  懒得改名也没关系：等你下载完，回到这里按回车，我会自动去找它并改名。
""")

    if open_browser:
        try:
            answer = input("现在帮你把这 4 个页面在浏览器里打开？[Y/n] ").strip().lower()
        except EOFError:
            answer = "n"
        if answer in ("", "y", "yes"):
            if open_pages(URLS.values()):
                print("  ✓ 已尝试打开浏览器（没反应的话请手动复制上面的链接）")
            else:
                print("  ! 没能自动打开浏览器，请手动复制上面的链接")


def verify_once(interactive=True):
    """检查一次凭证是否就位且合法。返回 True 表示已配置完成。"""
    if os.path.exists(CLIENT_SECRETS):
        _, err = load_and_validate(CLIENT_SECRETS)
        if err is None:
            print(f"\n  ✓ 凭证已就位且格式正确：{CLIENT_SECRETS}")
            return True
        print(f"\n  ✗ 已存在 {CLIENT_SECRETS}，但有问题：\n    {err}")
        if not interactive:
            return False
        try:
            answer = input("  删掉它重新放一份？[y/N] ").strip().lower()
        except EOFError:
            return False
        if answer in ("y", "yes"):
            try:
                os.remove(CLIENT_SECRETS)
            except OSError as e:
                print(f"  删除失败：{e}")
                return False
        else:
            return False

    # 没找到目标文件 —— 去常见位置翻一翻
    candidates = find_candidates()
    if candidates:
        print("\n  我在这些位置找到了可能是凭证的文件：")
        for i, p in enumerate(candidates, 1):
            print(f"    {i}. {p}")
        if not interactive:
            return False
        try:
            answer = input("  用哪一个？（序号，直接回车跳过） ").strip()
        except EOFError:
            answer = ""
        if answer.isdigit() and 1 <= int(answer) <= len(candidates):
            src = candidates[int(answer) - 1]
            _, err = load_and_validate(src)
            if err:
                print(f"  ✗ 这个文件不能用：\n    {err}")
                return False
            install(src)
            print(f"  ✓ 已复制到 {CLIENT_SECRETS}")
            return True
    return False


def print_done():
    line("═")
    print("  🎉 配置完成！接下来启动应用：")
    line("═")
    print("""
  【Docker 方式，推荐】
      mkdir -p config data cache output
      docker compose up -d --build

  【本地 Python 方式】
      pip install -r requirements.txt
      python3 app.py

  启动后打开 http://localhost:8765 —— 会自动跳到授权页，
  点「前往 Google 授权」并同意，页面就会自动跳回应用。

  提示：如果这个 OAuth 应用还停留在「测试」发布状态，refresh token
  每 7 天就会失效一次，需要重复授权。把「受众 / Audience」里的发布状态
  改成「正式 / In production」就不会过期了（只有你自己用，不需要
  Google 审核，授权时会看到一个「未经验证的应用」警告页，点
  「高级 → 继续前往」即可）。详见 docs/google-oauth.md。
""")


def main():
    ap = argparse.ArgumentParser(
        description="交互式配置引导：帮你准备好 config/client_secrets.json",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--check", action="store_true",
                    help="只校验现有配置，不交互（退出码 0 = 已配置好）")
    ap.add_argument("--no-open", action="store_true",
                    help="不要尝试自动打开浏览器")
    args = ap.parse_args()

    print()
    line("═")
    print("  YouTube Subscription Manager · 配置引导")
    line("═")

    if args.check:
        if os.path.exists(CLIENT_SECRETS):
            _, err = load_and_validate(CLIENT_SECRETS)
            if err is None:
                print(f"  ✓ {CLIENT_SECRETS} 可用")
                return 0
            print(f"  ✗ {CLIENT_SECRETS} 有问题：{err}")
            return 1
        print(f"  ✗ 还没配置：找不到 {CLIENT_SECRETS}")
        return 1

    # 已经在目标位置且合法 → 直接收工
    if os.path.exists(CLIENT_SECRETS) and load_and_validate(CLIENT_SECRETS)[1] is None:
        print(f"\n  ✓ 已经配置好了：{CLIENT_SECRETS}")
        print("  （想换一份凭证就先把这个文件删掉，再重新运行本脚本）")
        print_done()
        return 0

    # 万一 candidates 里已经有能用的，先问一句要不要直接用，省得重复申请
    if verify_once(interactive=True):
        print_done()
        return 0

    print_instructions(open_browser=not args.no_open)

    # 循环等待用户把文件放好
    while True:
        print()
        line()
        try:
            answer = input("把 client_secrets.json 放好后按回车，我来校验（q 退出）：").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\n已取消。")
            return 1
        if answer in ("q", "quit", "exit"):
            print("\n随时可以重新运行：python3 scripts/setup.py")
            return 1
        if verify_once(interactive=True):
            print_done()
            return 0
        print("\n  ✗ 还没找到可用的凭证，请确认：")
        print(f"      · 文件放在了 {CONFIG_DIR}")
        print("      · 文件名是 client_secrets.json")
        print("      · OAuth 客户端类型是「桌面应用」（不是 Web 应用）")


if __name__ == "__main__":
    sys.exit(main())
