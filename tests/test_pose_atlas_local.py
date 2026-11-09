"""An approved pose atlas exports an animated transparent sticker without video."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from pose_atlas_local import render  # noqa: E402
from subject_anchor import approve  # noqa: E402


class PoseAtlasLocalTests(unittest.TestCase):
    def make_inputs(self, root: Path) -> tuple[Path, Path]:
        anchor = root / "anchor.png"
        Image.new("RGBA", (128, 128), (0, 0, 0, 0)).save(anchor)
        approval = root / "subject-anchor-approval.json"
        approve(anchor, approval, confirmed_by_user=True)
        atlas = Image.new("RGBA", (257, 257), (0, 0, 0, 0))
        draw = ImageDraw.Draw(atlas)
        for index in range(4):
            x, y = (index % 2) * 128, (index // 2) * 128
            draw.ellipse((x + 45, y + 25, x + 85, y + 70), fill="#df963c")
            draw.rectangle((x + 48, y + 68, x + 82, y + 108), fill="#24633f")
            draw.ellipse((x + 78, y + 40 - 7 * index, x + 105, y + 55 - 7 * index),
                         fill="#df963c")
        path = root / "atlas.png"
        atlas.save(path)
        return path, approval

    def test_atlas_exports_valid_gif_and_hash_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, approval = self.make_inputs(root)
            output = root / "01.gif"
            report = render(source=source, output=output, approval=approval,
                            mode="atlas", grid=2, order=[0, 1, 2, 3, 2, 1])
            self.assertEqual(report["frames"], 6)
            self.assertLess(report["bytes"], 500_000)
            with Image.open(output) as image:
                self.assertEqual(image.size, (240, 240))
                self.assertEqual(image.info["loop"], 0)
            receipt = json.loads(output.with_suffix(".receipt.json").read_text())
            self.assertEqual(receipt["source_sha256"], report["source_sha256"])
            with self.assertRaises(FileExistsError):
                render(source=source, output=output, approval=approval,
                       mode="atlas", grid=2, order=[0, 1, 2, 3, 2, 1])

    def test_rejects_held_pose_and_opaque_atlas_before_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, approval = self.make_inputs(root)
            output = root / "01.gif"
            with self.assertRaisesRegex(ValueError, "停顿"):
                render(source=source, output=output, approval=approval,
                       mode="atlas", grid=2, order=[0, 1, 2, 2, 3, 1])
            self.assertFalse(output.exists())
            Image.new("RGB", (256, 256), "white").save(source)
            with self.assertRaisesRegex(ValueError, "透明像素"):
                render(source=source, output=output, approval=approval,
                       mode="atlas", grid=2, order=[0, 1, 2, 3, 2, 1])
            self.assertFalse(output.exists())

    def test_explicit_action_hold_is_recorded(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, approval = self.make_inputs(root)
            report = render(source=source, output=root / "jump.gif", approval=approval,
                            mode="atlas", grid=2, order=[0, 1, 2, 2, 3, 1],
                            allow_holds=True)
            self.assertTrue(report["allow_holds"])
            self.assertTrue(any("有意停留" in warning for warning in report["warnings"]))


if __name__ == "__main__":
    unittest.main()
