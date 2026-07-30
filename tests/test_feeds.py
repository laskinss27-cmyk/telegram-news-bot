import unittest
from unittest.mock import Mock

from newsbot.feeds import read_source


RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/">
  <channel>
    <title>Test</title>
    <item>
      <title>Новая технология &amp; рынок</title>
      <link>https://example.com/news/1?utm_source=rss</link>
      <description><![CDATA[<p>Краткое <b>описание</b>.</p>]]></description>
      <pubDate>Wed, 29 Jul 2026 10:00:00 GMT</pubDate>
      <media:content url="https://example.com/image.jpg" type="image/jpeg"/>
    </item>
  </channel>
</rss>
""".encode("utf-8")


class FeedTests(unittest.TestCase):
    def test_reads_rss_article_and_image(self):
        response = Mock()
        response.content = RSS
        response.raise_for_status.return_value = None
        session = Mock()
        session.get.return_value = response
        source = {
            "name": "Тест",
            "rss_url": "https://example.com/rss",
            "enabled": True,
            "fetch_article": True,
            "include_any": [],
            "exclude": [],
        }

        articles = read_source(source, session, 10)

        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0].title, "Новая технология & рынок")
        self.assertEqual(articles[0].summary, "Краткое описание.")
        self.assertEqual(articles[0].url, "https://example.com/news/1")
        self.assertEqual(articles[0].image_url, "https://example.com/image.jpg")
        self.assertIsNotNone(articles[0].published_at)


if __name__ == "__main__":
    unittest.main()
