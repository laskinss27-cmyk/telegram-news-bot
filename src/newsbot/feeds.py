from __future__ import annotations

import calendar
import logging
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin, urlsplit

import feedparser
import requests
from bs4 import BeautifulSoup

from .models import Article
from .text import clean_text, normalize_url

LOGGER = logging.getLogger(__name__)


def _entry_time(entry: Any) -> datetime | None:
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if not parsed:
        return None
    return datetime.fromtimestamp(calendar.timegm(parsed), tz=timezone.utc)


def _first_image(entry: Any, base_url: str) -> str | None:
    for field in ("media_content", "media_thumbnail"):
        for item in entry.get(field, []) or []:
            url = item.get("url")
            media_type = str(item.get("type", ""))
            if url and (not media_type or media_type.startswith("image/")):
                return urljoin(base_url, url)

    for item in entry.get("enclosures", []) or []:
        url = item.get("href") or item.get("url")
        media_type = str(item.get("type", ""))
        if url and media_type.startswith("image/"):
            return urljoin(base_url, url)

    for field in ("summary", "description"):
        soup = BeautifulSoup(entry.get(field, "") or "", "html.parser")
        image = soup.find("img", src=True)
        if image:
            return urljoin(base_url, image["src"])
    return None


def read_source(
    source: dict[str, Any],
    session: requests.Session,
    timeout: int,
) -> list[Article]:
    if source.get("kind", "rss") == "html":
        from .brand_sources import read_brand_source

        return read_brand_source(source, session, timeout)

    response = session.get(source["rss_url"], timeout=timeout)
    response.raise_for_status()
    parsed = feedparser.parse(response.content)
    if parsed.bozo and not parsed.entries:
        raise ValueError(f"лента не распознана: {parsed.bozo_exception}")

    articles = []
    for entry in parsed.entries:
        title = clean_text(entry.get("title"))
        raw_url = entry.get("link")
        if not title or not raw_url:
            continue
        url = normalize_url(urljoin(source["rss_url"], raw_url))
        if urlsplit(url).scheme not in {"http", "https"}:
            continue
        summary = clean_text(
            entry.get("summary") or entry.get("description") or entry.get("subtitle")
        )
        articles.append(
            Article(
                source=source["name"],
                title=title,
                url=url,
                summary=summary,
                image_url=_first_image(entry, url),
                published_at=_entry_time(entry),
                source_settings=source,
            )
        )
    return articles


def enrich_from_article(
    article: Article,
    session: requests.Session,
    timeout: int,
) -> Article:
    if not article.source_settings.get("fetch_article", True):
        return article
    if article.image_url and len(article.summary) >= 120:
        return article

    try:
        response = session.get(article.url, timeout=timeout)
        response.raise_for_status()
        if "html" not in response.headers.get("Content-Type", "").casefold():
            return article
        soup = BeautifulSoup(response.text, "html.parser")
        if article.source_settings.get("prefer_page_title"):
            tag = soup.select_one(
                'meta[property="og:title"][content], '
                'meta[name="twitter:title"][content]'
            )
            if tag and tag.get("content"):
                article.title = clean_text(tag.get("content"))
        if not article.image_url:
            tag = soup.select_one(
                'meta[property="og:image"][content], meta[name="twitter:image"][content]'
            )
            if tag:
                article.image_url = urljoin(article.url, tag.get("content", ""))
            else:
                image = soup.select_one(
                    "article img[src], main img[src], .entry-content img[src]"
                )
                if image:
                    article.image_url = urljoin(article.url, image.get("src", ""))
        if len(article.summary) < 120:
            tag = soup.select_one(
                'meta[name="description"][content], meta[property="og:description"][content]'
            )
            if tag:
                article.summary = clean_text(tag.get("content"))
            if len(article.summary) < 120:
                paragraphs = []
                for paragraph in soup.select(
                    ".single-news p, article p, main p, .entry-content p"
                ):
                    text = clean_text(paragraph.get_text(" ", strip=True))
                    if len(text) < 40 or text in paragraphs:
                        continue
                    paragraphs.append(text)
                    if sum(map(len, paragraphs)) >= 700 or len(paragraphs) >= 3:
                        break
                if paragraphs:
                    article.summary = " ".join(paragraphs)
    except requests.RequestException as exc:
        LOGGER.warning("Не удалось открыть статью %s: %s", article.url, exc)
    return article
