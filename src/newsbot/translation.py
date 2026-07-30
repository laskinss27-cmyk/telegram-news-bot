from __future__ import annotations

import html

import requests

from .models import Article
from .text import clean_text, truncate


GOOGLE_TRANSLATE_URL = "https://translation.googleapis.com/language/translate/v2"


class TranslationError(RuntimeError):
    pass


class GoogleCloudTranslator:
    def __init__(
        self,
        api_key: str,
        session: requests.Session,
        timeout: int,
        target_language: str = "ru",
    ) -> None:
        if not api_key.strip():
            raise TranslationError("Не задан ключ Google Cloud Translation")
        self.api_key = api_key.strip()
        self.session = session
        self.timeout = timeout
        self.target_language = target_language

    def translate_texts(self, texts: list[str]) -> list[str]:
        if not texts:
            return []

        try:
            response = self.session.post(
                GOOGLE_TRANSLATE_URL,
                headers={"X-goog-api-key": self.api_key},
                json={
                    "q": texts,
                    "target": self.target_language,
                    "format": "text",
                },
                timeout=self.timeout,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise TranslationError(f"Google Cloud Translation недоступен: {exc}") from exc

        try:
            items = response.json()["data"]["translations"]
            translated = [
                clean_text(html.unescape(str(item["translatedText"]))) for item in items
            ]
        except (KeyError, TypeError, ValueError) as exc:
            raise TranslationError(
                "Google Cloud Translation вернул неожиданный ответ"
            ) from exc

        if len(translated) != len(texts) or any(not value for value in translated):
            raise TranslationError(
                "Google Cloud Translation вернул неполный перевод"
            )
        return translated

    def translate_article(self, article: Article, summary_limit: int) -> Article:
        title = clean_text(article.title)
        summary = truncate(clean_text(article.summary), summary_limit)
        source_texts = [title]
        if summary:
            source_texts.append(summary)

        translated = self.translate_texts(source_texts)
        article.title = translated[0]
        article.summary = translated[1] if summary else ""
        return article

    def check_access(self) -> None:
        self.translate_texts(["Smart home"])
