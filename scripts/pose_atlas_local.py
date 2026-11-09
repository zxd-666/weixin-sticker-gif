#!/usr/bin/env python3
"""Render a transparent 240px sticker from an approved anchor or pose atlas.

Image generation happens outside this script. One atlas contains consecutive
poses for one sticker; the script never calls an image or video provider.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import tempfile
from pathlib import Path

from PIL import Image, ImageChops, ImageSequence

from album_workflow import check_gif
from animation_export import encode_gif_images
from subject_anchor import verify_approval

SIZE = 240
FPS = 8
MAX_SOURCE_PIXELS = 64_000_000


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def clean_alpha(image: Image.Image, cutoff: int = 48) -> Image.Image:
    rgba = image.convert("RGBA")
    rgba.putalpha(rgba.getchannel("A").point(lambda value: value if value >= cutoff else 0))
    return rgba


def visible_box(image: Image.Image) -> tuple[int, int, int, int]:
    alpha = image.getchannel("A")
    if alpha.getextrema()[0] == 255:
        raise ValueError("输入没有真实透明像素；不能把白底或棋盘格当作 Alpha")
    box = alpha.point(lambda value: 255 if value >= 128 else 0).getbbox()
    if box is None:
        raise ValueError("输入没有可见主体")
    return box


def fit_pose(pose: Image.Image, union: tuple[int, int, int, int]) -> Image.Image:
    art = pose.crop(union)
    ratio = min(210 / art.width, 210 / art.height)
    art = art.resize((max(1, round(art.width * ratio)), max(1, round(art.height * ratio))),
                     Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (SIZE, SIZE))
    canvas.alpha_composite(art, ((SIZE - art.width) // 2, (SIZE - art.height) // 2))
    return canvas


def atlas_frames(source: Image.Image, grid: int, order: list[int],
                 allow_holds: bool) -> tuple[list[Image.Image], list[str]]:
    if grid not in (2, 3, 4) or source.width != source.height:
        raise ValueError("姿态图集须为等格的正方形 2×2、3×3 或 4×4")
    if (len(order) < 3 or len(order) > 48 or any(not 0 <= item < grid * grid for item in order)
            or len(set(order)) < 3):
        raise ValueError("帧顺序须包含至少三个不同姿态，且总帧数为 3–48")
    holds = [index + 1 for index, (left, right) in enumerate(zip(order, order[1:]))
             if left == right]
    if holds and not allow_holds:
        raise ValueError("相邻重复姿态会造成停顿；仅有意蓄力、峰值或落地停留可用 --allow-holds")
    if order[0] == order[-1]:
        raise ValueError("循环首尾重复姿态会造成额外停顿；请调整 --order")
    cell_size = math.ceil(source.width / grid)
    cells = []
    boxes = []
    warnings = []
    if holds:
        warnings.append(f"有意停留位于相邻帧 {holds}；须逐处检查是否符合动作节奏")
    for index in range(grid * grid):
        row, column = divmod(index, grid)
        bounds = (column * source.width // grid, row * source.height // grid,
                  (column + 1) * source.width // grid, (row + 1) * source.height // grid)
        tile = clean_alpha(source.crop(bounds))
        cell = Image.new("RGBA", (cell_size, cell_size))
        cell.alpha_composite(tile)
        box = visible_box(cell)
        cells.append(cell)
        boxes.append(box)
        margin = min(box[0], box[1], cell_size - box[2], cell_size - box[3])
        if margin < cell_size * 0.04:
            warnings.append(f"图格 {index} 主体接近边界，需检查鬃毛、手脚或道具是否被裁切")
    union = (min(box[0] for box in boxes), min(box[1] for box in boxes),
             max(box[2] for box in boxes), max(box[3] for box in boxes))
    poses = [fit_pose(cell, union) for cell in cells]
    return [poses[index] for index in order], warnings


def light_frames(source: Image.Image) -> list[Image.Image]:
    art = clean_alpha(source)
    box = visible_box(art)
    art = art.crop(box)
    ratio = min(204 / art.width, 204 / art.height)
    art = art.resize((round(art.width * ratio), round(art.height * ratio)), Image.Resampling.LANCZOS)
    frames = []
    for index in range(10):
        # Every frame step moves 2 px, including the final-to-first step.
        rise = 2 * min(index, 10 - index)
        width_delta = 2 if rise <= 2 else (1 if rise <= 6 else 0)
        height_delta = -2 if rise <= 2 else (0 if rise <= 6 else 1)
        moving = art.resize((art.width + width_delta, art.height + height_delta),
                            Image.Resampling.BICUBIC)
        frame = Image.new("RGBA", (SIZE, SIZE))
        frame.alpha_composite(moving, ((SIZE - moving.width) // 2,
                                       SIZE - 14 - moving.height - rise))
        frames.append(frame)
    return frames


def check_animation(path: Path, expected_frames: int, *, allow_holds: bool = False) -> dict:
    checked = check_gif(path, background_mode="transparent")
    if checked["frames"] != expected_frames and not (allow_holds and 2 <= checked["frames"] < expected_frames):
        raise ValueError("GIF 编码后丢失帧；检查源帧是否完全重复")
    with Image.open(path) as image:
        frames = [frame.convert("RGBA") for frame in ImageSequence.Iterator(image)]
    if not allow_holds and any(ImageChops.difference(left, right).getbbox() is None
                               for left, right in zip(frames, frames[1:])):
        raise ValueError("GIF 有相邻重复帧，会出现可见停顿")
    if ImageChops.difference(frames[-1], frames[0]).getbbox() is None:
        raise ValueError("GIF 循环首尾完全重复，会出现可见停顿")
    return checked


def render(*, source: Path, output: Path, approval: Path, mode: str,
           grid: int | None = None, order: list[int] | None = None,
           fps: int = FPS, allow_holds: bool = False) -> dict:
    source = source.expanduser().resolve(strict=True)
    approval = approval.expanduser().resolve(strict=True)
    output = output.expanduser().resolve()
    if output.exists() or output.with_suffix(".receipt.json").exists():
        raise FileExistsError(f"拒绝覆盖已有输出：{output}")
    if not 4 <= fps <= 20:
        raise ValueError("fps 须为 4–20")
    anchor = verify_approval(approval)
    with Image.open(source) as opened:
        if opened.width * opened.height > MAX_SOURCE_PIXELS:
            raise ValueError("输入图片超过 6400 万像素")
        image = opened.convert("RGBA")
    if mode == "atlas":
        if grid is None or order is None:
            raise ValueError("姿态图集路线须提供 --grid 和 --order")
        frames, warnings = atlas_frames(image, grid, order, allow_holds)
    elif mode == "light":
        if grid is not None or order is not None or allow_holds:
            raise ValueError("轻动效路线不使用 --grid、--order 或 --allow-holds")
        frames, warnings = light_frames(image), []
    else:
        raise ValueError("mode 须为 atlas 或 light")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="pose-atlas-local-", dir=output.parent) as temp:
        candidate = Path(temp) / "candidate.gif"
        encode_gif_images(frames, candidate, fps, max_colors=96, alpha_threshold=128)
        checked = check_animation(candidate, len(frames), allow_holds=allow_holds)
        receipt = {"version": 1, "mode": f"{mode}-local", "source": str(source),
                   "source_sha256": sha256(source), "anchor_sha256": anchor["sha256"],
                   "approval": str(approval), "approval_sha256": sha256(approval),
                   "grid": grid, "order": order, "fps": fps, "allow_holds": allow_holds,
                   "warnings": warnings,
                   "gif": str(output), **checked}
        # Complete validation before publishing either output.
        output.write_bytes(candidate.read_bytes())
        output.with_suffix(".receipt.json").write_text(
            json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description="已确认主体的姿态图集／轻动效本地 GIF 导出")
    parser.add_argument("--source", type=Path, required=True, help="透明姿态图集，或轻动效单张透明图")
    parser.add_argument("--output", type=Path, required=True, help="最终 240×240 GIF")
    parser.add_argument("--anchor-approval", type=Path, required=True)
    parser.add_argument("--mode", choices=["atlas", "light"], required=True)
    parser.add_argument("--grid", type=int, choices=[2, 3, 4], help="atlas 模式的 N×N 格数")
    parser.add_argument("--order", help="atlas 模式按阅读顺序从 0 编号，逗号分隔播放帧，如 0,1,2,3,2,1")
    parser.add_argument("--allow-holds", action="store_true", help="仅对有意蓄力、峰值或落地停留允许相邻重复帧")
    parser.add_argument("--fps", type=int, default=FPS)
    args = parser.parse_args()
    order = [int(item.strip()) for item in args.order.split(",")] if args.order else None
    result = render(source=args.source, output=args.output, approval=args.anchor_approval,
                    mode=args.mode, grid=args.grid, order=order, fps=args.fps,
                    allow_holds=args.allow_holds)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
