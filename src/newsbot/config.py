from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


class ConfigError(ValueError):
    pass


DEFAULTS: dict[str, dict[str, Any]] = {
    "topic": {"include_any": [], "exclude": []},
    "translation": {
        "provider": "mymemory",
        "target_language": "ru",
        "required": True,
    },
    "publishing": {
        "max_posts_per_run": 3,
        "lookback_hours": 24,
        "summary_max_chars": 650,
        "disable_notification": False,
        "add_source_name": True,
        "add_link": True,
    },
    "runtime": {
        "request_timeout_seconds": 20,
        "user_agent": "TelegramNewsBot/0.1 (+RSS reader)",
        "state_file": "data/state.json",
        "state_max_items": 1000,
    },
}


def _as_terms(value: Any, field_name: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ConfigError(f"{field_name} должен быть списком строк")
    return [item.strip() for item in value if item.strip()]


def load_config(path: str | Path) -> dict[str, Any]:
    config_path = Path(path)
    if not config_path.exists():
        raise ConfigError(f"Файл настроек не найден: {config_path}")

    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"Ошибка YAML в {config_path}: {exc}") from exc

    if not isinstance(raw, dict):
        raise ConfigError("Корень config.yaml должен быть объектом")

    config: dict[str, Any] = {"sources": raw.get("sources", [])}
    for section, defaults in DEFAULTS.items():
        supplied = raw.get(section, {})
        if not isinstance(supplied, dict):
            raise ConfigError(f"Раздел {section} должен быть объектом")
        config[section] = {**defaults, **supplied}

    if not isinstance(config["sources"], list):
        raise ConfigError("sources должен быть списком")

    normalized_sources = []
    for index, source in enumerate(config["sources"], start=1):
        if not isinstance(source, dict):
            raise ConfigError(f"sources[{index}] должен быть объектом")
        if not source.get("name"):
            raise ConfigError(f"sources[{index}].name обязателен")
        kind = str(source.get("kind", "rss")).strip().casefold()
        if kind not in {"rss", "html"}:
            raise ConfigError(f"sources[{index}].kind должен быть rss или html")
        if kind == "rss" and not source.get("rss_url"):
            raise ConfigError(f"sources[{index}].rss_url обязателен")
        if kind == "html" and not source.get("page_url"):
            raise ConfigError(f"sources[{index}].page_url обязателен")
        if kind == "html" and not source.get("adapter"):
            raise ConfigError(f"sources[{index}].adapter обязателен")
        max_entries = source.get("max_entries", 30)
        if not isinstance(max_entries, int) or max_entries < 1:
            raise ConfigError(f"sources[{index}].max_entries должен быть положительным целым")
        normalized_sources.append(
            {
                **source,
                "kind": kind,
                "enabled": bool(source.get("enabled", True)),
                "fetch_article": bool(source.get("fetch_article", True)),
                "translate": bool(source.get("translate", False)),
                "max_entries": max_entries,
                "include_any": _as_terms(
                    source.get("include_any", []), f"sources[{index}].include_any"
                ),
                "require_any": _as_terms(
                    source.get("require_any", []), f"sources[{index}].require_any"
                ),
                "exclude": _as_terms(
                    source.get("exclude", []), f"sources[{index}].exclude"
                ),
            }
        )
    config["sources"] = normalized_sources

    config["topic"]["include_any"] = _as_terms(
        config["topic"].get("include_any"), "topic.include_any"
    )
    config["topic"]["exclude"] = _as_terms(
        config["topic"].get("exclude"), "topic.exclude"
    )

    provider = str(config["translation"].get("provider", "")).strip().casefold()
    if provider != "mymemory":
        raise ConfigError("translation.provider должен быть mymemory")
    config["translation"]["provider"] = provider
    target_language = str(
        config["translation"].get("target_language", "")
    ).strip().casefold()
    if not target_language:
        raise ConfigError("translation.target_language не должен быть пустым")
    config["translation"]["target_language"] = target_language
    config["translation"]["required"] = bool(
        config["translation"].get("required", True)
    )

    for field in ("max_posts_per_run", "lookback_hours", "summary_max_chars"):
        value = config["publishing"].get(field)
        if not isinstance(value, int) or value < 1:
            raise ConfigError(f"publishing.{field} должен быть положительным целым")

    timeout = config["runtime"].get("request_timeout_seconds")
    if not isinstance(timeout, int) or timeout < 1:
        raise ConfigError("runtime.request_timeout_seconds должен быть положительным целым")

    state_max = config["runtime"].get("state_max_items")
    if not isinstance(state_max, int) or state_max < 1:
        raise ConfigError("runtime.state_max_items должен быть положительным целым")

    state_path = Path(config["runtime"]["state_file"])
    if not state_path.is_absolute():
        state_path = config_path.parent / state_path
    config["runtime"]["state_file"] = state_path
    return config
