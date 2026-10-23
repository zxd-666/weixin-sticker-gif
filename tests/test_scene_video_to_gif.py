from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageSequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from album_workflow import check_gif  # noqa: E402
from scene_video_to_gif import convert  # noqa: E402


@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg is required")
class SceneVideoToGifTests(unittest.TestCase):
    def test_preserves_background_as_opaque_looping_gif(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = Image.new("RGB", (128, 96), (42, 105, 170))
            second = Image.new("RGB", (128, 96), (54, 120, 170))
            first.save(root / "frame-01.png")
            second.save(root / "frame-02.png")
            video = root / "scene.mp4"
            result = subprocess.run(
                ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-framerate", "4",
                 "-i", str(root / "frame-%02d.png"), "-c:v", "libx264", "-pix_fmt", "yuv420p",
                 str(video)], capture_output=True, text=True, check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            output = root / "scene.gif"
            report = convert(video, output)
            self.assertEqual(report["background_mode"], "opaque")
            self.assertLessEqual(report["bytes"], 500_000)
            self.assertGreaterEqual(report["frames"], 2)
            self.assertEqual(check_gif(output, background_mode="opaque")["sha256"], report["sha256"])
            with Image.open(output) as gif:
                self.assertEqual(gif.size, (240, 240))
                self.assertEqual(gif.info["loop"], 0)
                for frame in ImageSequence.Iterator(gif):
                    self.assertEqual(frame.convert("RGBA").getchannel("A").getextrema(), (255, 255))
