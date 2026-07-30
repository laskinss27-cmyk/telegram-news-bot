import unittest
from unittest.mock import Mock

import requests

from newsbot.models import Article
from newsbot.translation import GoogleCloudTranslator, TranslationError


class TranslationTests(unittest.TestCase):
    def test_translates_title_and_summary_to_russian(self):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "data": {
                "translations": [
                    {"translatedText": "Новая камера Dahua"},
                    {
                        "translatedText": "Интеллектуальная "
                        "видеоаналитика &amp; наблюдение."
                    },
                ]
            }
        }
        session = Mock()
        session.post.return_value = response
        translator = GoogleCloudTranslator("secret-key", session, 20)
        article = Article(
            source="Dahua",
            title="New Dahua camera",
            summary="Intelligent video analytics & surveillance.",
            url="https://example.com/news",
        )

        translated = translator.translate_article(article, 500)

        self.assertEqual(translated.title, "Новая камера Dahua")
        self.assertEqual(
            translated.summary,
            "Интеллектуальная видеоаналитика & наблюдение.",
        )
        _, kwargs = session.post.call_args
        self.assertNotIn("params", kwargs)
        self.assertEqual(kwargs["headers"]["X-goog-api-key"], "secret-key")
        self.assertEqual(kwargs["json"]["target"], "ru")
        self.assertEqual(len(kwargs["json"]["q"]), 2)

    def test_rejects_incomplete_translation(self):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"data": {"translations": []}}
        session = Mock()
        session.post.return_value = response
        translator = GoogleCloudTranslator("secret-key", session, 20)

        with self.assertRaises(TranslationError):
            translator.translate_texts(["Camera"])

    def test_wraps_network_error_without_exposing_key(self):
        session = Mock()
        session.post.side_effect = requests.ConnectionError("offline")
        translator = GoogleCloudTranslator("secret-key", session, 20)

        with self.assertRaisesRegex(TranslationError, "недоступен") as caught:
            translator.translate_texts(["Camera"])

        self.assertNotIn("secret-key", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
