from __future__ import annotations

import logging
from io import BytesIO
from pathlib import PurePosixPath
from urllib.parse import urlsplit

import requests

LOGGER = logging.getLogger(__name__)
MAX_IMAGE_BYTES = 10 * 1024 * 1024


class TelegramError(RuntimeError):
    pass


class TelegramPublisher:
    def __init__(
        self,
        token: str,
        chat_id: str,
        session: requests.Session,
        timeout: int,
        disable_notification: bool = False,
    ) -> None:
        self._base_url = f"https://api.telegram.org/bot{token}"
        self._chat_id = chat_id
        self._session = session
        self._timeout = timeout
        self._disable_notification = disable_notification

    def _request(self, method: str, **kwargs):
        try:
            response = self._session.post(
                f"{self._base_url}/{method}", timeout=self._timeout, **kwargs
            )
        except requests.RequestException as exc:
            raise TelegramError("Не удалось подключиться к Telegram") from exc
        try:
            payload = response.json()
        except requests.JSONDecodeError as exc:
            raise TelegramError(f"Telegram вернул HTTP {response.status_code}") from exc
        if not response.ok or not payload.get("ok"):
            description = payload.get("description", f"HTTP {response.status_code}")
            raise TelegramError(f"Telegram: {description}")
        return payload["result"]

    def check_access(self) -> None:
        self._request("getMe")
        self._request("getChat", data={"chat_id": self._chat_id})

    def _download_image(self, image_url: str) -> tuple[str, BytesIO] | None:
        try:
            response = self._session.get(
                image_url, timeout=self._timeout, stream=True
            )
            response.raise_for_status()
            content_type = response.headers.get("Content-Type", "").split(";")[0]
            if not content_type.startswith("image/"):
                return None
            content = bytearray()
            for chunk in response.iter_content(64 * 1024):
                content.extend(chunk)
                if len(content) > MAX_IMAGE_BYTES:
                    LOGGER.warning("Изображение больше 10 МБ: %s", image_url)
                    return None
            suffix = PurePosixPath(urlsplit(image_url).path).suffix or ".jpg"
            return f"news{suffix[:5]}", BytesIO(bytes(content))
        except requests.RequestException as exc:
            LOGGER.warning("Не удалось скачать изображение %s: %s", image_url, exc)
            return None

    def publish(self, text: str, image_url: str | None) -> None:
        common = {
            "chat_id": self._chat_id,
            "parse_mode": "HTML",
            "disable_notification": str(self._disable_notification).lower(),
        }
        if image_url:
            image = self._download_image(image_url)
            if image:
                name, content = image
                try:
                    self._request(
                        "sendPhoto",
                        data={**common, "caption": text},
                        files={"photo": (name, content)},
                    )
                    return
                except TelegramError as exc:
                    LOGGER.warning("Фото не отправлено, отправляю текст: %s", exc)

        self._request(
            "sendMessage",
            data={**common, "text": text, "disable_web_page_preview": "false"},
        )
