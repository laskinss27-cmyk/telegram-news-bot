import unittest

from newsbot.text import (
    article_matches,
    build_telegram_html,
    normalize_url,
    truncate,
)


class TextTests(unittest.TestCase):
    def test_normalize_url_removes_tracking(self):
        actual = normalize_url(
            "HTTPS://Example.COM/news/?utm_source=tg&id=7&fbclid=abc#part"
        )
        self.assertEqual(actual, "https://example.com/news?id=7")

    def test_topic_filter(self):
        self.assertTrue(
            article_matches(
                "Новая нейросеть",
                "Описание",
                ["нейросеть"],
                [],
                [],
                [],
            )
        )
        self.assertFalse(
            article_matches(
                "Новая нейросеть",
                "Партнерский материал",
                ["нейросеть"],
                ["партнерский"],
                [],
                [],
            )
        )

    def test_html_is_escaped_and_limited(self):
        result = build_telegram_html(
            title="<Новость>",
            summary="Текст & подробности " * 100,
            source="Сайт",
            url="https://example.com/?a=1&b=2",
            summary_limit=650,
            add_source_name=True,
            add_link=True,
        )
        self.assertIn("&lt;Новость&gt;", result)
        self.assertIn("&amp;", result)
        self.assertLessEqual(len(result), 1000)

    def test_truncate(self):
        self.assertEqual(truncate("коротко", 20), "коротко")
        self.assertTrue(truncate("очень длинная строка", 10).endswith("…"))
        self.assertEqual(
            truncate(
                "Первое предложение достаточно длинное. Второе тоже длинное и лишнее.",
                45,
            ),
            "Первое предложение достаточно длинное.",
        )


if __name__ == "__main__":
    unittest.main()
