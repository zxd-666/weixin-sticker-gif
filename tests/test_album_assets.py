"""File-level acceptance checks for standalone album submission images."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from album_assets import prepare_image, validate_assets  # noqa: E402


class AlbumAssetTests(unittest.TestCase):
    def test_prepare_requires_real_alpha_and_produces_exact_sizes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.png"
            output = root / "附加素材" / "表情封面.png"
            Image.new("RGB", (600, 600), "white").save(source)
            with self.assertRaisesRegex(ValueError, "真实透明"):
                prepare_image(source, output, "表情封面")
            self.assertFalse(output.exists())
            image = Image.new("RGBA", (600, 600), (0, 0, 0, 0))
            image.paste((200, 30, 50, 255), (100, 100, 500, 500))
            image.save(source)
            prepare_image(source, output, "表情封面")
            with Image.open(output) as prepared:
                self.assertEqual(prepared.size, (240, 240))
                self.assertEqual(prepared.getpixel((0, 0))[3], 0)
                self.assertGreater(prepared.getpixel((120, 120))[3], 0)
            with self.assertRaises(FileExistsError):
                prepare_image(source, output, "表情封面")

    def test_rejects_partial_reward_pair_and_transparent_banner(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            assets = root / "附加素材"
            assets.mkdir()
            Image.new("RGBA", (750, 400), (0, 0, 0, 0)).save(assets / "详情页横幅.png")
            for name, size in (("表情封面", (240, 240)), ("聊天页图标", (50, 50))):
                image = Image.new("RGBA", size, (0, 0, 0, 0))
                image.putpixel((size[0] // 2, size[1] // 2), (255, 0, 0, 255))
                image.save(assets / f"{name}.png")
            Image.new("RGB", (750, 560), "pink").save(assets / "赞赏引导图.png")
            with self.assertRaisesRegex(ValueError, "不透明"):
                validate_assets(assets)
            Image.new("RGB", (750, 400), "pink").save(assets / "详情页横幅.png")
            with self.assertRaisesRegex(ValueError, "赞赏致谢图"):
                validate_assets(assets)
            with self.assertRaisesRegex(ValueError, "赞赏引导图"):
                validate_assets(assets, include_rewards=False)


if __name__ == "__main__":
    unittest.main()
