from __future__ import annotations

import html

import requests

from .models import Article
from .text import clean_text, truncate


MYMEMORY_URL = "https://api.mymemory.translated.net/get"
MAX_SEGMENT_BYTES = 450


class TranslationError(RuntimeError):
    pass


def _split_by_utf8_bytes(text: str, limit: int = MAX_SEGMENT_BYTES) -> list[str]:
    words = text.split()
    if not words:
        return []

    chunks: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate.encode("utf-8")) <= limit:
            current = candidate
            continue

        if current:
            chunks.append(current)
            current = ""

        if len(word.encode("utf-8")) <= limit:
            current = word
            continue

        fragment = ""
        for character in word:
            candidate = fragment + character
            if len(candidate.encode("utf-8")) > limit:
                chunks.append(fragment)
                fragment = character
            else:
                fragment = candidate
        current = fragment

    if current:
        chunks.append(current)
    return chunks


class MyMemoryTranslator:
    def __init__(
        self,
        session: requests.Session,
        timeout: int,
        target_language: str = "ru",
        source_language: str = "en",
    ) -> None:
        self.session = session
        self.timeout = timeout
        self.target_language = target_language
        self.source_language = source_language

    def _translate_segment(self, text: str) -> str:
        try:
            response = self.session.get(
                MYMEMORY_URL,
                params={
                    "q": text,
                    "langpair": f"{self.source_language}|{self.target_language}",
                    "mt": 1,
                },
                timeout=self.timeout,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise TranslationError(f"MyMemory недоступен: {exc}") from exc

        try:
            payload = response.json()
            status = int(payload.get("responseStatus", 0))
            translated = clean_text(
                html.unescape(str(payload["responseData"]["translatedText"]))
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise TranslationError("MyMemory вернул неожиданный ответ") from exc

        if (
            status != 200
            or payload.get("quotaFinished") is True
            or not translated
            or translated.casefold().startswith("mymemory warning")
        ):
            details = clean_text(str(payload.get("responseDetails", "")))
            suffix = f": {details}" if details else ""
            raise TranslationError(f"MyMemory не выполнил перевод{suffix}")
        return translated

    def translate_texts(self, texts: list[str]) -> list[str]:
        translated_texts = []
        for text in texts:
            chunks = _split_by_utf8_bytes(clean_text(text))
            translated_texts.append(
                " ".join(self._translate_segment(chunk) for chunk in chunks)
            )
        return translated_texts

    def translate_article(self, article: Article, summary_limit: int) -> Article:
        title = clean_text(article.title)
        summary = truncate(clean_text(article.summary), summary_limit)
        source_texts = [title]
        if summary:
            source_texts.append(summary)

        translated = self.translate_texts(source_texts)
        if not translated or not translated[0]:
            raise TranslationError("MyMemory вернул неполный перевод")
        article.title = translated[0]
        article.summary = translated[1] if summary else ""
        return article

    def check_access(self) -> None:
        self.translate_texts(["Smart home"])
