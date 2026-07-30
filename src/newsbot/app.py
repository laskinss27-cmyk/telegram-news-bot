from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

from .feeds import enrich_from_article, read_source
from .moderation import ModerationQueue
from .models import Article
from .state import State
from .telegram import TelegramError, TelegramPublisher, discover_command_chats
from .text import (
    article_matches,
    build_telegram_html,
    normalize_title,
    normalize_url,
)
from .translation import MyMemoryTranslator, TranslationError

LOGGER = logging.getLogger(__name__)


def discover_moderation_chats(config: dict[str, Any]) -> int:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("Для поиска чата задайте TELEGRAM_BOT_TOKEN")

    runtime = config["runtime"]
    session = requests.Session()
    session.headers.update({"User-Agent": runtime["user_agent"]})
    chats = discover_command_chats(
        token,
        session,
        runtime["request_timeout_seconds"],
    )
    if not chats:
        raise RuntimeError(
            "Команда /id не найдена. Отправьте /id в нужную группу и повторите."
        )

    for chat in chats:
        print(
            f"MODERATION_CHAT_ID={chat['id']} | "
            f"type={chat['type']} | title={chat['title']}"
        )
    return 0


def collect_candidates(
    config: dict[str, Any], session: requests.Session, state: State
) -> list[Article]:
    timeout = config["runtime"]["request_timeout_seconds"]
    topic = config["topic"]
    cutoff = datetime.now(timezone.utc) - timedelta(
        hours=config["publishing"]["lookback_hours"]
    )
    candidates: list[Article] = []
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
        LOGGER.info(
            "Источник «%s»: найдено записей — %d", source["name"], len(articles)
        )

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
        key=lambda item: item.published_at
        or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    return candidates[: config["publishing"]["max_posts_per_run"]]


def _translator(
    config: dict[str, Any],
    session: requests.Session,
    enabled_sources: list[dict[str, Any]],
) -> MyMemoryTranslator | None:
    if not any(source.get("translate", False) for source in enabled_sources):
        return None
    return MyMemoryTranslator(
        session,
        config["runtime"]["request_timeout_seconds"],
        config["translation"]["target_language"],
    )


def _prepare_article(
    article: Article,
    config: dict[str, Any],
    session: requests.Session,
    translator: MyMemoryTranslator | None,
) -> Article | None:
    article = enrich_from_article(
        article, session, config["runtime"]["request_timeout_seconds"]
    )
    if not article.source_settings.get("translate", False):
        return article
    if translator is None:
        LOGGER.warning(
            "Пропущено без перевода: %s — %s", article.source, article.title
        )
        return None
    try:
        return translator.translate_article(
            article, config["publishing"]["summary_max_chars"]
        )
    except TranslationError as exc:
        if config["translation"]["required"]:
            LOGGER.error("Материал «%s» пропущен: %s", article.title, exc)
            return None
        LOGGER.warning(
            "Не удалось перевести «%s», используется оригинал: %s",
            article.title,
            exc,
        )
        return article


def _post_text(article: Article, config: dict[str, Any]) -> str:
    return build_telegram_html(
        title=article.title,
        summary=article.summary,
        source=article.source,
        url=article.url,
        summary_limit=config["publishing"]["summary_max_chars"],
        add_source_name=config["publishing"]["add_source_name"],
        add_link=config["publishing"]["add_link"],
    )


def run(
    config: dict[str, Any],
    dry_run: bool = False,
    check_only: bool = False,
    queue_for_review: bool = False,
) -> int:
    enabled_sources = [source for source in config["sources"] if source["enabled"]]
    if not enabled_sources:
        LOGGER.warning("Нет включённых источников. Настройте config.yaml.")
        return 0

    runtime = config["runtime"]
    session = requests.Session()
    session.headers.update({"User-Agent": runtime["user_agent"]})
    state = State(runtime["state_file"], runtime["state_max_items"])
    state.load()
    translator = _translator(config, session, enabled_sources)

    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    channel_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    moderation_chat_id = os.getenv("TELEGRAM_MODERATION_CHAT_ID", "").strip()
    publisher: TelegramPublisher | None = None

    if check_only and not dry_run:
        if not token or not channel_id or not moderation_chat_id:
            raise RuntimeError(
                "Для проверки задайте TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID "
                "и TELEGRAM_MODERATION_CHAT_ID"
            )
        TelegramPublisher(
            token,
            channel_id,
            session,
            runtime["request_timeout_seconds"],
            config["publishing"]["disable_notification"],
        ).check_access()
        TelegramPublisher(
            token,
            moderation_chat_id,
            session,
            runtime["request_timeout_seconds"],
        ).check_access()
        if translator is not None:
            translator.check_access()
        LOGGER.info("Бот видит канал и группу модерации; перевод доступен.")
        return 0
    if check_only:
        LOGGER.info(
            "Конфигурация корректна; проверка Telegram пропущена в dry-run."
        )
        return 0

    moderation_queue: ModerationQueue | None = None
    if not dry_run:
        target_chat = moderation_chat_id if queue_for_review else channel_id
        if not token or not target_chat:
            required_chat = (
                "TELEGRAM_MODERATION_CHAT_ID"
                if queue_for_review
                else "TELEGRAM_CHAT_ID"
            )
            raise RuntimeError(
                f"Для отправки задайте TELEGRAM_BOT_TOKEN и {required_chat}"
            )
        publisher = TelegramPublisher(
            token,
            target_chat,
            session,
            runtime["request_timeout_seconds"],
            config["publishing"]["disable_notification"],
        )
        if queue_for_review:
            moderation_queue = ModerationQueue(
                runtime["moderation_file"], runtime["state_max_items"]
            )
            moderation_queue.load()

    candidates = collect_candidates(config, session, state)
    if not candidates:
        LOGGER.info("Подходящих новых материалов нет.")
        return 0

    # Отправляем выбранные материалы от более раннего к более позднему.
    for candidate in reversed(candidates):
        article = _prepare_article(candidate, config, session, translator)
        if article is None:
            continue
        text = _post_text(article, config)
        if dry_run:
            print(
                f"\n--- {article.source} ---\n{text}\n"
                f"Фото: {article.image_url or 'нет'}"
            )
            continue

        assert publisher is not None
        if queue_for_review:
            assert moderation_queue is not None
            draft_id = moderation_queue.id_for(article.url)
            result = publisher.send_for_review(text, article.image_url, draft_id)
            photos = result.get("photo") or []
            photo_file_id = (
                str(photos[-1].get("file_id", "")).strip() if photos else None
            )
            moderation_queue.add(
                article,
                text,
                int(result["message_id"]),
                photo_file_id or None,
            )
            moderation_queue.save()
            state.add(article)
            state.save()
            LOGGER.info("Отправлено на модерацию: %s", article.title)
        else:
            publisher.publish(text, article.image_url)
            state.add(article)
            state.save()
            LOGGER.info("Опубликовано: %s", article.title)
    return 0


def process_moderation(config: dict[str, Any]) -> int:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    channel_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    moderation_chat_id = os.getenv("TELEGRAM_MODERATION_CHAT_ID", "").strip()
    if not token or not channel_id or not moderation_chat_id:
        raise RuntimeError(
            "Для модерации задайте TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID "
            "и TELEGRAM_MODERATION_CHAT_ID"
        )

    runtime = config["runtime"]
    session = requests.Session()
    session.headers.update({"User-Agent": runtime["user_agent"]})
    queue = ModerationQueue(
        runtime["moderation_file"], runtime["state_max_items"]
    )
    queue.load()
    final_publisher = TelegramPublisher(
        token,
        channel_id,
        session,
        runtime["request_timeout_seconds"],
        config["publishing"]["disable_notification"],
    )
    review_publisher = TelegramPublisher(
        token,
        moderation_chat_id,
        session,
        runtime["request_timeout_seconds"],
    )

    updates = sorted(
        review_publisher.get_callback_updates(queue.update_offset),
        key=lambda update: int(update.get("update_id", 0)),
    )
    if not updates:
        LOGGER.info("Новых решений модератора нет.")
        return 0

    for update in updates:
        update_id = int(update.get("update_id", 0))
        callback = update.get("callback_query") or {}
        message = callback.get("message") or {}
        chat = message.get("chat") or {}
        callback_id = str(callback.get("id", ""))
        message_id = int(message.get("message_id", 0))
        data = str(callback.get("data", ""))

        # Игнорируем любые кнопки вне заданной группы.
        if str(chat.get("id", "")) != moderation_chat_id:
            queue.update_offset = max(queue.update_offset, update_id + 1)
            queue.save()
            continue

        action, separator, draft_id = data.partition(":")
        item = queue.get(draft_id) if separator else None
        if (
            action not in {"publish", "skip"}
            or item is None
            or int(item.get("review_message_id", 0)) != message_id
        ):
            if callback_id:
                try:
                    review_publisher.answer_callback(
                        callback_id, "Черновик не найден"
                    )
                except TelegramError as exc:
                    LOGGER.warning("Не удалось ответить на кнопку: %s", exc)
            queue.update_offset = max(queue.update_offset, update_id + 1)
            queue.save()
            continue

        if item.get("status") == "pending":
            if action == "publish":
                final_publisher.publish(
                    str(item["text"]),
                    item.get("image_url"),
                    item.get("photo_file_id"),
                )
                queue.decide(draft_id, "published")
                result_text = "✅ Опубликовано в канале"
                callback_text = "Опубликовано"
                LOGGER.info("Опубликовано после модерации: %s", item["title"])
            else:
                queue.decide(draft_id, "skipped")
                result_text = "❌ Пропущено"
                callback_text = "Пропущено"
                LOGGER.info("Пропущено модератором: %s", item["title"])
            # Сохраняем решение сразу после публикации, до косметических действий.
            queue.save()
        else:
            result_text = (
                "✅ Уже опубликовано"
                if item.get("status") == "published"
                else "❌ Уже пропущено"
            )
            callback_text = "Уже обработано"

        for operation in (
            lambda: review_publisher.answer_callback(
                callback_id, callback_text
            ),
            lambda: review_publisher.remove_review_buttons(message_id),
            lambda: review_publisher.send_review_result(
                message_id, result_text
            ),
        ):
            try:
                operation()
            except TelegramError as exc:
                LOGGER.warning("Не удалось обновить сообщение модерации: %s", exc)

        queue.update_offset = max(queue.update_offset, update_id + 1)
        queue.save()
    return 0
