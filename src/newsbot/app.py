from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

from .feeds import enrich_from_article, read_source
from .state import State
from .telegram import TelegramPublisher
from .text import (
    article_matches,
    build_telegram_html,
    normalize_title,
    normalize_url,
)
from .translation import GoogleCloudTranslator, TranslationError

LOGGER = logging.getLogger(__name__)


def collect_candidates(
    config: dict[str, Any], session: requests.Session, state: State
) -> list:
    timeout = config["runtime"]["request_timeout_seconds"]
    topic = config["topic"]
    cutoff = datetime.now(timezone.utc) - timedelta(
        hours=config["publishing"]["lookback_hours"]
    )
    candidates = []
    run_urls: set[str] = set()
    run_titles: set[str] = set()

    for source in config["sources"]:
        if not source["enabled"]:
            continue
        try:
            articles = read_source(source, session, timeout)
        except (requests.RequestException, ValueError) as exc:
            LOGGER.error("Источник «%s» недоступен: %s", source["name"], exc)
            continue
        LOGGER.info("Источник «%s»: найдено записей — %d", source["name"], len(articles))

        for article in articles:
            if source.get("skip_undated", False) and article.published_at is None:
                continue
            if article.published_at and article.published_at < cutoff:
                continue
            if state.contains(article):
                continue
            required = source.get("require_any", [])
            if required:
                haystack = f"{article.title} {article.summary}".casefold()
                if not any(term.casefold() in haystack for term in required):
                    continue
            if not article_matches(
                article.title,
                article.summary,
                topic["include_any"],
                topic["exclude"],
                source["include_any"],
                source["exclude"],
            ):
                continue
            normalized_url = normalize_url(article.url)
            normalized_title = normalize_title(article.title)
            if normalized_url in run_urls or normalized_title in run_titles:
                continue
            run_urls.add(normalized_url)
            run_titles.add(normalized_title)
            candidates.append(article)

    candidates.sort(
        key=lambda item: item.published_at or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    return candidates[: config["publishing"]["max_posts_per_run"]]


def run(config: dict[str, Any], dry_run: bool = False, check_only: bool = False) -> int:
    enabled_sources = [source for source in config["sources"] if source["enabled"]]
    if not enabled_sources:
        LOGGER.warning("Нет включённых источников. Настройте config.yaml.")
        return 0

    runtime = config["runtime"]
    session = requests.Session()
    session.headers.update({"User-Agent": runtime["user_agent"]})
    state = State(runtime["state_file"], runtime["state_max_items"])
    state.load()

    translation_settings = config["translation"]
    translation_required = translation_settings["required"]
    translated_sources = [
        source for source in enabled_sources if source.get("translate", False)
    ]
    translator = None
    if translated_sources:
        translation_key = os.getenv("GOOGLE_TRANSLATE_API_KEY", "").strip()
        if translation_key:
            translator = GoogleCloudTranslator(
                translation_key,
                session,
                runtime["request_timeout_seconds"],
                translation_settings["target_language"],
            )
        elif translation_required and not dry_run:
            raise RuntimeError(
                "Для перевода Dahua, Tiandy и Shelly задайте "
                "GOOGLE_TRANSLATE_API_KEY"
            )
        else:
            LOGGER.warning(
                "GOOGLE_TRANSLATE_API_KEY не задан: англоязычные материалы "
                "будут пропущены."
            )

    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    publisher = None
    if not dry_run:
        if not token or not chat_id:
            raise RuntimeError(
                "Для публикации задайте TELEGRAM_BOT_TOKEN и TELEGRAM_CHAT_ID"
            )
        publisher = TelegramPublisher(
            token,
            chat_id,
            session,
            runtime["request_timeout_seconds"],
            config["publishing"]["disable_notification"],
        )
        if check_only:
            publisher.check_access()
            if translator is not None:
                translator.check_access()
            LOGGER.info("Токен и доступ к чату работают.")
            return 0
    elif check_only:
        LOGGER.info("Конфигурация корректна; проверка Telegram пропущена в dry-run.")
        return 0

    candidates = collect_candidates(config, session, state)
    if not candidates:
        LOGGER.info("Подходящих новых материалов нет.")
        return 0

    # Отправляем выбранные материалы от более раннего к более позднему.
    for article in reversed(candidates):
        article = enrich_from_article(
            article, session, runtime["request_timeout_seconds"]
        )
        if article.source_settings.get("translate", False):
            if translator is None:
                LOGGER.warning(
                    "Пропущено без перевода: %s — %s",
                    article.source,
                    article.title,
                )
                continue
            try:
                article = translator.translate_article(
                    article, config["publishing"]["summary_max_chars"]
                )
            except TranslationError as exc:
                if translation_required:
                    LOGGER.error(
                        "Материал «%s» пропущен: %s", article.title, exc
                    )
                    continue
                LOGGER.warning(
                    "Не удалось перевести «%s», публикуется оригинал: %s",
                    article.title,
                    exc,
                )
        text = build_telegram_html(
            title=article.title,
            summary=article.summary,
            source=article.source,
            url=article.url,
            summary_limit=config["publishing"]["summary_max_chars"],
            add_source_name=config["publishing"]["add_source_name"],
            add_link=config["publishing"]["add_link"],
        )
        if dry_run:
            print(f"\n--- {article.source} ---\n{text}\nФото: {article.image_url or 'нет'}")
            continue
        assert publisher is not None
        publisher.publish(text, article.image_url)
        state.add(article)
        state.save()
        LOGGER.info("Опубликовано: %s", article.title)
    return 0
