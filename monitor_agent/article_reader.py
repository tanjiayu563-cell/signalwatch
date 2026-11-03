import html
import ipaddress
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional

from .config import HTTP_TIMEOUT_SECONDS, USER_AGENT


MAX_RESPONSE_BYTES = 1_500_000
MAX_TEXT_CHARS = 12_000


class ArticleReadError(RuntimeError):
    pass


def _clean_title(value: str) -> str:
    title = re.sub(r"\s+", " ", value or "").strip()
    if "_" in title:
        title = title.split("_", 1)[0].strip()
    title = re.sub(
        r"\s*[-|｜]\s*(中新网|新华网|人民网|央视网|中国新闻网|BlueFocus)\s*$",
        "",
        title,
        flags=re.IGNORECASE,
    ).strip()
    return title[:240]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _validate_public_url(url: str) -> urllib.parse.ParseResult:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ArticleReadError("只允许读取 http/https 公开文章")
    hostname = parsed.hostname.casefold()
    if hostname in {"localhost", "localhost.localdomain"}:
        raise ArticleReadError("禁止访问本机地址")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        addresses = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ArticleReadError(f"无法解析文章域名：{hostname}") from exc
    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_unspecified
            or ip.is_multicast
        ):
            raise ArticleReadError("禁止访问内网、本机或保留地址")
    return parsed


class ArticleHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.page_title = ""
        self.site_name = ""
        self.description = ""
        self.canonical = ""
        self.published_at = ""
        self.paragraphs: List[str] = []
        self._skip_depth = 0
        self._capture_title = False
        self._current_tag = ""
        self._current_text: List[str] = []

    def handle_starttag(self, tag: str, attrs: List[tuple]) -> None:
        tag = tag.lower()
        attributes = {key.lower(): value or "" for key, value in attrs}
        if tag in {"script", "style", "noscript", "svg", "nav", "header", "footer", "aside"}:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if tag == "title":
            self._capture_title = True
        if tag == "meta":
            property_name = (
                attributes.get("property")
                or attributes.get("name")
                or attributes.get("itemprop")
                or ""
            ).lower()
            content = attributes.get("content", "").strip()
            if property_name in {"og:site_name", "application-name"} and content:
                self.site_name = content[:120]
            elif property_name in {"description", "og:description"} and content and not self.description:
                self.description = content[:500]
            elif property_name in {
                "article:published_time",
                "datepublished",
                "publishdate",
            } and content:
                self.published_at = content[:80]
        if tag == "link" and attributes.get("rel", "").lower() == "canonical":
            self.canonical = attributes.get("href", "").strip()[:1000]
        if tag in {"p", "h1", "h2", "h3", "blockquote"}:
            self._current_tag = tag
            self._current_text = []

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if self._skip_depth:
            if tag in {"script", "style", "noscript", "svg", "nav", "header", "footer", "aside"}:
                self._skip_depth = max(0, self._skip_depth - 1)
            return
        if tag == "title":
            self._capture_title = False
        if tag == self._current_tag:
            text = re.sub(r"\s+", " ", "".join(self._current_text)).strip()
            if text and (len(text) >= 18 or tag in {"h1", "h2", "h3"}):
                self.paragraphs.append(html.unescape(text)[:1200])
            self._current_tag = ""
            self._current_text = []

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if self._capture_title:
            self.page_title += data
        if self._current_tag:
            self._current_text.append(data)


def _decode_response(raw: bytes, content_type: str) -> str:
    charset_match = re.search(r"charset=([\w-]+)", content_type, re.IGNORECASE)
    candidates = []
    if charset_match:
        candidates.append(charset_match.group(1))
    candidates.extend(["utf-8", "gb18030"])
    for encoding in dict.fromkeys(candidates):
        try:
            return raw.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")


def read_article(url: str) -> Dict[str, Any]:
    _validate_public_url(url)
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.5",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.5",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            final_url = response.geturl()
            _validate_public_url(final_url)
            content_type = response.headers.get("Content-Type", "")
            if content_type and not any(
                value in content_type.lower()
                for value in ("text/html", "application/xhtml", "text/plain")
            ):
                raise ArticleReadError(f"不支持的页面类型：{content_type}")
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                raise ArticleReadError("文章页面过大，已停止读取")
    except ArticleReadError:
        raise
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ArticleReadError(f"{type(exc).__name__}: {exc}") from exc

    document = _decode_response(raw, content_type)
    parser = ArticleHTMLParser()
    try:
        parser.feed(document)
    except Exception as exc:
        raise ArticleReadError(f"网页正文解析失败：{exc}") from exc

    paragraphs: List[str] = []
    seen = set()
    total = 0
    for paragraph in parser.paragraphs:
        normalized = re.sub(r"\{[^{}]{0,300}yecms[^{}]*\}", "", paragraph, flags=re.IGNORECASE)
        normalized = re.sub(r"\s+", " ", normalized).strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        if total + len(normalized) > MAX_TEXT_CHARS:
            remaining = MAX_TEXT_CHARS - total
            if remaining > 40:
                paragraphs.append(normalized[:remaining])
            break
        paragraphs.append(normalized)
        total += len(normalized)

    text = "\n\n".join(paragraphs).strip()
    if len(text) < 60:
        raise ArticleReadError("未提取到足够的文章正文，原网页可能需要登录或依赖 JavaScript 渲染")

    title = _clean_title(parser.page_title)
    return {
        "url": url,
        "final_url": final_url,
        "site_name": parser.site_name or urllib.parse.urlparse(final_url).hostname or "",
        "title": title,
        "description": re.sub(
            r"\{[^{}]{0,300}yecms[^{}]*\}",
            "",
            parser.description,
            flags=re.IGNORECASE,
        ).strip(),
        "published_at": parser.published_at,
        "canonical_url": parser.canonical or final_url,
        "text": text,
        "char_count": len(text),
        "fetched_at": _utc_now(),
    }
