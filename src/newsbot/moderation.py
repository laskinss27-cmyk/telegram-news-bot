from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import Article
from .state import State


class ModerationQueue:
    def __init__(self, path: Path, max_items: int = 1000) -> None:
        self.path = path
        self.max_items = max_items
        self.update_offset = 0
        self.items: list[dict[str, Any]] = []

    def load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        offset = data.get("update_offset", 0)
        if isinstance(offset, int) and offset >= 0:
            self.update_offset = offset
        items = data.get("items", [])
        if isinstance(items, list):
            self.items = [item for item in items if isinstance(item, dict)]

    @staticmethod
    def id_for(url: str) -> str:
        return State.key_for(url)[:16]

    def get(self, draft_id: str) -> dict[str, Any] | None:
        return next(
            (item for item in self.items if item.get("id") == draft_id),
            None,
        )

    def add(
        self,
        article: Article,
        text: str,
        review_message_id: int,
        photo_file_id: str | None = None,
    ) -> dict[str, Any]:
        existing = self.get(self.id_for(article.url))
        if existing is not None:
            return existing
        item = {
            "id": self.id_for(article.url),
            "status": "pending",
            "source": article.source,
            "title": article.title,
            "url": article.url,
            "text": text,
            "image_url": article.image_url,
            "photo_file_id": photo_file_id,
            "review_message_id": review_message_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self.items.append(item)
        self.items = self.items[-self.max_items :]
        return item

    def decide(self, draft_id: str, status: str) -> dict[str, Any]:
        if status not in {"published", "skipped"}:
            raise ValueError(f"Недопустимый статус модерации: {status}")
        item = self.get(draft_id)
        if item is None:
            raise KeyError(draft_id)
        item["status"] = status
        item["decided_at"] = datetime.now(timezone.utc).isoformat()
        return item

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "update_offset": self.update_offset,
            "items": self.items[-self.max_items :],
        }
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.path)
