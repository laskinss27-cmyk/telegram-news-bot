from __future__ import annotations

import argparse
import logging
import sys

from .app import discover_moderation_chats, process_moderation, run
from .config import ConfigError, load_config
from .telegram import TelegramError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Собирает тематические новости, отправляет их на модерацию "
            "и публикует одобренные материалы в Telegram."
        )
    )
    parser.add_argument(
        "--config", default="config.yaml", help="путь к YAML-настройкам"
    )
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument(
        "--dry-run",
        action="store_true",
        help="показать будущие посты, ничего не отправляя",
    )
    modes.add_argument(
        "--check",
        action="store_true",
        help="проверить настройки и доступ бота к каналу и предложке",
    )
    modes.add_argument(
        "--discover-chats",
        action="store_true",
        help="найти ID чатов, в которых боту отправили команду /id",
    )
    modes.add_argument(
        "--queue",
        action="store_true",
        help="собрать новости и отправить их в предложку",
    )
    modes.add_argument(
        "--process-moderation",
        action="store_true",
        help="обработать нажатия кнопок в предложке",
    )
    return parser


def main() -> int:
    # Старые кодовые страницы Windows не умеют печатать часть символов из RSS.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            reconfigure(encoding="utf-8", errors="replace")
    args = build_parser().parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )
    try:
        config = load_config(args.config)
        if args.discover_chats:
            return discover_moderation_chats(config)
        if args.process_moderation:
            return process_moderation(config)
        return run(
            config,
            dry_run=args.dry_run,
            check_only=args.check,
            # Обычный запуск тоже безопасно отправляет материал в предложку.
            queue_for_review=args.queue or (not args.dry_run and not args.check),
        )
    except (ConfigError, RuntimeError, TelegramError) as exc:
        logging.error("%s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
