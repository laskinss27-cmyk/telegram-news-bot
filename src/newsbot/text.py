from __future__ import annotations

import html
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from bs4 import BeautifulSoup


TRACKING_PARAMS = {
    "fbclid",
    "gclid",
    "yclid",
    "ref",
    "referrer",
    "source",
}


def clean_text(value: str | None) -> str:
    if not value:
        return ""
    text = BeautifulSoup(value, "html.parser").get_text(" ", strip=True)
    text = re.sub(r"\s+", " ", html.unescape(text)).strip()
    return re.sub(r"\s+([,.!?;:])", r"\1", text)


def truncate(value: str, limit: int) -> str:
    value = value.strip()
    if len(value) <= limit:
        return value
    fragment = value[: max(1, limit - 1)]
    sentence_ends = [
        match.end()
        for match in re.finditer(r"[.!?](?=\s|$)", fragment)
        if match.end() >= limit * 0.55
    ]
    if sentence_ends:
        return fragment[: sentence_ends[-1]].strip()
    shortened = fragment.rsplit(" ", 1)[0].rstrip(".,;:—- ")
    if not shortened:
        shortened = value[: max(1, limit - 1)]
    return shortened + "…"


def normalize_url(url: str) -> str:
    parts = urlsplit(url.strip())
    filtered = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        lowered = key.casefold()
        if lowered.startswith("utm_") or lowered in TRACKING_PARAMS:
            continue
        filtered.append((key, value))
    path = parts.path.rstrip("/") or "/"
    return urlunsplit(
        (parts.scheme.casefold(), parts.netloc.casefold(), path, urlencode(filtered), "")
    )


def normalize_title(title: str) -> str:
    return " ".join(re.findall(r"[\wа-яё]+", title.casefold(), flags=re.UNICODE))


def article_matches(
    title: str,
    summary: str,
    global_include: list[str],
    global_exclude: list[str],
    source_include: list[str],
    source_exclude: list[str],
) -> bool:
    haystack = f"{title} {summary}".casefold()
    excludes = [*global_exclude, *source_exclude]
    if any(term.casefold() in haystack for term in excludes):
        return False

    includes = [*global_include, *source_include]
    return not includes or any(term.casefold() in haystack for term in includes)


def build_telegram_html(
    *,
    title: str,
    summary: str,
    source: str,
    url: str,
    summary_limit: int,
    add_source_name: bool,
    add_link: bool,
    total_limit: int = 1000,
) -> str:
    safe_title = html.escape(truncate(clean_text(title), 240))
    clean_summary = truncate(clean_text(summary), summary_limit)

    tail_parts = []
    if add_source_name:
        tail_parts.append(f"Источник: {html.escape(source)}")
    if add_link:
        tail_parts.append(f'<a href="{html.escape(url, quote=True)}">Читать полностью</a>')
    tail = "\n".join(tail_parts)

    fixed = f"<b>{safe_title}</b>"
    if tail:
        fixed += f"\n\n{tail}"
    available = max(0, total_limit - len(fixed) - 2)
    safe_summary = html.escape(truncate(clean_summary, available)) if available else ""

    parts = [f"<b>{safe_title}</b>"]
    if safe_summary:
        parts.append(safe_summary)
    if tail:
        parts.append(tail)
    return "\n\n".join(parts)
