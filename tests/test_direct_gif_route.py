"""Offline checks for direct Image API GIF requests and final GIF normalization."""

from __future__ import annotations

import base64
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from album_workflow import check_gif  # noqa: E402
from direct_gif_to_sticker import convert  # noqa: E402
from generate_image_gif import generate, request_payload  # noqa: E402


def sample_gif(size: int = 414, *, transparent: bool = False) -> bytes:
    frames = []
    for x in (10, 35, 60):
        image = Image.new("RGBA" if transparent else "RGB", (size, size),
                          (0, 0, 0, 0) if transparent else "#e8caaa")
        for y in range(30, 90):
            for column in range(x, x + 20):
                image.putpixel((column, y), (255, 90, 20, 255) if transparent else (255, 90, 20))
        frames.append(image)
    buffer = io.BytesIO()
    frames[0].save(buffer, format="GIF", save_all=True, append_images=frames[1:],
                   duration=200, loop=0)
    return buffer.getvalue()


class DirectGifRouteTests(unittest.TestCase):
    def test_api_payload_is_explicit_gif_and_cost_gate_prevents_request(self) -> None:
        payload = request_payload("wave", model="gpt-image-2.6-sunburst",
                                  frame_count=9, frame_duration_ms=200,
                                  size="auto", quality="medium")
        self.assertEqual(payload["output_format"], "gif")
        self.assertEqual(payload["frame_count"], 9)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            prompt = root / "prompt.txt"
            prompt.write_text("wave", encoding="utf-8")
            with patch("generate_image_gif.urllib.request.urlopen") as urlopen:
                with self.assertRaisesRegex(ValueError, "费用范围"):
                    generate(prompt, root / "source.gif")
                urlopen.assert_not_called()

    def test_api_rejects_static_gif_and_keeps_output_absent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            prompt = root / "prompt.txt"
            prompt.write_text("wave", encoding="utf-8")
            still = io.BytesIO()
            Image.new("RGB", (64, 64), "red").save(still, format="GIF")
            response = io.BytesIO(json.dumps({"data": [{"b64_json": base64.b64encode(still.getvalue()).decode()}]}).encode())
            with patch.dict("generate_image_gif.os.environ", {"OPENAI_API_KEY": "test-key"}), \
                    patch("generate_image_gif.urllib.request.urlopen", return_value=response):
                with self.assertRaisesRegex(ValueError, "没有实际动画帧"):
                    generate(prompt, root / "source.gif", cost_confirmed=True)
            self.assertFalse((root / "source.gif").exists())

    def test_api_saves_real_gif_and_key_free_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            prompt = root / "prompt.txt"
            prompt.write_text("wave", encoding="utf-8")
            raw = sample_gif(240)
            response = io.BytesIO(json.dumps({"data": [{"b64_json": base64.b64encode(raw).decode()}],
                                              "usage": {"output_tokens": 42}}).encode())
            with patch.dict("generate_image_gif.os.environ", {"OPENAI_API_KEY": "test-key"}), \
                    patch("generate_image_gif.urllib.request.urlopen", return_value=response):
                result = generate(prompt, root / "source.gif", cost_confirmed=True)
            self.assertEqual((root / "source.gif").read_bytes(), raw)
            receipt = (root / "source.receipt.json").read_text(encoding="utf-8")
            self.assertNotIn("test-key", receipt)
            self.assertEqual(json.loads(receipt)["usage"]["output_tokens"], 42)
            self.assertEqual(result["receipt"], str((root / "source.receipt.json").resolve()))

    def test_opaque_direct_gif_scales_without_video(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.gif"
            source.write_bytes(sample_gif())
            output = root / "final.gif"
            report = convert(source, output)
            self.assertEqual(report["background_mode"], "opaque")
            self.assertEqual(report["frames"], 3)
            self.assertLessEqual(report["bytes"], 500_000)
            self.assertEqual(check_gif(output, background_mode="opaque")["frames"], 3)
            with Image.open(output) as image:
                self.assertEqual(image.size, (240, 240))

    def test_opaque_route_rejects_actual_transparency(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.gif"
            source.write_bytes(sample_gif(240, transparent=True))
            with self.assertRaisesRegex(ValueError, "实际透明像素"):
                convert(source, root / "final.gif")


if __name__ == "__main__":
    unittest.main()
