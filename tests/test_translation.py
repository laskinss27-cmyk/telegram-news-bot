import unittest
from unittest.mock import Mock

import requests

from newsbot.models import Article
from newsbot.translation import (
    MAX_SEGMENT_BYTES,
    MyMemoryTranslator,
    TranslationError,
)


def translation_response(text: str, *, quota_finished: bool = False) -> Mock:
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "responseData": {"translatedText": text},
        "responseStatus": 200,
        "responseDetails": "",
        "quotaFinished": quota_finished,
    }
    return response


class TranslationTests(unittest.TestCase):
    def test_translates_title_and_summary_to_russian(self):
        session = Mock()
        session.get.side_effect = [
            translation_response("Новая камера Dahua"),
            translation_response(
                "Интеллектуальная видеоаналитика &amp; наблюдение."
            ),
        ]
        translator = MyMemoryTranslator(session, 20)
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
        _, kwargs = session.get.call_args_list[0]
        self.assertEqual(kwargs["params"]["langpair"], "en|ru")
        self.assertEqual(kwargs["params"]["mt"], 1)

    def test_splits_long_text_under_service_limit(self):
        session = Mock()

        def respond(*args, **kwargs):
            self.assertLessEqual(
                len(kwargs["params"]["q"].encode("utf-8")),
                MAX_SEGMENT_BYTES,
            )
            return translation_response("перевод")

        session.get.side_effect = respond
        translator = MyMemoryTranslator(session, 20)

        result = translator.translate_texts(["security camera " * 60])

        self.assertGreater(session.get.call_count, 1)
        self.assertTrue(result[0].startswith("перевод"))

    def test_rejects_exhausted_quota(self):
        session = Mock()
        session.get.return_value = translation_response(
            "MYMEMORY WARNING: quota reached", quota_finished=True
        )
        translator = MyMemoryTranslator(session, 20)

        with self.assertRaises(TranslationError):
            translator.translate_texts(["Camera"])

    def test_wraps_network_error(self):
        session = Mock()
        session.get.side_effect = requests.ConnectionError("offline")
        translator = MyMemoryTranslator(session, 20)

        with self.assertRaisesRegex(TranslationError, "недоступен"):
            translator.translate_texts(["Camera"])


if __name__ == "__main__":
    unittest.main()
