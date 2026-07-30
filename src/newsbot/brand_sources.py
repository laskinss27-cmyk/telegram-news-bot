from __future__ import annotations

import re
import xml.etree.ElementTree as ElementTree
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import urljoin, urlsplit

import requests
from bs4 import BeautifulSoup

from .models import Article
from .text import clean_text, normalize_url


def _parse_iso_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _parse_english_date(value: str) -> datetime | None:
    match = re.search(
        r"\b("
        r"January|February|March|April|May|June|July|August|"
        r"September|October|November|December"
        r")\s+\d{1,2},\s+\d{4}\b",
        value,
    )
    if not match:
        return None
    try:
        return datetime.strptime(match.group(0), "%B %d, %Y").replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        return None


def _image_url(container, base_url: str) -> str | None:
    image = container.select_one("img[src]") if container else None
    if not image:
        return None
    return urljoin(base_url, image.get("src", ""))


def _read_ctv(
    source: dict[str, Any], soup: BeautifulSoup, fetched_at: datetime
) -> list[Article]:
    articles = []
    seen = set()
    for link in soup.select("a.new-preview[href]"):
        url = normalize_url(urljoin(source["page_url"], link.get("href", "")))
        if url in seen:
            continue
        seen.add(url)
        title = clean_text(link.get_text(" ", strip=True))
        title = re.sub(r"^NEW\s+", "", title, flags=re.IGNORECASE)
        if not title:
            continue
        articles.append(
            Article(
                source=source["name"],
                title=title,
                url=url,
                image_url=_image_url(link, url),
                # CTV не показывает дату карточки. Берём только верхнюю карточку,
                # поэтому момент обнаружения безопасно считать датой публикации.
                published_at=fetched_at,
                source_settings=source,
            )
        )
        if len(articles) >= source["max_entries"]:
            break
    return articles


def _hydrate_ctv(
    article: Article, session: requests.Session, timeout: int
) -> Article:
    response = session.get(article.url, timeout=timeout)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    page_text = clean_text(soup.get_text(" ", strip=True))
    date_match = re.search(r"\b\d{2}/\d{2}/\d{4}\b", page_text)
    if date_match:
        try:
            article.published_at = datetime.strptime(
                date_match.group(0), "%d/%m/%Y"
            ).replace(tzinfo=timezone.utc)
        except ValueError:
            pass

    paragraphs = []
    for paragraph in soup.select(".single-news p, main p"):
        text = clean_text(paragraph.get_text(" ", strip=True))
        if len(text) < 40 or text in paragraphs:
            continue
        paragraphs.append(text)
        if sum(map(len, paragraphs)) >= 700 or len(paragraphs) >= 3:
            break
    if paragraphs:
        article.summary = " ".join(paragraphs)

    image = soup.select_one(".single-news img[src], main img[src]")
    if image:
        article.image_url = urljoin(article.url, image.get("src", ""))
    return article


def _read_dahua(
    source: dict[str, Any], soup: BeautifulSoup, fetched_at: datetime
) -> list[Article]:
    articles = []
    seen = set()
    for link in soup.find_all("a", href=True):
        url = normalize_url(urljoin(source["page_url"], link.get("href", "")))
        if not re.search(r"/newsevents/pressrelease/\d+$", urlsplit(url).path.casefold()):
            continue
        if url in seen:
            continue
        seen.add(url)
        title_tag = link.select_one("h3")
        if not title_tag:
            continue
        summary_tag = link.select_one("p.on") or link.select_one("p")
        summary = clean_text(summary_tag.get_text(" ", strip=True) if summary_tag else "")
        articles.append(
            Article(
                source=source["name"],
                title=clean_text(title_tag.get_text(" ", strip=True)),
                url=url,
                summary=summary,
                image_url=_image_url(link, url),
                published_at=_parse_english_date(summary),
                source_settings=source,
            )
        )
        if len(articles) >= source["max_entries"]:
            break
    return articles


def _read_tiandy(
    source: dict[str, Any], soup: BeautifulSoup, fetched_at: datetime
) -> list[Article]:
    articles = []
    for card in soup.select(".newsBox"):
        link = card.select_one("p.newsTitle a[href]")
        if not link:
            continue
        date_tag = card.select_one(".time")
        published_at = None
        if date_tag:
            try:
                published_at = datetime.strptime(
                    clean_text(date_tag.get_text()), "%Y-%m-%d"
                ).replace(tzinfo=timezone.utc)
            except ValueError:
                pass
        summary_tag = card.select_one("p.newsContent")
        articles.append(
            Article(
                source=source["name"],
                title=clean_text(link.get_text(" ", strip=True)),
                url=normalize_url(urljoin(source["page_url"], link.get("href", ""))),
                summary=clean_text(
                    summary_tag.get_text(" ", strip=True) if summary_tag else ""
                ),
                image_url=_image_url(card, source["page_url"]),
                published_at=published_at,
                source_settings=source,
            )
        )
        if len(articles) >= source["max_entries"]:
            break
    return articles


def _read_shelly_sitemap(
    source: dict[str, Any], content: bytes
) -> list[Article]:
    root = ElementTree.fromstring(content)
    namespace = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    required_path = str(source.get("url_contains", "/blogs/media-kit/"))
    rows = []
    for node in root.findall("s:url", namespace):
        url = node.findtext("s:loc", "", namespace).strip()
        if required_path not in url:
            continue
        published_at = _parse_iso_date(node.findtext("s:lastmod", "", namespace))
        rows.append((published_at, normalize_url(url)))
    rows.sort(
        key=lambda row: row[0] or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    articles = []
    for published_at, url in rows[: source["max_entries"]]:
        slug = urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1]
        articles.append(
            Article(
                source=source["name"],
                title=slug.replace("-", " ").strip().title(),
                url=url,
                published_at=published_at,
                source_settings={**source, "prefer_page_title": True},
            )
        )
    return articles


HTML_ADAPTERS: dict[
    str, Callable[[dict[str, Any], BeautifulSoup, datetime], list[Article]]
] = {
    "ctv_news": _read_ctv,
    "dahua_news": _read_dahua,
    "tiandy_news": _read_tiandy,
}


def read_brand_source(
    source: dict[str, Any],
    session: requests.Session,
    timeout: int,
) -> list[Article]:
    response = session.get(source["page_url"], timeout=timeout)
    response.raise_for_status()
    adapter = source["adapter"]
    if adapter == "shelly_sitemap":
        try:
            return _read_shelly_sitemap(source, response.content)
        except ElementTree.ParseError as exc:
            raise ValueError(f"XML-карта Shelly не распознана: {exc}") from exc
    parser = HTML_ADAPTERS.get(adapter)
    if not parser:
        raise ValueError(f"неизвестный HTML-адаптер: {adapter}")
    soup = BeautifulSoup(response.text, "html.parser")
    articles = parser(source, soup, datetime.now(timezone.utc))
    if adapter == "ctv_news" and articles:
        _hydrate_ctv(articles[0], session, timeout)
    return articles
