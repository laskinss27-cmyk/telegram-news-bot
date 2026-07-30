from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from .models import Article
from .text import normalize_title, normalize_url


class State:
    def __init__(self, path: Path, max_items: int = 1000) -> None:
        self.path = path
        self.max_items = max_items
        self.items: list[dict[str, Any]] = []

    def load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        items = data.get("items", [])
        if isinstance(items, list):
            self.items = [item for item in items if isinstance(item, dict)]

    @staticmethod
    def key_for(url: str) -> str:
        return hashlib.sha256(normalize_url(url).encode("utf-8")).hexdigest()

    def contains(self, article: Article) -> bool:
        key = self.key_for(article.url)
        title = normalize_title(article.title)
        for item in self.items:
            if item.get("key") == key:
                return True
            previous_title = normalize_title(str(item.get("title", "")))
            if (
                title
                and previous_title
                and SequenceMatcher(None, title, previous_title).ratio() >= 0.92
            ):
                return True
        return False

    def add(self, article: Article) -> None:
        self.items.append(
            {
                "key": self.key_for(article.url),
                "url": article.url,
                "title": article.title,
                "posted_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        self.items = self.items[-self.max_items :]

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": 1, "items": self.items[-self.max_items :]}
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.path)
