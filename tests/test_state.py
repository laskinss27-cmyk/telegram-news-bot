import tempfile
import unittest
from pathlib import Path

from newsbot.models import Article
from newsbot.state import State


class StateTests(unittest.TestCase):
    def test_persists_and_detects_tracking_variant(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            state = State(path)
            state.add(
                Article(
                    source="Сайт",
                    title="Важная новость дня",
                    url="https://example.com/story?utm_source=rss",
                )
            )
            state.save()

            restored = State(path)
            restored.load()
            self.assertTrue(
                restored.contains(
                    Article(
                        source="Другой сайт",
                        title="Другой заголовок",
                        url="https://example.com/story",
                    )
                )
            )


if __name__ == "__main__":
    unittest.main()
