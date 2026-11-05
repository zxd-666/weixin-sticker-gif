#!/usr/bin/env python3
"""Normalize a direct opaque GIF to the WeChat sticker size and byte limit."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageSequence

from album_workflow import MAX_GIF_BYTES, check_gif


def convert(source: Path, output: Path, *, background_mode: str = "opaque") -> dict:
    source = source.expanduser().resolve(strict=True)
    output = output.expanduser().resolve()
    if background_mode not in {"opaque", "transparent"}:
        raise ValueError("背景模式须为 opaque 或 transparent")
    if source == output or output.exists():
        raise FileExistsError(f"拒绝覆盖输入或已有 GIF：{output}")
    with Image.open(source) as image:
        if image.format != "GIF" or image.n_frames < 2:
            raise ValueError("输入须为真正的多帧 GIF")
        if background_mode == "opaque" and any(
            frame.convert("RGBA").getchannel("A").getextrema()[0] != 255
            for frame in ImageSequence.Iterator(image)
        ):
            raise ValueError("保留场景的原始 GIF 含实际透明像素，不能悄悄铺底")
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        checked = check_gif(source, background_mode=background_mode)
    except ValueError:
        checked = None
    if checked:
        shutil.copyfile(source, output)
        return {"source": str(source), "gif": str(output), "method": "copy",
                "background_mode": background_mode, **checked}
    if background_mode == "transparent":
        raise ValueError("透明直出 GIF 未满足微信规格；不能通过不透明调色板压缩，须另行处理或回退视频路线")
    candidates = (160, 128, 96, 64)
    with tempfile.TemporaryDirectory(prefix="direct-gif-", dir=output.parent) as temporary:
        candidate = Path(temporary) / "candidate.gif"
        for colors in candidates:
            filters = ("[0:v]crop=min(iw\\,ih):min(iw\\,ih),"
                       "scale=240:240:flags=lanczos,split[a][b];"
                       f"[a]palettegen=max_colors={colors}:reserve_transparent=0[p];"
                       "[b][p]paletteuse=dither=bayer:bayer_scale=4")
            result = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                                     "-i", str(source), "-filter_complex", filters,
                                     "-fps_mode", "vfr", "-loop", "0", str(candidate)],
                                    capture_output=True, text=True, check=False)
            if result.returncode:
                raise RuntimeError(f"ffmpeg 处理直出 GIF 失败：{result.stderr.strip()}")
            if candidate.stat().st_size <= MAX_GIF_BYTES:
                checked = check_gif(candidate, background_mode="opaque")
                candidate.replace(output)
                return {"source": str(source), "gif": str(output), "method": "palette-scale",
                        "max_colors": colors, "background_mode": "opaque", **checked}
    raise ValueError("直出 GIF 在 240×240 和有限色数下仍超过 500000 字节；需简化场景或重新生成")


def main() -> int:
    parser = argparse.ArgumentParser(description="验收并缩放 Images 2.6 直出 GIF")
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--background-mode", choices=["opaque", "transparent"], default="opaque")
    args = parser.parse_args()
    print(json.dumps(convert(args.source, args.output, background_mode=args.background_mode),
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
