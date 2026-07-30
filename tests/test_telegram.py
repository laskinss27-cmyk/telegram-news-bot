import unittest
from unittest.mock import Mock

from newsbot.telegram import discover_command_chats


class TelegramDiscoveryTests(unittest.TestCase):
    def test_finds_group_with_case_insensitive_id_command(self):
        response = Mock()
        response.ok = True
        response.json.return_value = {
            "ok": True,
            "result": [
                {
                    "update_id": 10,
                    "message": {
                        "text": "/Id",
                        "chat": {
                            "id": -1001234567890,
                            "type": "supergroup",
                            "title": "Предложка SHomeNews",
                        },
                    },
                }
            ],
        }
        session = Mock()
        session.post.return_value = response

        chats = discover_command_chats("secret", session, 20)

        self.assertEqual(
            chats,
            [
                {
                    "id": "-1001234567890",
                    "type": "supergroup",
                    "title": "Предложка SHomeNews",
                }
            ],
        )
        _, kwargs = session.post.call_args
        self.assertNotIn("secret", str(kwargs))

    def test_ignores_unrelated_messages(self):
        response = Mock()
        response.ok = True
        response.json.return_value = {
            "ok": True,
            "result": [
                {
                    "message": {
                        "chat": {"id": -1000, "type": "supergroup"},
                        "new_chat_member": {"is_bot": True},
                    }
                },
                {
                    "message": {
                        "text": "обычное сообщение",
                        "chat": {"id": -1001, "type": "supergroup"},
                    }
                }
            ],
        }
        session = Mock()
        session.post.return_value = response

        self.assertEqual(discover_command_chats("secret", session, 20), [])


if __name__ == "__main__":
    unittest.main()
