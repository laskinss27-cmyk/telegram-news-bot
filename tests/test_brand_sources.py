import unittest
from datetime import datetime, timezone

from bs4 import BeautifulSoup

from newsbot.brand_sources import (
    _hydrate_ctv,
    _read_ctv,
    _read_dahua,
    _read_shelly_sitemap,
    _read_tiandy,
)
from newsbot.models import Article
from unittest.mock import Mock


class BrandSourceTests(unittest.TestCase):
    def test_ctv_uses_only_configured_number_of_top_cards(self):
        soup = BeautifulSoup(
            """
            <a class="new-preview" href="/news/first/">
              NEW CTV ProCam Новая камера
            </a>
            <a class="new-preview" href="/news/second/">Вторая новость</a>
            """,
            "html.parser",
        )
        source = {
            "name": "CTV",
            "page_url": "https://ctvcctv.ru/news/",
            "max_entries": 1,
        }
        now = datetime(2026, 7, 30, tzinfo=timezone.utc)

        articles = _read_ctv(source, soup, now)

        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0].title, "CTV ProCam Новая камера")
        self.assertEqual(articles[0].published_at, now)

    def test_ctv_detail_supplies_real_date_summary_and_image(self):
        response = Mock()
        response.text = """
        <main class="single-news">
          <div>15/07/2026</div>
          <p>Описание новой линейки видеодомофонов длиной больше сорока символов.</p>
          <img src="/uploads/intercom.jpg">
        </main>
        """
        response.raise_for_status.return_value = None
        session = Mock()
        session.get.return_value = response
        article = Article(
            source="CTV",
            title="Новая линейка",
            url="https://ctvcctv.ru/news/new/",
        )

        _hydrate_ctv(article, session, 10)

        self.assertEqual(article.published_at.day, 15)
        self.assertIn("Описание новой линейки", article.summary)
        self.assertEqual(
            article.image_url, "https://ctvcctv.ru/uploads/intercom.jpg"
        )

    def test_dahua_reads_card_fields(self):
        soup = BeautifulSoup(
            """
            <a href="/newsEvents/pressRelease/123">
              <img src="/camera.jpg">
              <h3>Dahua launches a video camera</h3>
              <p class="on">July 16, 2026 / New intelligent monitoring.</p>
            </a>
            """,
            "html.parser",
        )
        source = {
            "name": "Dahua",
            "page_url": "https://previous.dahuasecurity.com/newsEvents/pressRelease",
            "max_entries": 20,
        }

        articles = _read_dahua(source, soup, datetime.now(timezone.utc))

        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0].published_at.year, 2026)
        self.assertEqual(
            articles[0].image_url,
            "https://previous.dahuasecurity.com/camera.jpg",
        )

    def test_tiandy_reads_listing_card(self):
        soup = BeautifulSoup(
            """
            <div class="newsBox">
              <div class="imgBox"><img src="//cdn.example/cam.jpg"><span class="time">2026-06-29</span></div>
              <p class="newsTitle"><a href="/news/camera-1.html">New camera</a></p>
              <p class="newsContent">A security camera announcement.</p>
            </div>
            """,
            "html.parser",
        )
        source = {
            "name": "Tiandy",
            "page_url": "https://en.tiandy.com/news/",
            "max_entries": 30,
        }

        articles = _read_tiandy(source, soup, datetime.now(timezone.utc))

        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0].published_at.month, 6)
        self.assertEqual(articles[0].image_url, "https://cdn.example/cam.jpg")

    def test_shelly_reads_media_kit_sitemap(self):
        xml = b"""<?xml version="1.0" encoding="UTF-8"?>
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
          <url>
            <loc>https://www.shelly.com/blogs/media-kit/new-smart-relay</loc>
            <lastmod>2026-07-30T08:00:00+00:00</lastmod>
          </url>
          <url>
            <loc>https://www.shelly.com/products/not-a-post</loc>
            <lastmod>2026-07-30T09:00:00+00:00</lastmod>
          </url>
        </urlset>
        """
        source = {
            "name": "Shelly",
            "max_entries": 20,
            "url_contains": "/blogs/media-kit/",
        }

        articles = _read_shelly_sitemap(source, xml)

        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0].title, "New Smart Relay")
        self.assertTrue(articles[0].source_settings["prefer_page_title"])


if __name__ == "__main__":
    unittest.main()
