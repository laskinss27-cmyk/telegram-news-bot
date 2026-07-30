from __future__ import annotations

import json
import logging
from io import BytesIO
from pathlib import PurePosixPath
from urllib.parse import urlsplit

import requests

LOGGER = logging.getLogger(__name__)
MAX_IMAGE_BYTES = 10 * 1024 * 1024


class TelegramError(RuntimeError):
    pass


def discover_command_chats(
    token: str,
    session: requests.Session,
    timeout: int,
) -> list[dict]:
    try:
        response = session.post(
            f"https://api.telegram.org/bot{token}/getUpdates",
            data={
                "limit": 100,
                "timeout": 0,
                "allowed_updates": json.dumps(["message"]),
            },
            timeout=timeout,
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

    chats: dict[str, dict] = {}
    for update in payload.get("result", []):
        message = update.get("message") or {}
        text = str(message.get("text", "")).strip()
        if not text:
            continue
        command = text.split(maxsplit=1)[0].split("@", 1)[0].casefold()
        if command != "/id":
            continue
        chat = message.get("chat") or {}
        chat_id = str(chat.get("id", "")).strip()
        if not chat_id:
            continue
        chats[chat_id] = {
            "id": chat_id,
            "type": str(chat.get("type", "")),
            "title": str(
                chat.get("title")
                or chat.get("username")
                or chat.get("first_name")
                or "без названия"
            ),
        }
    return list(chats.values())


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

    def publish(
        self,
        text: str,
        image_url: str | None,
        photo_file_id: str | None = None,
    ) -> dict:
        common = {
            "chat_id": self._chat_id,
            "parse_mode": "HTML",
            "disable_notification": str(self._disable_notification).lower(),
        }
        if photo_file_id:
            try:
                return self._request(
                    "sendPhoto",
                    data={**common, "photo": photo_file_id, "caption": text},
                )
            except TelegramError as exc:
                LOGGER.warning(
                    "Не удалось переиспользовать фото из Telegram, пробую исходное: %s",
                    exc,
                )
        if image_url:
            image = self._download_image(image_url)
            if image:
                name, content = image
                try:
                    return self._request(
                        "sendPhoto",
                        data={**common, "caption": text},
                        files={"photo": (name, content)},
                    )
                except TelegramError as exc:
                    LOGGER.warning(
                        "Фото не отправлено, отправляю текст: %s", exc
                    )
        return self._request(
            "sendMessage",
            data={**common, "text": text, "disable_web_page_preview": "false"},
        )

    @staticmethod
    def _review_keyboard(draft_id: str) -> str:
        return json.dumps(
            {
                "inline_keyboard": [
                    [
                        {
                            "text": "✅ Опубликовать",
                            "callback_data": f"publish:{draft_id}",
                        },
                        {
                            "text": "❌ Пропустить",
                            "callback_data": f"skip:{draft_id}",
                        },
                    ]
                ]
            },
            ensure_ascii=False,
        )

    def send_for_review(
        self,
        text: str,
        image_url: str | None,
        draft_id: str,
    ) -> dict:
        common = {
            "chat_id": self._chat_id,
            "parse_mode": "HTML",
            "disable_notification": "false",
            "reply_markup": self._review_keyboard(draft_id),
        }
        if image_url:
            image = self._download_image(image_url)
            if image:
                name, content = image
                try:
                    return self._request(
                        "sendPhoto",
                        data={**common, "caption": text},
                        files={"photo": (name, content)},
                    )
                except TelegramError as exc:
                    LOGGER.warning(
                        "Фото не отправлено в предложку, отправляю текст: %s",
                        exc,
                    )
        return self._request(
            "sendMessage",
            data={**common, "text": text, "disable_web_page_preview": "false"},
        )

    def get_callback_updates(self, offset: int) -> list[dict]:
        data: dict[str, str | int] = {
            "limit": 100,
            "timeout": 0,
            "allowed_updates": json.dumps(["callback_query"]),
        }
        if offset > 0:
            data["offset"] = offset
        result = self._request("getUpdates", data=data)
        return result if isinstance(result, list) else []

    def answer_callback(self, callback_query_id: str, text: str) -> None:
        self._request(
            "answerCallbackQuery",
            data={
                "callback_query_id": callback_query_id,
                "text": text,
                "show_alert": "false",
            },
        )

    def remove_review_buttons(self, message_id: int) -> None:
        self._request(
            "editMessageReplyMarkup",
            data={
                "chat_id": self._chat_id,
                "message_id": message_id,
                "reply_markup": json.dumps({"inline_keyboard": []}),
            },
        )

    def send_review_result(self, message_id: int, text: str) -> None:
        self._request(
            "sendMessage",
            data={
                "chat_id": self._chat_id,
                "text": text,
                "reply_to_message_id": message_id,
                "disable_notification": "true",
            },
        )
