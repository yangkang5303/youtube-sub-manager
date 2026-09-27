"""YouTube 订阅管理 - Flask 后端 API"""

import errno
import hmac
import http.server
import json
import os
import re
import sqlite3
import threading
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from flask import (Flask, jsonify, render_template, redirect, url_for,
                   request, Response, send_file, make_response)
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

app = Flask(__name__)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _env_path(name, default):
    """允许用环境变量覆盖路径（Docker 部署时把状态挂到 volume 上）."""
    return os.path.abspath(os.environ.get(name) or default)


CONFIG_DIR = _env_path("CONFIG_DIR", os.path.join(BASE_DIR, "config"))
OUTPUT_DIR = _env_path("OUTPUT_DIR", os.path.join(BASE_DIR, "output"))
DB_PATH = _env_path("DB_PATH", os.path.join(BASE_DIR, "data.db"))
THUMB_DIR = _env_path("THUMB_DIR", os.path.join(BASE_DIR, "cache", "thumbs"))
CREDENTIALS_PATH = os.path.join(CONFIG_DIR, "client_secrets.json")
TOKEN_PATH = os.path.join(CONFIG_DIR, "token.json")

# 本地数据库「新鲜度」阈值：超过该秒数才认为需要重新拉取 API。
REFRESH_INTERVAL_SECONDS = int(os.environ.get("REFRESH_INTERVAL_SECONDS", 6 * 3600))

# 可选：后台定时刷新间隔（秒）。0 = 关闭（默认），只在页面请求时按需刷新。
# 开启后数据无需打开页面也会保持最新，代价是持续消耗 API 配额。
AUTO_REFRESH_SECONDS = int(os.environ.get("AUTO_REFRESH_SECONDS", "0"))

# 可选访问口令：设置 ACCESS_PASSWORD 后，除 /healthz 外所有请求都要求 HTTP Basic 认证。
# 用于把应用暴露到局域网 / Tailscale 时，避免被同网段的其他设备直接访问。
ACCESS_USER = os.environ.get("ACCESS_USER", "admin")
ACCESS_PASSWORD = os.environ.get("ACCESS_PASSWORD", "")

SCOPES = [
    "https://www.googleapis.com/auth/youtube.force-ssl",
    "https://www.googleapis.com/auth/youtube.readonly",
]

# oauthlib 默认禁止 http 回调，但本机 loopback 是官方允许的例外。
# 回调地址是 http://localhost:<port>/，这里显式放行（否则换 token 会抛
# InsecureTransportError）。与 scripts/auth.py 保持一致。
os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")

# 主题分类 URL → 友好名称映射
# 实际 API 返回的是 Wikipedia 主题 URL（及部分旧 schema.org URL），此处统一映射。
CATEGORY_MAP = {
    # Wikipedia 主题（YouTube topicDetails.topicCategories 实际返回）
    "https://en.wikipedia.org/wiki/TechArticle": "科技",
    "https://en.wikipedia.org/wiki/Technology": "科技",
    "https://en.wikipedia.org/wiki/Video_game_culture": "游戏",
    "https://en.wikipedia.org/wiki/Action_game": "游戏",
    "https://en.wikipedia.org/wiki/Action-adventure_game": "游戏",
    "https://en.wikipedia.org/wiki/Role-playing_video_game": "游戏",
    "https://en.wikipedia.org/wiki/Simulation_video_game": "游戏",
    "https://en.wikipedia.org/wiki/Sports_game": "游戏",
    "https://en.wikipedia.org/wiki/Film": "影视",
    "https://en.wikipedia.org/wiki/Television_program": "电视节目",
    "https://en.wikipedia.org/wiki/Entertainment": "娱乐",
    "https://en.wikipedia.org/wiki/Performing_arts": "艺术",
    "https://en.wikipedia.org/wiki/Music": "音乐",
    "https://en.wikipedia.org/wiki/Pop_music": "音乐",
    "https://en.wikipedia.org/wiki/Rock_music": "音乐",
    "https://en.wikipedia.org/wiki/Electronic_music": "音乐",
    "https://en.wikipedia.org/wiki/Classical_music": "音乐",
    "https://en.wikipedia.org/wiki/Christian_music": "音乐",
    "https://en.wikipedia.org/wiki/Independent_music": "音乐",
    "https://en.wikipedia.org/wiki/Music_of_Asia": "音乐",
    "https://en.wikipedia.org/wiki/Rhythm_and_blues": "音乐",
    "https://en.wikipedia.org/wiki/Soul_music": "音乐",
    "https://en.wikipedia.org/wiki/Sport": "体育",
    "https://en.wikipedia.org/wiki/Association_football": "体育",
    "https://en.wikipedia.org/wiki/Motorsport": "体育",
    "https://en.wikipedia.org/wiki/Food": "美食",
    "https://en.wikipedia.org/wiki/Tourism": "旅行",
    "https://en.wikipedia.org/wiki/Knowledge": "教育/学习",
    "https://en.wikipedia.org/wiki/Business": "商业",
    "https://en.wikipedia.org/wiki/Health": "健康",
    "https://en.wikipedia.org/wiki/Hobby": "兴趣爱好",
    "https://en.wikipedia.org/wiki/Humour": "幽默",
    "https://en.wikipedia.org/wiki/Lifestyle_(sociology)": "生活方式",
    "https://en.wikipedia.org/wiki/Society": "社会",
    "https://en.wikipedia.org/wiki/Politics": "政治",
    "https://en.wikipedia.org/wiki/Religion": "宗教",
    "https://en.wikipedia.org/wiki/Pet": "宠物",
    "https://en.wikipedia.org/wiki/Vehicle": "汽车",
    # 旧版 schema.org 主题（向后兼容）
    "http://schema.org/TechArticle": "科技",
    "http://schemas.google.com/Games": "游戏",
    "http://schema.org/Movie": "影视",
    "http://schema.org/MusicComposition": "音乐",
    "http://schema.org/TVSeries": "电视节目",
    "http://schema.org/SportsActivity": "运动",
    "http://schema.org/NewsArticle": "新闻",
    "http://schema.org/Recipe": "美食",
    "http://schema.org/TravelAction": "旅行",
    "http://schema.org/Book": "教育/学习",
    "http://schema.org/Blog": "博客/Vlog",
    "http://schema.org/EntertainmentBusiness": "娱乐",
    "/Film_and_animation": "动画",
    "/Computers_and_technology": "计算机技术",
    "/Music": "音乐",
    "/Sports": "体育",
    "/Food_and_drink": "美食",
    "/Hobbies_and_interest": "兴趣爱好",
    "/People_and_blog": "个人博客",
    "/Society_and_politics": "社会政治",
    "/Science_and_technology": "科学技术",
}


def category_label(url):
    """将主题分类 URL 转换为友好名称.

    Wikipedia URL 会取末尾 slug，将下划线转空格并去除括号后缀，
    例如 Lifestyle_(sociology) → Lifestyle。
    """
    if url in CATEGORY_MAP:
        return CATEGORY_MAP[url]
    slug = url.split("/")[-1] if "/" in url else url
    # 去掉括号内说明，如 Music_of_Asia → Music of Asia、Lifestyle_(sociology) → Lifestyle
    base = slug.split("(")[0].replace("_", " ").strip()
    return base or "未分类"


def categories_of(sub):
    """返回一个频道的全部分类标签（去重、保持 YouTube 返回顺序）.

    YouTube 的 topicCategories 一个频道通常有 2-3 个（最多 7 个），
    之前只取第一个会丢掉 73% 的信息，这里全部保留。
    """
    labels = []
    for c in (sub.get("topic_categories") or []):
        label = category_label(c)
        if label and label not in labels:
            labels.append(label)
    return labels or ["未分类"]


# ── 用户自定义标签 ──
MAX_LABEL_LEN = 24
MAX_LABELS_PER_CHANNEL = 20


def _clean_labels(raw):
    """规范化自定义标签列表：去空、去重、限长、限量，保持原有顺序."""
    if not isinstance(raw, (list, tuple)):
        return []
    out = []
    for item in raw:
        if not isinstance(item, str):
            continue
        name = item.strip()[:MAX_LABEL_LEN]
        if name and name not in out:
            out.append(name)
        if len(out) >= MAX_LABELS_PER_CHANNEL:
            break
    return out


def labels_of(sub):
    """频道的自定义标签."""
    return _clean_labels(sub.get("custom_labels"))


def all_tags_of(sub):
    """YouTube 自动分类 + 自定义标签，用于分组与筛选."""
    cats = sub.get("categories") or categories_of(sub)
    return list(cats) + [l for l in labels_of(sub) if l not in cats]


def days_since_upload(upload_time):
    """计算距离某个 ISO 时间戳的天数（-1 表示未知/无上传）."""
    if not upload_time:
        return -1
    try:
        dt = upload_time.replace("Z", "+00:00")
        dt = datetime.fromisoformat(dt)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt).days
    except (ValueError, TypeError):
        return -1


# ────────────────────────── 本地小型数据库 (SQLite) ──────────────────────────
# 把订阅快照落到本地，之后优先从 DB 读取，仅在过期/手动刷新时才调用 YouTube API。

_SCHEMA = """
CREATE TABLE IF NOT EXISTS subscriptions (
    channel_id       TEXT PRIMARY KEY,
    subscription_id  TEXT NOT NULL,
    title            TEXT NOT NULL,
    thumbnail        TEXT,
    custom_url       TEXT,          -- 频道 @handle，用于拼接 .../@handle/videos
    subscriber_count INTEGER DEFAULT 0,
    video_count      INTEGER DEFAULT 0,
    topic_categories TEXT,          -- JSON 数组：原始 topic URL
    categories       TEXT,          -- JSON 数组：全部映射后的中文分类（一个频道可有多个）
    custom_labels    TEXT,          -- JSON 数组：用户自己创建的标签
    primary_category TEXT,          -- 主分类（= categories[0]）
    description      TEXT,
    country          TEXT,
    last_upload      TEXT,
    days_since_upload INTEGER DEFAULT -1,
    fetched_at       TEXT
);
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""

_db_lock = threading.Lock()


def _get_conn():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with _db_lock:
        conn = _get_conn()
        try:
            conn.executescript(_SCHEMA)
            # 轻量迁移：老库补上 categories / custom_url 列
            cols = {r["name"] for r in conn.execute("PRAGMA table_info(subscriptions)")}
            if "categories" not in cols:
                conn.execute("ALTER TABLE subscriptions ADD COLUMN categories TEXT")
            if "custom_url" not in cols:
                conn.execute("ALTER TABLE subscriptions ADD COLUMN custom_url TEXT")
            if "custom_labels" not in cols:
                conn.execute("ALTER TABLE subscriptions ADD COLUMN custom_labels TEXT")
            conn.commit()
        finally:
            conn.close()


_SUB_COLUMNS = (
    "channel_id, subscription_id, title, thumbnail, custom_url,"
    " subscriber_count, video_count,"
    " topic_categories, categories, custom_labels, primary_category,"
    " description, country,"
    " last_upload, days_since_upload, fetched_at"
)
_SUB_PLACEHOLDERS = ",".join(["?"] * 16)


def _sub_row_values(s, now):
    """把一个订阅 dict 转成 INSERT 用的值元组."""
    cats = s.get("categories") or categories_of(s)
    return (
        s.get("channel_id", ""),
        s.get("subscription_id", ""),
        s.get("title", ""),
        s.get("thumbnail", ""),
        s.get("custom_url", ""),
        int(s.get("subscriber_count", 0) or 0),
        int(s.get("video_count", 0) or 0),
        json.dumps(s.get("topic_categories", []), ensure_ascii=False),
        json.dumps(cats, ensure_ascii=False),
        json.dumps(_clean_labels(s.get("custom_labels")), ensure_ascii=False),
        s.get("primary_category") or (cats[0] if cats else "未分类"),
        s.get("description", ""),
        s.get("country", ""),
        s.get("last_upload", ""),
        s.get("days_since_upload", -1),
        now,
    )


def export_subs_json(subs):
    """导出 JSON 快照，方便查看/备份（失败不影响主流程）."""
    try:
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        with open(os.path.join(OUTPUT_DIR, "subscriptions.json"), "w", encoding="utf-8") as f:
            json.dump(subs, f, ensure_ascii=False, indent=2, default=str)
    except Exception:
        pass


def save_subscriptions(subs):
    """整批覆盖写入订阅快照 (channel 表全量替换) ."""
    now = datetime.now(timezone.utc).isoformat()
    with _db_lock:
        conn = _get_conn()
        try:
            conn.execute("DELETE FROM subscriptions")
            conn.executemany(
                f"INSERT INTO subscriptions ({_SUB_COLUMNS}) VALUES ({_SUB_PLACEHOLDERS})",
                [_sub_row_values(s, now) for s in subs],
            )
            conn.execute(
                "INSERT INTO meta (key, value) VALUES ('last_updated', ?)"
                " ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (now,),
            )
            conn.commit()
        finally:
            conn.close()

    export_subs_json(subs)


def update_labels(channel_ids, label, action):
    """批量为频道添加/移除自定义标签，返回 (实际改动数, 错误信息).

    只改本地 SQLite，不触碰 YouTube API（标签是本应用自己的概念）。
    """
    label = (label or "").strip()[:MAX_LABEL_LEN]
    if not label:
        return 0, "标签名不能为空"
    if action not in ("add", "remove"):
        return 0, "action 必须是 add 或 remove"

    ids = [c for c in (channel_ids or []) if isinstance(c, str) and c]
    if not ids:
        return 0, "请先选择频道"

    changed = 0
    with _db_lock:
        conn = _get_conn()
        try:
            for cid in ids:
                row = conn.execute(
                    "SELECT custom_labels FROM subscriptions WHERE channel_id = ?",
                    (cid,),
                ).fetchone()
                if row is None:
                    continue
                try:
                    current = json.loads(row["custom_labels"] or "[]")
                except (ValueError, TypeError):
                    current = []
                current = _clean_labels(current)

                if action == "add":
                    if label in current:
                        continue
                    if len(current) >= MAX_LABELS_PER_CHANNEL:
                        continue
                    current.append(label)
                else:
                    if label not in current:
                        continue
                    current = [x for x in current if x != label]

                conn.execute(
                    "UPDATE subscriptions SET custom_labels = ? WHERE channel_id = ?",
                    (json.dumps(current, ensure_ascii=False), cid),
                )
                changed += 1
            conn.commit()
        finally:
            conn.close()

    if changed:
        # 标签变了，内存缓存必须失效；但不动 last_updated，
        # 所以下次请求只会重新读库，不会触发 YouTube API 调用
        with _ENRICHED_CACHE["lock"]:
            _ENRICHED_CACHE["data"] = None
            _ENRICHED_CACHE["at"] = None
        try:
            export_subs_json(load_subscriptions()[0])
        except Exception:
            pass

    return changed, None


def upsert_subscription(sub):
    """插入/更新单个订阅记录（用于「撤销退订」恢复数据）."""
    now = datetime.now(timezone.utc).isoformat()
    with _db_lock:
        conn = _get_conn()
        try:
            conn.execute(
                f"INSERT OR REPLACE INTO subscriptions ({_SUB_COLUMNS})"
                f" VALUES ({_SUB_PLACEHOLDERS})",
                _sub_row_values(sub, now),
            )
            conn.commit()
        finally:
            conn.close()
    remaining, _ = load_subscriptions()
    export_subs_json(remaining)
    with _ENRICHED_CACHE["lock"]:
        _ENRICHED_CACHE["data"] = None
        _ENRICHED_CACHE["at"] = None


def delete_subscription(subscription_id):
    """删除单个订阅记录，并同步导出 JSON + 清空内存缓存."""
    with _db_lock:
        conn = _get_conn()
        try:
            conn.execute(
                "DELETE FROM subscriptions WHERE subscription_id = ?",
                (subscription_id,),
            )
            conn.commit()
        finally:
            conn.close()
    remaining, _ = load_subscriptions()
    export_subs_json(remaining)
    with _ENRICHED_CACHE["lock"]:
        _ENRICHED_CACHE["data"] = None
        _ENRICHED_CACHE["at"] = None


def load_subscriptions():
    """从本地 DB 读取订阅快照，返回 (list_of_dicts, last_updated_iso_or_None) ."""
    with _db_lock:
        conn = _get_conn()
        try:
            rows = conn.execute(
                "SELECT * FROM subscriptions ORDER BY last_upload DESC, title"
            ).fetchall()
            last = conn.execute(
                "SELECT value FROM meta WHERE key='last_updated'"
            ).fetchone()
        finally:
            conn.close()

    subs = []
    for r in rows:
        d = dict(r)
        for key in ("topic_categories", "categories", "custom_labels"):
            try:
                d[key] = json.loads(d.get(key) or "[]")
            except (ValueError, TypeError):
                d[key] = []
        d["custom_labels"] = _clean_labels(d.get("custom_labels"))
        # 兼容老数据：没有 categories 就从 topic_categories 推导
        if not d["categories"]:
            d["categories"] = categories_of(d)
        if not d.get("primary_category"):
            d["primary_category"] = d["categories"][0]
        # 关键：days_since_upload 不能沿用入库时的快照值。
        # 它是「距离今天几天」，会随日历推移自然变化，必须按当前时间实时重算，
        # 否则会用旧值（例如昨天算的 0 天，今天还显示"今天"）。这不消耗任何 API 配额。
        d["days_since_upload"] = days_since_upload(d.get("last_upload"))
        subs.append(d)
    return subs, (last["value"] if last else None)


def last_updated_iso():
    with _db_lock:
        conn = _get_conn()
        try:
            row = conn.execute(
                "SELECT value FROM meta WHERE key='last_updated'"
            ).fetchone()
        finally:
            conn.close()
    return row["value"] if row else None


def needs_refresh():
    """判断本地快照是否过期（不存在或超过阈值 → 重新拉取 API）."""
    ts = last_updated_iso()
    if not ts:
        return True
    try:
        t = datetime.fromisoformat(ts)
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - t).total_seconds()
        return age > REFRESH_INTERVAL_SECONDS
    except ValueError:
        return True


_CREDS_LOCK = threading.Lock()


def load_credentials(allow_refresh=True):
    """读取本地 OAuth 凭证，过期则自动刷新.

    返回 (creds, error)。OAuth access token 只有约 1 小时有效期，
    因此必须先判断过期并刷新，再去校验有效性——顺序反了会导致
    token 一过期就直接返回 401，刷新逻辑永远不会执行。

    刷新用锁串行化，避免多线程/多请求同时刷新导致 refresh_token 失效。
    """
    if not os.path.exists(TOKEN_PATH):
        return None, "尚未授权，请先登录"

    try:
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)
    except Exception as e:
        return None, f"凭证文件无法读取，请重新登录: {e}"

    if creds is None:
        return None, "尚未授权，请先登录"

    if creds.valid:
        return creds, None

    if not allow_refresh or not creds.refresh_token:
        return None, "授权已失效，请重新登录"

    with _CREDS_LOCK:
        # 双重检查：等锁期间可能已被其他线程刷新
        try:
            creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)
        except Exception:
            pass
        if creds.valid:
            return creds, None
        if not creds.refresh_token:
            return None, "授权已失效，请重新登录"
        try:
            creds.refresh(Request())
        except Exception as e:
            return None, f"刷新授权失败，请重新登录: {e}"
        try:
            _save_token(creds)
        except Exception:
            pass
        return creds, None


def get_youtube_service():
    """获取已认证的 YouTube API 服务；token 过期会自动刷新."""
    creds, err = load_credentials()
    if err:
        return None, err
    return build("youtube", "v3", credentials=creds), None


def get_credentials():
    """读取当前 OAuth 凭证（供多线程构建独立 service 用），过期自动刷新."""
    creds, _ = load_credentials()
    return creds


def fetch_all_subscriptions(youtube):
    """拉取所有订阅频道（分页）."""
    subscriptions = []
    next_page_token = None
    while True:
        opts = {"part": "snippet", "mine": True, "maxResults": 50}
        if next_page_token:
            opts["pageToken"] = next_page_token
        resp = youtube.subscriptions().list(**opts).execute()
        for item in resp.get("items", []):
            snippet = item["snippet"]
            channel_id = snippet["resourceId"]["channelId"]
            subscriptions.append({
                "subscription_id": item["id"],
                "channel_id": channel_id,
                "title": snippet["title"],
                "thumbnail": snippet.get("thumbnails", {}).get("default", {}).get("url", ""),
                "published_at": snippet.get("publishedAt", ""),
            })
        next_page_token = resp.get("nextPageToken")
        if not next_page_token:
            break
    return subscriptions


def fetch_channel_details(youtube, channel_ids):
    """批量获取频道详情（统计信息+主题分类）."""
    details = {}
    # Batch by 50 IDs max per call
    batch_size = 50
    for i in range(0, len(channel_ids), batch_size):
        batch = channel_ids[i:i + batch_size]
        resp = youtube.channels().list(
            part="snippet,statistics,topicDetails",
            id=",".join(batch)
        ).execute()
        for ch in resp.get("items", []):
            cid = ch["id"]
            stats = ch.get("statistics", {})
            topic = ch.get("topicDetails", {})
            snippet = ch.get("snippet", {})
            details[cid] = {
                # customUrl 现在就是频道 @handle（如 "@mediastorm6801"），
                # 已包含在 snippet 里，不额外消耗配额
                "custom_url": snippet.get("customUrl", ""),
                "subscriber_count": int(stats.get("subscriberCount", 0)),
                "video_count": int(stats.get("videoCount", 0)),
                "topic_categories": topic.get("topicCategories", []),
                "description": snippet.get("description", "")[:200],
                "country": snippet.get("country", ""),
            }
    return details


def check_upload_activity(youtube, channel_id):
    """检查频道最近一次上传时间.

    使用 activities().list()（每个请求仅消耗 1 个配额单位），
    回退 search().list() 太贵（100 单位/请求），会迅速耗尽每日配额。
    """
    try:
        resp = youtube.activities().list(
            part="snippet,contentDetails",
            channelId=channel_id,
            maxResults=5,
        ).execute()
        for item in resp.get("items", []):
            if item.get("contentDetails", {}).get("upload", {}).get("videoId"):
                return item["snippet"]["publishedAt"]
    except Exception:
        pass
    return None


_ENRICHED_CACHE = {"data": None, "at": None, "lock": threading.Lock()}
_REFRESH_LOCK = threading.Lock()

# 并发请求共享同一次刷新的时间窗（秒）。
# 前端用 Promise.all 同时打 /api/subscriptions 和 /api/summary：
# 若两个请求都判定"缓存过期"，没有这个窗口就会各拉一次全量数据（配额翻倍）。
_REFRESH_COALESCE_SECONDS = 60


def _memory_cache_age():
    at = _ENRICHED_CACHE.get("at")
    if _ENRICHED_CACHE["data"] is None or at is None:
        return None
    return (datetime.now(timezone.utc) - at).total_seconds()


def get_enriched_subscriptions(yt, force=False, max_workers=10, reuse_recent=True):
    """获取完整订阅数据（详情 + 分类 + 最近上传），带内存缓存.

    前端在 /api/subscriptions 与 /api/summary 会各请求一次，
    这里缓存完整结果，避免重复调用高配额/高延迟的 API。

    reuse_recent=False 用于「用户手动点刷新」：必须真的重新拉取，
    不能被下面的并发合并窗口复用掉。
    """
    with _ENRICHED_CACHE["lock"]:
        if not force and _ENRICHED_CACHE["data"] is not None:
            return _ENRICHED_CACHE["data"]

    # 串行化刷新：同一时刻只允许一个线程真正去拉 API。
    # 等锁期间若已有别的请求刚刷新完，直接复用它的结果。
    with _REFRESH_LOCK:
        age = _memory_cache_age()
        if reuse_recent and age is not None and age < _REFRESH_COALESCE_SECONDS:
            return _ENRICHED_CACHE["data"]

        return _do_refresh(yt, max_workers)


def _do_refresh(yt, max_workers):
    """真正执行一次全量拉取并写入缓存/DB."""
    subs = fetch_all_subscriptions(yt)
    channel_ids = [s["channel_id"] for s in subs]
    details = fetch_channel_details(yt, channel_ids)

    # google-api-python-client 的 HTTP 资源非线程安全，
    # 为每个工作线程构建独立的 service 实例。
    creds = get_credentials()
    tls = threading.local()

    def thread_service():
        if getattr(tls, "svc", None) is None:
            tls.svc = build("youtube", "v3", credentials=creds, cache_discovery=False)
        return tls.svc

    # 并行检查每个频道的最近上传时间
    def enrich(sub, idx):
        cid = sub["channel_id"]
        sub.update(details.get(cid, {}))
        # 保留【全部】分类，一个频道可以同时属于多个分类
        cats = categories_of(sub)
        sub["categories"] = cats
        sub["primary_category"] = cats[0]
        sub["last_upload"] = check_upload_activity(thread_service(), cid)
        sub["days_since_upload"] = days_since_upload(sub["last_upload"])
        return idx, sub

    enriched = [None] * len(subs)
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(enrich, s, i): i for i, s in enumerate(subs)}
        for fut in as_completed(futures):
            idx, sub = fut.result()
            enriched[idx] = sub

    with _ENRICHED_CACHE["lock"]:
        _ENRICHED_CACHE["data"] = enriched
        _ENRICHED_CACHE["at"] = datetime.now(timezone.utc)

    # 持久化到本地 SQLite，之后无需每次都打 API
    try:
        save_subscriptions(enriched)
    except Exception:
        pass

    # 后台预热头像缓存（一次性），之后浏览器完全不再访问图片 CDN
    try:
        warm_thumbnails(enriched)
    except Exception:
        pass

    return enriched


def _asset_mtime(rel_path):
    """静态资源修改时间，用作缓存失效版本号."""
    try:
        return int(os.path.getmtime(os.path.join(BASE_DIR, rel_path)))
    except OSError:
        return 0


@app.context_processor
def _inject_asset_version():
    """给 CSS/JS 加上基于文件修改时间的版本号，避免重建后浏览器还用旧缓存.

    没有这个的话，更新代码后浏览器可能继续执行缓存的旧 app.js，
    表现为「明明改好了，界面还是老样子」。
    """
    return {"asset_v": _asset_mtime}


@app.route("/")
def index():
    # load_credentials 会自动刷新过期的 access token；
    # 只有真正无法恢复（无 refresh_token / 刷新失败）时才去重新授权。
    creds, err = load_credentials()
    if err or creds is None:
        return redirect(url_for("authorize"))
    resp = make_response(render_template("index.html"))
    # HTML 本身不允许缓存，保证每次都能拿到最新的资源版本号
    resp.headers["Cache-Control"] = "no-store, must-revalidate"
    return resp


@app.route("/favicon.ico")
def favicon():
    """避免浏览器请求 /favicon.ico 产生 404 噪音."""
    return "", 204


@app.route("/healthz")
def healthz():
    """健康检查端点（不需要授权），供 Docker HEALTHCHECK 使用.

    同时可作为「部署的是哪个版本」的自检入口：
    features 里列出的是当前代码已具备的能力。
    """
    return jsonify({
        "ok": True,
        "authorized": bool(load_credentials(allow_refresh=False)[0])
                      or os.path.exists(TOKEN_PATH),
        "last_updated": last_updated_iso(),
        # 静态资源版本号：重建后应变化，可用来确认浏览器是否拿到新文件
        "assets": {
            "app_js": _asset_mtime("static/js/app.js"),
            "style_css": _asset_mtime("static/css/style.css"),
        },
        "features": {
            "channel_links_to_videos": True,   # 点击频道跳 /@handle/videos
            "multi_category": True,            # 一个频道多个标签
            "thumbnail_cache": True,           # 本地缩略图代理
            "access_password": bool(ACCESS_PASSWORD),
            "auto_refresh_seconds": AUTO_REFRESH_SECONDS,
        },
    })


@app.before_request
def _require_access_password():
    """可选的访问保护：设了 ACCESS_PASSWORD 才生效，默认完全放行.

    Tailscale / 局域网内其他设备默认可以直接打开本应用并退订频道，
    设置 ACCESS_PASSWORD 后会启用浏览器原生 HTTP Basic 认证
    （无需改动前端，浏览器自己弹登录框）。
    """
    if not ACCESS_PASSWORD:
        return None
    if request.path == "/healthz":
        return None
    auth = request.authorization
    if auth and hmac.compare_digest(auth.username or "", ACCESS_USER) \
            and hmac.compare_digest(auth.password or "", ACCESS_PASSWORD):
        return None
    return Response(
        "需要登录",
        401,
        {"WWW-Authenticate": 'Basic realm="YouTube Subscription Manager", charset="UTF-8"'},
    )


# ────────────────────── 缩略图本地缓存代理 ──────────────────────
# 浏览器直接请求 yt3.ggpht.com 时，一次几百个并发会被 CDN 限流 (429)。
# 这里由后端下载一次并存到本地磁盘，之后所有请求都走本地，不再碰 CDN。

_THUMB_LOCKS = {}
_THUMB_LOCKS_GUARD = threading.Lock()
_THUMB_SEMAPHORE = threading.Semaphore(4)   # 限制并发下载，避免自己触发限流

PLACEHOLDER_SVG = (
    b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48" width="48" height="48">'
    b'<rect fill="#333" width="48" height="48"/>'
    b'<text x="24" y="30" text-anchor="middle" fill="#666" font-size="20">?</text></svg>'
)


def _thumb_lock(thumb_id):
    with _THUMB_LOCKS_GUARD:
        lk = _THUMB_LOCKS.get(thumb_id)
        if lk is None:
            lk = threading.Lock()
            _THUMB_LOCKS[thumb_id] = lk
        return lk


def _placeholder_response():
    """占位图（不缓存，方便下次重试下载）."""
    return Response(
        PLACEHOLDER_SVG,
        mimetype="image/svg+xml",
        headers={"Cache-Control": "no-store"},
    )


def get_thumbnail_url(channel_id):
    """从本地 DB 取出该频道的原始缩略图 URL."""
    with _db_lock:
        conn = _get_conn()
        try:
            row = conn.execute(
                "SELECT thumbnail FROM subscriptions WHERE channel_id = ?",
                (channel_id,),
            ).fetchone()
        finally:
            conn.close()
    return row["thumbnail"] if row else None


def safe_thumb_id(channel_id):
    """把 channel_id 清洗成安全的文件名片段."""
    return re.sub(r"[^A-Za-z0-9_-]", "", channel_id or "")[:128]


def _download_thumb(safe, url):
    """确保缩略图已缓存到本地，返回本地路径；失败返回 None.

    同一频道用独立锁去重，避免并发重复下载；
    全局信号量限制并发数，避免我们自己把 CDN 打到限流。
    """
    if not safe or not url:
        return None
    path = os.path.join(THUMB_DIR, safe + ".jpg")
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return path

    with _thumb_lock(safe):
        # 双重检查：可能在等锁期间已被其他线程下载完
        if os.path.exists(path) and os.path.getsize(path) > 0:
            return path
        try:
            os.makedirs(THUMB_DIR, exist_ok=True)
            with _THUMB_SEMAPHORE:
                req = urllib.request.Request(
                    url,
                    headers={"User-Agent": "Mozilla/5.0 (compatible; yt-sub-manager/1.0)"},
                )
                with urllib.request.urlopen(req, timeout=10) as resp:
                    data = resp.read()
            if not data:
                return None
            tmp = path + ".tmp"
            with open(tmp, "wb") as f:
                f.write(data)
            os.replace(tmp, path)   # 原子替换，避免读到半个文件
            return path
        except Exception:
            return None


def warm_thumbnails(subs):
    """后台预下载全部频道头像到本地缓存（daemon 线程，不阻塞请求）.

    预热一次之后，浏览器只从本机 Flask 取图，完全不再访问 yt3.ggpht.com。
    """
    def run():
        try:
            with ThreadPoolExecutor(max_workers=4) as pool:
                list(pool.map(
                    lambda s: _download_thumb(
                        safe_thumb_id(s.get("channel_id")),
                        s.get("thumbnail") or "",
                    ),
                    subs,
                ))
        except Exception:
            pass

    threading.Thread(target=run, daemon=True, name="thumb-warmer").start()


@app.route("/thumb/<channel_id>")
def thumb(channel_id):
    """本地缓存的频道头像：命中直接返回，未命中则下载一次后缓存.

    带 Cache-Control，浏览器切换标签页时可直接用自身缓存，不再产生网络请求。
    """
    safe = safe_thumb_id(channel_id)
    path = _download_thumb(safe, get_thumbnail_url(safe))
    if not path:
        # 下载失败（含 CDN 429）→ 占位图，不影响页面，也不缓存失败结果
        return _placeholder_response()
    return send_file(path, mimetype="image/jpeg", max_age=30 * 24 * 3600)


# ────────────────────── Google OAuth 授权（容器 / 无浏览器环境）──────────────────────
#
# 刻意不用 google_auth_oauthlib 的 flow.run_local_server()，它有两个致命问题：
#
#   1. 它会**阻塞**当前请求，并在等待回调期间一直占着回调端口。
#      本项目用 gunicorn 跑（1 worker / 8 线程），只要有一次授权没走到回调
#      （关掉标签页、没点链接、直接刷新页面……），那个端口就被永久占住，
#      之后任何 /authorize 都只会得到 "[Errno 98] Address already in use"。
#   2. 授权链接只打印到 stdout（也就是容器日志），浏览器里的用户根本看不到，
#      于是「打开页面 → 一直转圈 → 刷新 → 端口冲突」几乎必然发生。
#
# 现在的做法：/authorize 立刻返回一个带授权链接的页面；回调由后台一个
# **单次、带超时** 的 HTTP 服务接收，拿到 code 后换取 token 并原子写入
# config/token.json，然后关闭服务、释放端口。重复访问 /authorize 会复用
# 进行中的那条链接，不会再抢端口。

OAUTH_PORT = int(os.environ.get("OAUTH_PORT", "0") or "0")
# 本地运行默认只绑 loopback；容器里必须绑 0.0.0.0 才能被端口映射转发
# （docker-compose.yml 已显式设置 OAUTH_BIND_ADDR=0.0.0.0）。
OAUTH_BIND_ADDR = os.environ.get("OAUTH_BIND_ADDR") or "127.0.0.1"
# 等待回调的超时秒数；超时自动释放端口，避免「没走完的授权把端口焊死」。
OAUTH_TIMEOUT_SECONDS = int(os.environ.get("OAUTH_TIMEOUT_SECONDS", "600"))

_oauth_lock = threading.Lock()
_oauth = {
    "url": None,            # 进行中的授权链接（重复访问 /authorize 时复用）
    "redirect_uri": None,   # 对应的回调地址
    "thread": None,         # 后台回调服务线程
    "error": None,          # 最近一次失败原因
    "done": False,          # 最近一次流程是否已成功写入 token
}


def _oauth_redirect_uri(port):
    """回调地址：桌面客户端用 loopback 地址，Google 允许任意端口."""
    return os.environ.get("OAUTH_REDIRECT_URI") or f"http://localhost:{port}/"


_OAUTH_CALLBACK_PAGE = """<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<title>{title}</title><style>
body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
background:#15171b;color:#d6dade;display:grid;place-items:center;height:100vh;margin:0}}
.box{{text-align:center;padding:40px 48px;border:1px solid #2b2f36;border-radius:14px;background:#1b1e23}}
h1{{font-size:20px;margin:0 0 8px;color:#f0f2f5}}
p{{color:#9aa2ac;font-size:14px;margin:0}}
</style></head><body><div class="box"><h1>{title}</h1><p>{detail}</p></div></body></html>"""


class _OAuthCallbackHandler(http.server.BaseHTTPRequestHandler):
    """接收 Google 的 ?code=... 回调：记录结果、等后台换完 token 再回应."""

    def do_GET(self):  # noqa: N802 (stdlib 命名)
        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        result = {k: v[0] for k, v in query.items()}

        if "code" not in result and "error" not in result:
            # 不是 Google 回调（健康检查 / favicon / 端口探测）：
            # 不能消耗这一次等待，否则真正的授权回调会被顶掉。
            html = _OAUTH_CALLBACK_PAGE.format(
                title="⏳ 等待授权回调",
                detail="还没有收到 Google 的授权码，请从应用页面点击授权链接。")
        else:
            self.server.oauth_result = result
            self.server.oauth_event.set()       # 唤醒后台线程去换 token
            # 等后台线程把 code 换成 token，这样页面显示的是真实结果
            self.server.oauth_finished.wait(30)
            error = getattr(self.server, "oauth_error", None)
            if error:
                html = _OAUTH_CALLBACK_PAGE.format(title="❌ 授权失败", detail=error)
            else:
                html = _OAUTH_CALLBACK_PAGE.format(
                    title="✅ 授权成功", detail="凭证已保存，可以关闭此页面回到应用。")

        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass  # 静音 stdlib 访问日志


def _save_token(creds):
    """原子写入 token.json，避免其它线程读到半个文件."""
    os.makedirs(CONFIG_DIR, exist_ok=True)
    tmp = TOKEN_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(creds.to_json())
    os.replace(tmp, TOKEN_PATH)


def _oauth_worker(flow, httpd, state):
    """后台线程：等回调 → 换 token → 写 token.json → 释放端口."""
    error = None
    try:
        deadline = time.monotonic() + OAUTH_TIMEOUT_SECONDS
        while not httpd.oauth_event.is_set() and time.monotonic() < deadline:
            httpd.handle_request()   # 带 timeout，循环里反复检查截止时间
        result = httpd.oauth_result

        if result is None:
            error = f"等待授权超时（{OAUTH_TIMEOUT_SECONDS}s），请重新发起授权。"
        elif "error" in result:
            error = f"授权被拒绝: {result['error']}"
        elif "code" not in result:
            error = "没有收到授权码，请重试。"
        elif result.get("state") != state:
            error = "回调 state 不匹配，出于安全考虑已丢弃，请重新发起授权。"
        else:
            flow.fetch_token(code=result["code"])
            _save_token(flow.credentials)
            with _oauth_lock:
                _oauth["done"] = True
    except Exception as e:                      # 需要把原因回显到页面上
        error = f"{type(e).__name__}: {e}"
    finally:
        httpd.oauth_error = error
        try:
            httpd.server_close()                # 关键：无论成败都释放回调端口
        except Exception:
            pass
        httpd.oauth_finished.set()              # 通知回调页面「结果已确定」
        with _oauth_lock:
            _oauth["error"] = error
            _oauth["url"] = None
            _oauth["thread"] = None


@app.route("/authorize")
def authorize():
    """发起 OAuth 授权：立刻返回带授权链接的页面，回调由后台服务接收.

    本地运行：OAUTH_PORT 留空（0）→ 随机端口，可选自动打开浏览器。
    Docker 运行：设 OAUTH_PORT + OAUTH_BIND_ADDR=0.0.0.0 + OAUTH_OPEN_BROWSER=0，
    并把该端口映射到宿主机即可。
    """
    if not os.path.exists(CREDENTIALS_PATH):
        return render_template("error.html",
                               message="缺少 OAuth 凭证文件。<br>请到 Google Cloud Console 创建 OAuth 客户端 ID（类型选「桌面应用」），"
                                       "下载 client_secret_*.json 放到 config/client_secrets.json")

    with _oauth_lock:
        # 已经有一次授权在等回调：复用同一条链接，绝不再抢端口
        if _oauth["thread"] is not None and _oauth["thread"].is_alive() and _oauth["url"]:
            return render_template("authorize.html", auth_url=_oauth["url"],
                                   redirect_uri=_oauth["redirect_uri"])

        try:
            httpd = http.server.ThreadingHTTPServer(
                (OAUTH_BIND_ADDR, OAUTH_PORT), _OAuthCallbackHandler)
        except OSError as e:
            hint = ("这个端口已被其它程序占用。请修改 docker-compose.yml 里的 "
                    "OAUTH_PORT 与端口映射，然后重启容器。"
                    ) if e.errno == errno.EADDRINUSE else "请检查回调端口配置。"
            return render_template(
                "error.html",
                message=f"无法监听回调端口 {OAUTH_BIND_ADDR}:{OAUTH_PORT}：{e}<br>{hint}")

        httpd.timeout = 1
        httpd.oauth_event = threading.Event()      # 收到回调
        httpd.oauth_finished = threading.Event()   # 换 token 结束
        httpd.oauth_result = None
        httpd.oauth_error = None

        try:
            redirect_uri = _oauth_redirect_uri(httpd.server_port)
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_PATH, SCOPES)
            flow.redirect_uri = redirect_uri
            auth_url, state = flow.authorization_url(access_type="offline", prompt="consent")
        except Exception as e:
            httpd.server_close()
            return render_template("error.html", message=f"生成授权链接失败: {e}")

        thread = threading.Thread(target=_oauth_worker, args=(flow, httpd, state),
                                  name="oauth-callback", daemon=True)
        _oauth.update(url=auth_url, redirect_uri=redirect_uri, thread=thread,
                      error=None, done=False)
        thread.start()

    if os.environ.get("OAUTH_OPEN_BROWSER", "0") not in ("0", "false", "False"):
        try:
            import webbrowser
            webbrowser.open(auth_url)
        except Exception:
            pass

    return render_template("authorize.html", auth_url=auth_url, redirect_uri=redirect_uri)


@app.route("/authorize/status")
def authorize_status():
    """给授权页面轮询用：已完成 / 仍在等待 / 失败原因."""
    with _oauth_lock:
        thread = _oauth["thread"]
        return jsonify({
            "done": _oauth["done"],
            "pending": bool(thread is not None and thread.is_alive()),
            "error": _oauth["error"],
        })


@app.route("/api/subscriptions")
def api_subscriptions():
    """获取所有订阅列表 + 频道详情 + 最近上传时间.

    优先读本地 SQLite 快照；仅当本地无数据/过期/显式 ?refresh=1 时才调 API。
    """
    force = request.args.get("refresh") == "1"
    yt, err = get_youtube_service()
    if err:
        return jsonify({"error": err}), 401

    # 有本地缓存且未过期且未强制刷新 → 直接返回 DB
    if not force and not needs_refresh():
        subs, last = load_subscriptions()
        if subs:
            return jsonify({
                "count": len(subs),
                "subscriptions": subs,
                "last_updated": last,
                "from_cache": True,
            })

    # 否则调用 API 拉取全量数据（会自动落库）
    subs = get_enriched_subscriptions(yt, force=True)

    return jsonify({
        "count": len(subs),
        "subscriptions": subs,
        "last_updated": last_updated_iso(),
        "from_cache": False,
    })


@app.route("/api/summary")
def api_summary():
    """汇总统计."""
    force = request.args.get("refresh") == "1"
    yt, err = get_youtube_service()
    if err:
        return jsonify({"error": err}), 401

    # 与 subscriptions 一致：优先读本地快照
    if not force and not needs_refresh():
        subs, _ = load_subscriptions()
    else:
        subs = get_enriched_subscriptions(yt, force=True)

    inactive = [s for s in subs if s.get("days_since_upload", -1) > 90]
    active = [s for s in subs if 0 <= s.get("days_since_upload", -1) <= 90]

    # 一个频道有多个分类时，会出现在每一个它所属的分类下（分类之间会重复计数）
    categories = {}
    custom_labels = set()
    for sub in subs:
        cid = sub["channel_id"]
        sub_custom = labels_of(sub)
        custom_labels.update(sub_custom)
        # 「分类分组」同时涵盖 YouTube 自动分类和用户自定义标签
        tags = all_tags_of(sub)
        entry = {
            "title": sub["title"],
            "channel_id": cid,
            "thumbnail": sub.get("thumbnail", ""),
            "days_since_upload": sub.get("days_since_upload", -1),
            "categories": tags,
            "custom_labels": sub_custom,
        }
        for cat in tags:
            categories.setdefault(cat, []).append(entry)

    return jsonify({
        "total": len(subs),
        "active_90d": len(active),
        "inactive_90d": len(inactive),
        "categories": categories,
        # 前端用这个列表区分「自动分类」和「我的标签」
        "custom_labels": sorted(custom_labels),
        "multi_category": True,
        "last_updated": last_updated_iso(),
    })


@app.route("/api/refresh", methods=["POST"])
def api_refresh():
    """手动强制刷新：忽略本地缓存，重新从 YouTube API 拉取并落库."""
    yt, err = get_youtube_service()
    if err:
        return jsonify({"error": err}), 401
    try:
        # reuse_recent=False：用户手动点了刷新，就必须真的再拉一次
        subs = get_enriched_subscriptions(yt, force=True, reuse_recent=False)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    return jsonify({
        "ok": True,
        "count": len(subs),
        "last_updated": last_updated_iso(),
    })


@app.route("/api/unsubscribe/<subscription_id>", methods=["POST"])
def api_unsubscribe(subscription_id):
    """退订一个频道（前端采用乐观更新 + 撤销，因此这里不做二次确认）."""
    yt, err = get_youtube_service()
    if err:
        return jsonify({"error": err}), 401
    try:
        yt.subscriptions().delete(id=subscription_id).execute()
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

    try:
        delete_subscription(subscription_id)
    except Exception:
        pass

    return jsonify({"ok": True, "message": "已退订"})


@app.route("/api/labels", methods=["POST"])
def api_labels():
    """批量给选中的频道添加/移除自定义标签.

    请求体:
        {"channel_ids": ["UC...", ...], "label": "我的收藏", "action": "add"|"remove"}

    只写本地数据库，不调用 YouTube API。
    """
    payload = request.get_json(silent=True) or {}
    label = payload.get("label") or ""
    action = payload.get("action") or "add"
    channel_ids = payload.get("channel_ids") or []

    changed, error = update_labels(channel_ids, label, action)
    if error:
        return jsonify({"ok": False, "error": error}), 400

    return jsonify({
        "ok": True,
        "action": action,
        "label": label.strip()[:MAX_LABEL_LEN],
        "changed": changed,
    })


@app.route("/api/resubscribe", methods=["POST"])
def api_resubscribe():
    """撤销退订：重新订阅该频道并恢复本地记录.

    前端把被退订频道的完整信息回传，这样无需重新拉取整份数据。
    """
    payload = request.get_json(silent=True) or {}
    channel_id = payload.get("channel_id")
    if not channel_id:
        return jsonify({"ok": False, "error": "缺少 channel_id"}), 400

    yt, err = get_youtube_service()
    if err:
        return jsonify({"error": err}), 401

    # 重新订阅（若已订阅，API 会返回 409，视为成功）
    try:
        yt.subscriptions().insert(
            part="snippet",
            body={
                "snippet": {
                    "resourceId": {
                        "kind": "youtube#channel",
                        "channelId": channel_id,
                    }
                }
            },
        ).execute()
    except HttpError as e:
        if getattr(e, "resp", None) is not None and e.resp.status in (409, 400):
            pass  # 已经订阅了，继续恢复本地记录
        else:
            return jsonify({"ok": False, "error": str(e)}), 500
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

    # 恢复本地 DB 记录
    try:
        cats = payload.get("categories") or []
        sub = {
            "channel_id": channel_id,
            "subscription_id": payload.get("subscription_id", ""),
            "title": payload.get("title", ""),
            "thumbnail": payload.get("thumbnail", ""),
            "custom_url": payload.get("custom_url", ""),
            "subscriber_count": payload.get("subscriber_count", 0),
            "video_count": payload.get("video_count", 0),
            "topic_categories": payload.get("topic_categories", []),
            "categories": cats,
            "primary_category": payload.get("primary_category") or (cats[0] if cats else "未分类"),
            "description": payload.get("description", ""),
            "country": payload.get("country", ""),
            "last_upload": payload.get("last_upload", ""),
            "days_since_upload": payload.get("days_since_upload", -1),
        }
        upsert_subscription(sub)
    except Exception:
        pass

    return jsonify({"ok": True, "message": "已恢复订阅"})


# 启动时确保目录与数据库表就绪（Docker 挂载 volume 时目录可能为空）
for _d in (CONFIG_DIR, OUTPUT_DIR, THUMB_DIR, os.path.dirname(DB_PATH)):
    try:
        os.makedirs(_d, exist_ok=True)
    except Exception:
        pass

init_db()


def _startup_warm():
    """启动时若本地已有数据，后台补齐缺失的头像缓存（已缓存则几乎零开销）."""
    try:
        subs, _ = load_subscriptions()
        if subs:
            warm_thumbnails(subs)
    except Exception:
        pass


_startup_warm()


def _start_auto_refresh():
    """可选的后台定时刷新（需设置 AUTO_REFRESH_SECONDS > 0）.

    默认关闭：应用采用「按需刷新」——页面请求时若本地快照超过
    REFRESH_INTERVAL_SECONDS 才去调 API；不打开页面就完全不消耗配额。
    """
    if AUTO_REFRESH_SECONDS <= 0:
        return

    def loop():
        while True:
            time.sleep(AUTO_REFRESH_SECONDS)
            try:
                yt, err = get_youtube_service()
                if not err and yt is not None:
                    get_enriched_subscriptions(yt, force=True, reuse_recent=False)
            except Exception:
                pass

    threading.Thread(target=loop, daemon=True, name="auto-refresh").start()


_start_auto_refresh()


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8765")),
        debug=os.environ.get("FLASK_DEBUG", "0") in ("1", "true", "True"),
    )
