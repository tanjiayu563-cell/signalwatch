import hashlib
import html
import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Dict, List, Optional
from urllib.parse import quote
from urllib.request import HTTPCookieProcessor, Request, build_opener

from .config import HTTP_TIMEOUT_SECONDS, MAX_ITEMS_PER_SOURCE, USER_AGENT


@dataclass
class SourceResult:
    source: str
    items: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


class SourceError(RuntimeError):
    pass


SOURCE_CATALOG = [
    {
        "id": "weibo_hot",
        "name": "微博热搜",
        "kind": "公开热榜",
        "auth_required": False,
        "status_label": "公开可用",
        "coverage": "公开热搜榜；不是微博站内全量帖子检索",
    },
    {
        "id": "douyin_hot",
        "name": "抖音热榜",
        "kind": "公开热榜",
        "auth_required": False,
        "status_label": "公开可用",
        "coverage": "公开热榜接口；不包含站内评论与全量视频搜索",
    },
    {
        "id": "toutiao_hot",
        "name": "今日头条热榜",
        "kind": "公开热榜",
        "auth_required": False,
        "status_label": "公开可用",
        "coverage": "公开热榜",
    },
    {
        "id": "bilibili_hot",
        "name": "B站热门",
        "kind": "公开榜单",
        "auth_required": False,
        "status_label": "公开可用",
        "coverage": "综合热门视频榜",
    },
    {
        "id": "chinanews",
        "name": "中新网即时新闻",
        "kind": "权威新闻",
        "auth_required": False,
        "status_label": "公开可用",
        "coverage": "中新网即时新闻 RSS",
    },
]

AUTH_REQUIRED_SOURCES = [
    {
        "id": "weibo_search",
        "name": "微博关键词搜索",
        "kind": "全文检索",
        "auth_required": True,
        "auth_types": ["session_cookie"],
        "coverage": "需要用户登录态或授权数据接口；尚未验证当前账号可用性",
        "status_label": "需授权",
    },
    {
        "id": "douyin_search",
        "name": "抖音关键词搜索",
        "kind": "全文检索",
        "auth_required": True,
        "auth_types": ["api_token", "api_key"],
        "coverage": "站内搜索存在签名与风控，建议接入官方或授权数据供应商",
        "status_label": "需授权供应商",
    },
    {
        "id": "wechat_articles",
        "name": "微信公众号",
        "kind": "图文内容",
        "auth_required": True,
        "auth_types": ["api_token", "api_key"],
        "coverage": "需公众号授权、合规采集服务或授权数据供应商",
        "status_label": "需授权",
    },
    {
        "id": "xiaohongshu",
        "name": "小红书",
        "kind": "社交内容",
        "auth_required": True,
        "auth_types": ["api_token", "api_key"],
        "coverage": "需官方或授权数据接口",
        "status_label": "需授权供应商",
    },
    {
        "id": "kuaishou",
        "name": "快手",
        "kind": "社交内容",
        "auth_required": True,
        "auth_types": ["api_token", "api_key"],
        "coverage": "需官方或授权数据接口",
        "status_label": "需授权供应商",
    },
]

PUBLIC_SOURCE_IDS = [source["id"] for source in SOURCE_CATALOG]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def clean_text(value: Any, limit: int = 1200) -> str:
    if value is None:
        return ""
    text = html.unescape(str(value))
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def stable_id(source: str, value: Any) -> str:
    digest = hashlib.sha1(f"{source}:{value}".encode("utf-8")).hexdigest()[:20]
    return f"{source}:{digest}"


def request_bytes(
    url: str,
    headers: Optional[Dict[str, str]] = None,
    opener: Any = None,
) -> bytes:
    request_headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json,text/plain,text/html,application/xml,text/xml,*/*",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }
    request_headers.update(headers or {})
    request = Request(url, headers=request_headers)
    active_opener = opener or build_opener()
    try:
        with active_opener.open(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            return response.read()
    except Exception as exc:
        raise SourceError(f"{type(exc).__name__}: {exc}") from exc


def request_json(
    url: str,
    headers: Optional[Dict[str, str]] = None,
    opener: Any = None,
) -> Dict[str, Any]:
    raw = request_bytes(url, headers=headers, opener=opener)
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SourceError("接口未返回有效 JSON，可能触发了平台风控") from exc
    if not isinstance(data, dict):
        raise SourceError("接口返回结构不是 JSON 对象")
    return data


def parse_weibo(payload: Dict[str, Any], fetched_at: str) -> List[Dict[str, Any]]:
    realtime = payload.get("data", {}).get("realtime", [])
    if not isinstance(realtime, list):
        raise SourceError("微博热搜返回结构异常")
    items: List[Dict[str, Any]] = []
    for index, raw in enumerate(realtime[:MAX_ITEMS_PER_SOURCE], start=1):
        title = clean_text(raw.get("word") or raw.get("note"), 200)
        if not title:
            continue
        rank = int(raw.get("realpos") or index)
        hot_value = raw.get("num")
        try:
            hot_value = int(hot_value) if hot_value is not None else None
        except (TypeError, ValueError):
            hot_value = None
        items.append(
            {
                "id": stable_id("weibo_hot", title),
                "source": "weibo_hot",
                "external_id": title,
                "title": title,
                "url": "https://s.weibo.com/weibo?q=" + quote(title),
                "summary": f"微博热搜第 {rank} 位"
                + (f"，热度 {hot_value}" if hot_value else ""),
                "author": "微博热搜",
                "published_at": None,
                "fetched_at": fetched_at,
                "rank": rank,
                "hot_value": hot_value,
                "raw": raw,
            }
        )
    return items


def fetch_weibo_hot() -> SourceResult:
    fetched_at = utc_now()
    opener = build_opener(HTTPCookieProcessor())
    request_bytes("https://weibo.com/", headers={"Accept": "text/html"}, opener=opener)
    payload = request_json(
        "https://weibo.com/ajax/side/hotSearch",
        headers={
            "Referer": "https://weibo.com/",
            "X-Requested-With": "XMLHttpRequest",
        },
        opener=opener,
    )
    return SourceResult("weibo_hot", parse_weibo(payload, fetched_at))


def parse_douyin(payload: Dict[str, Any], fetched_at: str) -> List[Dict[str, Any]]:
    words = payload.get("word_list", [])
    if not isinstance(words, list):
        raise SourceError("抖音热榜返回结构异常")
    items: List[Dict[str, Any]] = []
    for index, raw in enumerate(words[:MAX_ITEMS_PER_SOURCE], start=1):
        title = clean_text(raw.get("word"), 200)
        if not title:
            continue
        hot_value = raw.get("hot_value")
        try:
            hot_value = int(hot_value) if hot_value is not None else None
        except (TypeError, ValueError):
            hot_value = None
        items.append(
            {
                "id": stable_id("douyin_hot", title),
                "source": "douyin_hot",
                "external_id": title,
                "title": title,
                "url": "https://www.douyin.com/search/" + quote(title),
                "summary": f"抖音热榜第 {index} 位"
                + (f"，热度 {hot_value}" if hot_value else ""),
                "author": "抖音热榜",
                "published_at": None,
                "fetched_at": fetched_at,
                "rank": index,
                "hot_value": hot_value,
                "raw": raw,
            }
        )
    return items


def fetch_douyin_hot() -> SourceResult:
    fetched_at = utc_now()
    payload = request_json(
        "https://www.iesdouyin.com/web/api/v2/hotsearch/billboard/word/",
        headers={"Referer": "https://www.douyin.com/"},
    )
    return SourceResult("douyin_hot", parse_douyin(payload, fetched_at))


def parse_toutiao(payload: Dict[str, Any], fetched_at: str) -> List[Dict[str, Any]]:
    rows = payload.get("data", [])
    if not isinstance(rows, list):
        raise SourceError("今日头条热榜返回结构异常")
    items: List[Dict[str, Any]] = []
    for index, raw in enumerate(rows[:MAX_ITEMS_PER_SOURCE], start=1):
        title = clean_text(raw.get("Title"), 200)
        if not title:
            continue
        hot_value = raw.get("HotValue")
        try:
            hot_value = int(hot_value) if hot_value is not None else None
        except (TypeError, ValueError):
            hot_value = None
        cluster_id = str(raw.get("ClusterId") or title)
        items.append(
            {
                "id": stable_id("toutiao_hot", cluster_id),
                "source": "toutiao_hot",
                "external_id": cluster_id,
                "title": title,
                "url": raw.get("Url") or "https://www.toutiao.com/",
                "summary": f"今日头条热榜第 {index} 位"
                + (f"，热度 {hot_value}" if hot_value else ""),
                "author": "今日头条热榜",
                "published_at": None,
                "fetched_at": fetched_at,
                "rank": index,
                "hot_value": hot_value,
                "raw": raw,
            }
        )
    return items


def fetch_toutiao_hot() -> SourceResult:
    fetched_at = utc_now()
    payload = request_json(
        "https://www.toutiao.com/hot-event/hot-board/?origin=toutiao_pc",
        headers={"Referer": "https://www.toutiao.com/"},
    )
    return SourceResult("toutiao_hot", parse_toutiao(payload, fetched_at))


def parse_bilibili(payload: Dict[str, Any], fetched_at: str) -> List[Dict[str, Any]]:
    rows = payload.get("data", {}).get("list", [])
    if not isinstance(rows, list):
        raise SourceError("B站热门返回结构异常")
    items: List[Dict[str, Any]] = []
    for index, raw in enumerate(rows[:MAX_ITEMS_PER_SOURCE], start=1):
        title = clean_text(raw.get("title"), 200)
        bvid = raw.get("bvid") or str(raw.get("aid") or title)
        if not title:
            continue
        published_at = None
        pubdate = raw.get("pubdate")
        if pubdate:
            try:
                published_at = datetime.fromtimestamp(
                    int(pubdate), tz=timezone.utc
                ).isoformat(timespec="seconds")
            except (TypeError, ValueError, OSError):
                published_at = None
        stat = raw.get("stat") if isinstance(raw.get("stat"), dict) else {}
        view_count = stat.get("view")
        try:
            view_count = int(view_count) if view_count is not None else None
        except (TypeError, ValueError):
            view_count = None
        owner = raw.get("owner") if isinstance(raw.get("owner"), dict) else {}
        items.append(
            {
                "id": stable_id("bilibili_hot", bvid),
                "source": "bilibili_hot",
                "external_id": str(bvid),
                "title": title,
                "url": f"https://www.bilibili.com/video/{bvid}",
                "summary": clean_text(raw.get("desc") or f"B站热门第 {index} 位", 500),
                "author": clean_text(owner.get("name") or "B站热门", 100),
                "published_at": published_at,
                "fetched_at": fetched_at,
                "rank": index,
                "hot_value": view_count,
                "raw": raw,
            }
        )
    return items


def fetch_bilibili_hot() -> SourceResult:
    fetched_at = utc_now()
    payload = request_json(
        "https://api.bilibili.com/x/web-interface/ranking/v2?rid=0&type=all",
        headers={"Referer": "https://www.bilibili.com/"},
    )
    return SourceResult("bilibili_hot", parse_bilibili(payload, fetched_at))


def parse_chinanews(raw_xml: bytes, fetched_at: str) -> List[Dict[str, Any]]:
    try:
        root = ET.fromstring(raw_xml)
    except ET.ParseError as exc:
        raise SourceError("中新网 RSS 解析失败") from exc
    items: List[Dict[str, Any]] = []
    for raw in root.findall("./channel/item")[:MAX_ITEMS_PER_SOURCE]:
        title = clean_text(raw.findtext("title"), 200)
        link = clean_text(raw.findtext("link"), 500)
        if not title or not link:
            continue
        published_at = None
        date_text = raw.findtext("pubDate")
        if date_text:
            try:
                published_at = parsedate_to_datetime(date_text).isoformat(timespec="seconds")
            except (TypeError, ValueError, OverflowError):
                published_at = None
        items.append(
            {
                "id": stable_id("chinanews", link),
                "source": "chinanews",
                "external_id": link,
                "title": title,
                "url": link,
                "summary": clean_text(raw.findtext("description"), 700),
                "author": "中国新闻网",
                "published_at": published_at,
                "fetched_at": fetched_at,
                "rank": None,
                "hot_value": None,
                "raw": {
                    "title": title,
                    "link": link,
                    "pubDate": date_text or "",
                },
            }
        )
    return items


def fetch_chinanews() -> SourceResult:
    fetched_at = utc_now()
    raw = request_bytes(
        "https://www.chinanews.com.cn/rss/scroll-news.xml",
        headers={"Accept": "application/xml,text/xml"},
    )
    return SourceResult("chinanews", parse_chinanews(raw, fetched_at))


FETCHERS = {
    "weibo_hot": fetch_weibo_hot,
    "douyin_hot": fetch_douyin_hot,
    "toutiao_hot": fetch_toutiao_hot,
    "bilibili_hot": fetch_bilibili_hot,
    "chinanews": fetch_chinanews,
}


def fetch_source(source_id: str) -> SourceResult:
    fetcher = FETCHERS.get(source_id)
    if not fetcher:
        raise SourceError(f"来源 {source_id} 尚未实现或需要授权")
    return fetcher()


def _authorization_headers(auth_type: str, secret: str) -> Dict[str, str]:
    if auth_type == "session_cookie":
        return {"Cookie": secret}
    if auth_type == "api_key":
        return {"X-API-Key": secret}
    if auth_type == "api_token":
        return {"Authorization": f"Bearer {secret}"}
    raise SourceError("不支持的授权类型")


def _authorized_endpoint_url(endpoint: str, keyword: str) -> str:
    separator = "&" if "?" in endpoint else "?"
    return (
        endpoint
        + separator
        + "keyword="
        + quote(keyword)
        + "&limit="
        + str(min(50, MAX_ITEMS_PER_SOURCE))
    )


def parse_authorized_items(
    payload: Dict[str, Any], source_id: str, fetched_at: str
) -> List[Dict[str, Any]]:
    rows: Any = payload.get("items")
    if rows is None:
        rows = payload.get("data")
    if isinstance(rows, dict):
        rows = rows.get("items") or rows.get("list")
    if rows is None:
        rows = payload.get("list")
    if not isinstance(rows, list):
        raise SourceError(
            "授权接口返回格式不符合约定，需返回 items 数组或 data.items 数组"
        )

    items: List[Dict[str, Any]] = []
    for index, raw in enumerate(rows[:MAX_ITEMS_PER_SOURCE], start=1):
        if not isinstance(raw, dict):
            continue
        title = clean_text(raw.get("title") or raw.get("name"), 240)
        url = clean_text(raw.get("url") or raw.get("link"), 1000)
        if not title or not url:
            continue
        external_id = str(
            raw.get("id")
            or raw.get("external_id")
            or raw.get("url")
            or f"{title}:{index}"
        )
        hot_value = raw.get("hot_value") or raw.get("view_count")
        try:
            hot_value = int(hot_value) if hot_value is not None else None
        except (TypeError, ValueError):
            hot_value = None
        rank = raw.get("rank") or index
        try:
            rank = int(rank) if rank is not None else None
        except (TypeError, ValueError):
            rank = None
        items.append(
            {
                "id": stable_id(source_id, external_id),
                "source": source_id,
                "external_id": external_id,
                "title": title,
                "url": url,
                "summary": clean_text(
                    raw.get("summary") or raw.get("description") or raw.get("content"),
                    1200,
                ),
                "author": clean_text(
                    raw.get("author") or raw.get("account") or raw.get("source"),
                    120,
                ),
                "published_at": raw.get("published_at") or raw.get("publish_time"),
                "fetched_at": fetched_at,
                "rank": rank,
                "hot_value": hot_value,
                "raw": raw,
            }
        )
    return items


def fetch_authorized_source(
    source_id: str,
    credential: Dict[str, Any],
    watch_terms: List[str],
) -> SourceResult:
    endpoint = str(credential.get("endpoint") or "").strip()
    auth_type = str(credential.get("auth_type") or "")
    secret = str(credential.get("secret") or "")
    if not endpoint:
        raise SourceError("已保存授权，但尚未配置可调用的数据接口地址")
    if not watch_terms:
        return SourceResult(
            source_id,
            [],
            warnings=["没有监测关键词，已跳过授权全文检索"],
        )

    headers = _authorization_headers(auth_type, secret)
    items_by_id: Dict[str, Dict[str, Any]] = {}
    warnings: List[str] = []
    for term in watch_terms[:10]:
        payload = request_json(
            _authorized_endpoint_url(endpoint, term),
            headers={**headers, "Accept": "application/json"},
        )
        for item in parse_authorized_items(payload, source_id, utc_now()):
            items_by_id[item["id"]] = item
    if len(watch_terms) > 10:
        warnings.append("单次扫描仅向前 10 个监测词请求授权全文接口")
    return SourceResult(source_id, list(items_by_id.values()), warnings)
