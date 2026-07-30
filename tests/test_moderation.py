import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from newsbot.app import process_moderation
from newsbot.models import Article
from newsbot.moderation import ModerationQueue


class ModerationQueueTests(unittest.TestCase):
    def test_persists_draft_decision_and_update_offset(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "moderation.json"
            queue = ModerationQueue(path)
            item = queue.add(
                Article(
                    source="Портал",
                    title="Умный дом",
                    url="https://example.com/news?utm_source=rss",
                    image_url="https://example.com/photo.jpg",
                ),
                "<b>Умный дом</b>",
                123,
                "telegram-file-id",
            )
            queue.decide(item["id"], "skipped")
            queue.update_offset = 77
            queue.save()

            restored = ModerationQueue(path)
            restored.load()

            self.assertEqual(restored.update_offset, 77)
            self.assertEqual(restored.get(item["id"])["status"], "skipped")
            self.assertEqual(
                restored.get(item["id"])["photo_file_id"],
                "telegram-file-id",
            )

    def test_processes_publish_button_only_from_configured_message(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "moderation.json"
            queue = ModerationQueue(path)
            item = queue.add(
                Article(
                    source="Портал",
                    title="Новая камера",
                    url="https://example.com/camera",
                    image_url="https://example.com/camera.jpg",
                ),
                "<b>Новая камера</b>",
                321,
                "telegram-photo",
            )
            queue.save()
            config = {
                "runtime": {
                    "request_timeout_seconds": 20,
                    "user_agent": "test",
                    "moderation_file": path,
                    "state_max_items": 1000,
                },
                "publishing": {"disable_notification": False},
            }
            final_publisher = Mock()
            review_publisher = Mock()
            review_publisher.get_callback_updates.return_value = [
                {
                    "update_id": 50,
                    "callback_query": {
                        "id": "callback-1",
                        "data": f"publish:{item['id']}",
                        "message": {
                            "message_id": 321,
                            "chat": {"id": -1004425872708},
                        },
                    },
                }
            ]

            with (
                patch.dict(
                    "os.environ",
                    {
                        "TELEGRAM_BOT_TOKEN": "token",
                        "TELEGRAM_CHAT_ID": "@SHomeNews",
                        "TELEGRAM_MODERATION_CHAT_ID": "-1004425872708",
                    },
                    clear=False,
                ),
                patch(
                    "newsbot.app.TelegramPublisher",
                    side_effect=[final_publisher, review_publisher],
                ),
            ):
                self.assertEqual(process_moderation(config), 0)

            final_publisher.publish.assert_called_once_with(
                "<b>Новая камера</b>",
                "https://example.com/camera.jpg",
                "telegram-photo",
            )
            restored = ModerationQueue(path)
            restored.load()
            self.assertEqual(restored.get(item["id"])["status"], "published")
            self.assertEqual(restored.update_offset, 51)
            review_publisher.remove_review_buttons.assert_called_once_with(321)


if __name__ == "__main__":
    unittest.main()
