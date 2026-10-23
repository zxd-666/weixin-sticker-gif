#!/usr/bin/env python3
"""Convert a single scene video to an opaque, looping WeChat GIF without matting."""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from pathlib import Path

from album_workflow import MAX_GIF_BYTES, check_gif


def convert(video: Path, output: Path, *, start_seconds: float = 0,
            duration_seconds: float | None = None, max_bytes: int = MAX_GIF_BYTES) -> dict:
    video = video.expanduser().resolve(strict=True)
    output = output.expanduser().resolve()
    if not video.is_file() or video.stat().st_size == 0:
        raise ValueError("输入视频为空或不是文件")
    if output.exists():
        raise FileExistsError(f"拒绝覆盖现有 GIF：{output}")
    if start_seconds < 0 or duration_seconds is not None and duration_seconds <= 0:
        raise ValueError("起始时间须非负，时长须大于零")
    if not 1 <= max_bytes <= MAX_GIF_BYTES:
        raise ValueError(f"文件上限须在 1–{MAX_GIF_BYTES} 字节之间")
    output.parent.mkdir(parents=True, exist_ok=True)
    # Lower the palette before dropping frames. Do not change the requested
    # scene, infer a key color, or synthesize transparency.
    candidates = ((8, 160), (8, 128), (8, 96), (8, 64), (6, 96), (6, 64))
    with tempfile.TemporaryDirectory(prefix="weixin-scene-gif-", dir=output.parent) as temporary:
        target = Path(temporary) / "candidate.gif"
        for fps, colors in candidates:
            target.unlink(missing_ok=True)
            filters = (
                f"[0:v]fps={fps},crop=min(iw\\,ih):min(iw\\,ih),"
                "scale=240:240:flags=lanczos,split[a][b];"
                f"[a]palettegen=max_colors={colors}:reserve_transparent=0[p];"
                "[b][p]paletteuse=dither=bayer:bayer_scale=3"
            )
            command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
            if start_seconds:
                command.extend(["-ss", str(start_seconds)])
            command.extend(["-i", str(video)])
            if duration_seconds is not None:
                command.extend(["-t", str(duration_seconds)])
            command.extend(["-filter_complex", filters, "-loop", "0", str(target)])
            result = subprocess.run(command, capture_output=True, text=True, check=False)
            if result.returncode:
                raise RuntimeError(f"ffmpeg 转 GIF 失败：{result.stderr.strip()}")
            if target.stat().st_size > max_bytes:
                continue
            checked = check_gif(target, background_mode="opaque")
            target.replace(output)
            return {"video": str(video), "gif": str(output), "background_mode": "opaque",
                    "fps": fps, "max_colors": colors, "start_seconds": start_seconds,
                    "requested_duration_seconds": duration_seconds, **checked}
    raise ValueError("保留背景的视频在限定帧率/色数下仍超过 500KB；需选更短的有效动作窗口或重做更简洁的场景")


def main() -> int:
    parser = argparse.ArgumentParser(description="保留场景背景，直接把一段独立视频转为不透明 GIF")
    parser.add_argument("video", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--start-seconds", type=float, default=0)
    parser.add_argument("--duration-seconds", type=float)
    args = parser.parse_args()
    print(json.dumps(convert(args.video, args.output, start_seconds=args.start_seconds,
                             duration_seconds=args.duration_seconds), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
