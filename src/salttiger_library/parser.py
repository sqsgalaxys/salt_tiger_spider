from __future__ import annotations

import calendar
import re
from datetime import date
from pathlib import PurePosixPath
from urllib.parse import parse_qs, urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from .models import ArchiveEntry, Book, DownloadLink


_DATE_RE = re.compile(r"(?:出版|发布)时间\s*[：:]?\s*(\d{4})[年./-](\d{1,2})[月./-](\d{1,2})")
_YEAR_RE = re.compile(r"\b(20\d{2})\b")
_DAY_RE = re.compile(r"^\s*(\d{1,2})\s*[日:]?")
_CODE_RE = re.compile(r"(?:提取码|密码|pwd)\s*[：:=]?\s*([A-Za-z0-9]{4,8})", re.I)
_PUBLISHER_RE = re.compile(r"(?:出版社|Publisher)\s*[：:]\s*([^\n|]+)", re.I)
_DOWNLOAD_SUFFIXES = {".pdf", ".epub", ".mobi", ".azw3", ".zip", ".rar", ".7z"}


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    value = " ".join(value.split()).strip()
    return value or None


def _slug_from_url(url: str) -> str:
    path = PurePosixPath(urlparse(url).path.rstrip("/"))
    return path.name or "book"


def _month_number(text: str) -> int | None:
    match = re.search(r"(?:^|\s)(1[0-2]|0?[1-9])\s*月", text)
    if match:
        return int(match.group(1))
    lowered = text.lower()
    for number, name in enumerate(calendar.month_name[1:], 1):
        if name.lower() in lowered or calendar.month_abbr[number].lower() in lowered:
            return number
    return None


def parse_archive(html: str, base_url: str = "https://salttiger.com/") -> list[ArchiveEntry]:
    soup = BeautifulSoup(html, "html.parser")
    entries: list[ArchiveEntry] = []
    seen: set[str] = set()
    for item in soup.select(".car-monthlisting > li"):
        link = item.find("a", href=True)
        if not isinstance(link, Tag):
            continue
        detail_url = urljoin(base_url, str(link["href"]))
        if detail_url in seen:
            continue
        title = _clean(link.get_text(" ", strip=True))
        if not title:
            continue
        month_list = item.find_parent(class_="car-monthlisting")
        month_item = month_list.find_parent("li") if month_list else None
        month_heading = month_item.select_one(".car-yearmonth") if month_item else None
        heading_text = month_heading.get_text(" ", strip=True) if month_heading else ""
        year_match = _YEAR_RE.search(heading_text)
        month = _month_number(heading_text)
        day_match = _DAY_RE.search(item.get_text(" ", strip=True))
        published_at = None
        if year_match and month and day_match:
            try:
                published_at = date(int(year_match.group(1)), month, int(day_match.group(1))).isoformat()
            except ValueError:
                pass
        entries.append(ArchiveEntry(title=title, detail_url=detail_url, published_at=published_at))
        seen.add(detail_url)
    return entries


def classify_download(url: str) -> str | None:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if host == "pan.baidu.com" or host.endswith(".pan.baidu.com"):
        return "baidu_pan"
    if parsed.scheme in {"http", "https"} and PurePosixPath(parsed.path.lower()).suffix in _DOWNLOAD_SUFFIXES:
        return "direct"
    if parsed.scheme in {"ed2k", "magnet"}:
        return parsed.scheme
    return None


def parse_detail(
    html: str,
    origin_url: str,
    *,
    fallback_title: str | None = None,
    fallback_date: str | None = None,
) -> Book:
    soup = BeautifulSoup(html, "html.parser")
    content = soup.select_one(".entry-content")
    if content is None:
        raise ValueError("detail page does not contain .entry-content")
    title_node = soup.select_one("h1.entry-title")
    title = _clean(title_node.get_text(" ", strip=True) if title_node else fallback_title)
    if not title:
        raise ValueError("detail page does not contain a book title")

    content_text = content.get_text("\n", strip=True)
    date_match = _DATE_RE.search(content_text)
    published_at = fallback_date
    if date_match:
        try:
            published_at = date(*(int(part) for part in date_match.groups())).isoformat()
        except ValueError:
            pass
    publisher_match = _PUBLISHER_RE.search(content_text)
    publisher = _clean(publisher_match.group(1)) if publisher_match else None

    cover = content.find("img")
    cover_url = None
    if isinstance(cover, Tag):
        cover_src = cover.get("data-lazy-src") or cover.get("src")
        if cover_src:
            cover_url = urljoin(origin_url, str(cover_src))

    code_match = _CODE_RE.search(content_text)
    page_code = code_match.group(1) if code_match else None
    downloads: list[DownloadLink] = []
    official_url = None
    seen_urls: set[str] = set()
    for link in content.find_all("a", href=True):
        href = urljoin(origin_url, str(link["href"]).strip())
        if href in seen_urls:
            continue
        seen_urls.add(href)
        provider = classify_download(href)
        label = _clean(link.get_text(" ", strip=True))
        if provider:
            query_code = parse_qs(urlparse(href).query).get("pwd", [None])[0]
            downloads.append(
                DownloadLink(provider=provider, url=href, extract_code=query_code or page_code, label=label)
            )
        elif official_url is None and urlparse(href).scheme in {"http", "https"}:
            official_url = href

    tags = []
    for tag in soup.select('.entry-meta a[rel~="tag"], .entry-meta a[rel~="category"]'):
        value = _clean(tag.get_text(" ", strip=True))
        if value and value not in tags:
            tags.append(value)

    return Book(
        title=title,
        origin_url=origin_url,
        slug=_slug_from_url(origin_url),
        published_at=published_at,
        publisher=publisher,
        official_url=official_url,
        cover_url=cover_url,
        tags=tags,
        downloads=downloads,
    )
