#!/usr/bin/env python3
"""在不同环境之间同步「自定义标签」.

自定义标签保存在各环境自己的 SQLite 里（不是 YouTube 侧），
所以开发环境和部署环境默认是两套。这个脚本用来把标签从一边搬到另一边。

标签以 channel_id 为键，两个环境订阅相同账号时可以直接对应。

用法：

  # 本机(开发) → Mac mini(部署)：把本机的标签推上去
  python3 scripts/sync_labels.py --to http://100.93.40.53:8765

  # Mac mini → 本机：把服务器上打的标签拉下来
  python3 scripts/sync_labels.py --from http://100.93.40.53:8765 --to http://localhost:8765

  # 只看差异，不实际改动
  python3 scripts/sync_labels.py --to http://100.93.40.53:8765 --dry-run

  # 目标开了访问口令（ACCESS_PASSWORD）时
  python3 scripts/sync_labels.py --to http://... --user admin --password 你的密码

默认「来源」是本地数据库（DB_PATH 或项目根目录的 data.db）。
"""

import argparse
import base64
import json
import os
import sqlite3
import sys
import urllib.error
import urllib.request

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def local_db_path():
    """优先用 DB_PATH 环境变量，否则用项目根目录的 data.db."""
    return os.path.abspath(os.environ.get("DB_PATH") or os.path.join(BASE_DIR, "data.db"))


def read_from_db(db_path):
    """返回 {channel_id: [标签, ...]}，只包含有标签的频道."""
    if not os.path.exists(db_path):
        sys.exit(f"找不到数据库: {db_path}")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT channel_id, title, custom_labels FROM subscriptions"
        ).fetchall()
    finally:
        conn.close()

    out = {}
    for r in rows:
        try:
            labels = json.loads(r["custom_labels"] or "[]")
        except (ValueError, TypeError):
            labels = []
        labels = [str(x).strip() for x in labels if str(x).strip()]
        if labels:
            out[r["channel_id"]] = labels
    return out


def _request(url, method="GET", body=None, auth=None):
    headers = {}
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if auth:
        token = base64.b64encode(f"{auth[0]}:{auth[1]}".encode()).decode()
        headers["Authorization"] = "Basic " + token

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, json.load(resp)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        raise SystemExit(f"请求失败 {e.code} {url}\n{detail}")


def read_from_api(base_url, auth=None):
    """从目标环境读取当前标签，返回 ({channel_id: [标签]}, {channel_id: 标题})."""
    _, data = _request(base_url.rstrip("/") + "/api/subscriptions", auth=auth)
    labels, titles = {}, {}
    for s in data.get("subscriptions", []):
        cid = s.get("channel_id")
        if not cid:
            continue
        titles[cid] = s.get("title", cid)
        cur = [str(x).strip() for x in (s.get("custom_labels") or []) if str(x).strip()]
        if cur:
            labels[cid] = cur
    return labels, titles


def apply_labels(base_url, channel_ids, label, action, auth=None):
    return _request(
        base_url.rstrip("/") + "/api/labels",
        method="POST",
        body={"channel_ids": channel_ids, "label": label, "action": action},
        auth=auth,
    )


def main():
    ap = argparse.ArgumentParser(description="同步自定义标签")
    ap.add_argument("--from-db", dest="from_db", default=None,
                    help="来源数据库路径（默认 DB_PATH 或 ./data.db）")
    ap.add_argument("--from", dest="from_api", default=None,
                    help="来源 API 地址；不填则读本地数据库")
    ap.add_argument("--to", dest="to_api", required=True, help="目标 API 地址")
    ap.add_argument("--user", default=None, help="目标环境的访问口令用户名")
    ap.add_argument("--password", default=None, help="目标环境的访问口令")
    ap.add_argument("--dry-run", action="store_true", help="只显示差异，不做改动")
    args = ap.parse_args()

    auth = (args.user, args.password) if args.password else None

    # ── 读取来源 ──
    if args.from_api:
        print(f"来源: {args.from_api} (API)")
        source, _ = read_from_api(args.from_api, auth=auth)
    else:
        db = args.from_db or local_db_path()
        print(f"来源: {db} (数据库)")
        source = read_from_db(db)

    # ── 读取目标当前状态 ──
    print(f"目标: {args.to_api} (API)")
    target, titles = read_from_api(args.to_api, auth=auth)
    print(f"  目标共有 {len(titles)} 个频道\n")

    if not source:
        print("来源没有任何自定义标签，无需同步。")
        return

    # ── 计算差异 ──
    to_add, to_remove = [], []
    missing = []
    for cid, labels in source.items():
        if cid not in titles:
            missing.append(cid)
            continue
        cur = set(target.get(cid, []))
        for lab in labels:
            if lab not in cur:
                to_add.append((cid, lab))
        for lab in cur:
            if lab not in labels:
                to_remove.append((cid, lab))

    print(f"来源有标签的频道: {len(source)}")
    print(f"需要添加: {len(to_add)} 项 | 需要移除: {len(to_remove)} 项")
    if missing:
        print(f"目标环境中不存在这些频道（跳过）: {len(missing)}")

    if not to_add and not to_remove:
        print("\n两边已经一致，无需同步 ✓")
        return

    if args.dry_run:
        print("\n--- 将要添加 ---")
        for cid, lab in to_add[:20]:
            print(f"  {titles.get(cid, cid)[:28]:30s} + {lab}")
        if len(to_add) > 20:
            print(f"  ... 还有 {len(to_add) - 20} 项")
        print("\n--- 将要移除 ---")
        for cid, lab in to_remove[:20]:
            print(f"  {titles.get(cid, cid)[:28]:30s} - {lab}")
        if len(to_remove) > 20:
            print(f"  ... 还有 {len(to_remove) - 20} 项")
        print("\n(dry-run，未做任何改动)")
        return

    # ── 按标签聚合，减少请求次数 ──
    grouped_add = {}
    for cid, lab in to_add:
        grouped_add.setdefault(lab, []).append(cid)
    grouped_rm = {}
    for cid, lab in to_remove:
        grouped_rm.setdefault(lab, []).append(cid)

    done = 0
    for lab, ids in grouped_add.items():
        _, r = apply_labels(args.to_api, ids, lab, "add", auth=auth)
        done += r.get("changed", 0)
        print(f"  + 「{lab}」→ {r.get('changed', 0)} 个频道")
    for lab, ids in grouped_rm.items():
        _, r = apply_labels(args.to_api, ids, lab, "remove", auth=auth)
        done += r.get("changed", 0)
        print(f"  - 「{lab}」→ {r.get('changed', 0)} 个频道")

    print(f"\n完成，共改动 {done} 处。")


if __name__ == "__main__":
    main()
