from __future__ import annotations

import re
import unittest
from pathlib import Path
from urllib.parse import unquote

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
LINK = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")


class DocumentationTests(unittest.TestCase):
    def test_local_markdown_links_resolve(self) -> None:
        for document in [
            ROOT / "README.md",
            ROOT / "README.en.md",
            ROOT / "SKILL.md",
            *sorted((ROOT / "references").glob("*.md")),
        ]:
            text = document.read_text(encoding="utf-8")
            for raw in LINK.findall(text):
                target = raw.split("#", 1)[0].strip()
                if not target or "://" in target or target.startswith("mailto:"):
                    continue
                resolved = (document.parent / unquote(target)).resolve()
                with self.subTest(document=document.name, target=target):
                    self.assertTrue(resolved.exists(), f"broken local link: {document} -> {target}")

    def test_readme_previews_are_valid_looping_gifs(self) -> None:
        expected = {
            "docs/assets/recent-sticker-pack/fox-01.gif",
            "docs/assets/recent-sticker-pack/fox-05.gif",
            "docs/assets/recent-sticker-pack/fox-06.gif",
        }
        for document in (ROOT / "README.md", ROOT / "README.en.md"):
            text = document.read_text(encoding="utf-8")
            image_refs = set(re.findall(r'<img src="(docs/assets/recent-sticker-pack/[^\"]+\.gif)"', text))
            self.assertEqual(image_refs, expected)
        for path in expected:
            with self.subTest(path=path), Image.open(ROOT / path) as image:
                self.assertEqual(image.size, (240, 240))
                self.assertGreater(image.n_frames, 1)
                self.assertEqual(image.info.get("loop"), 0)
                self.assertLessEqual((ROOT / path).stat().st_size, 500_000)


if __name__ == "__main__":
    unittest.main()
