from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True)
class Article:
    source: str
    title: str
    url: str
    summary: str = ""
    image_url: str | None = None
    published_at: datetime | None = None
    source_settings: dict = field(default_factory=dict, repr=False)
