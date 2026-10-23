#!/usr/bin/env python3
"""Prepare and validate a dynamic album's non-sticker submission images."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError


SIZES = {
    "详情页横幅": (750, 400),
    "表情封面": (240, 240),
    "聊天页图标": (50, 50),
    "赞赏引导图": (750, 560),
    "赞赏致谢图": (750, 750),
}
MODES = {
    "banner": "详情页横幅", "cover": "表情封面", "icon": "聊天页图标",
    "reward-guide": "赞赏引导图", "reward-thanks": "赞赏致谢图",
}
REWARD_ROLES = ("赞赏引导图", "赞赏致谢图")
FORMATS = {".png": "PNG", ".jpg": "JPEG", ".jpeg": "JPEG", ".gif": "GIF"}
COMPRESSION_THRESHOLD = 500 * 1024
ICON_LIMIT = 100 * 1024


def image_paths(directory: Path, role: str) -> list[Path]:
    return sorted(path for path in directory.iterdir() if path.is_file() and path.stem == role)


def actual_transparency(image: Image.Image) -> bool:
    minimum, maximum = image.convert("RGBA").getchannel("A").getextrema()
    return minimum == 0 and maximum > 0


def any_transparency(image: Image.Image) -> bool:
    return image.convert("RGBA").getchannel("A").getextrema()[0] < 255


def validate_assets(directory: Path, *, include_rewards: bool = True) -> tuple[list[Path], list[str]]:
    if not directory.is_dir():
        raise ValueError(f"附加素材目录不存在：{directory}")
    selected: list[Path] = []
    warnings: list[str] = []
    roles = ("详情页横幅", "表情封面", "聊天页图标", *REWARD_ROLES)
    allowed = set()
    for role in roles:
        paths = image_paths(directory, role)
        required = role not in REWARD_ROLES or include_rewards
        if len(paths) != int(required):
            raise ValueError(f"{role} 须有 {int(required)} 张，实际 {len(paths)} 张")
        if not paths:
            continue
        path = paths[0]
        allowed.add(path.name)
        permitted = {"PNG", "JPEG"} if role == "详情页横幅" else (
            {"PNG"} if role in {"表情封面", "聊天页图标"} else {"PNG", "JPEG", "GIF"})
        try:
            with Image.open(path) as image:
                if (image.format not in permitted or FORMATS.get(path.suffix.lower()) != image.format
                        or image.size != SIZES[role] or getattr(image, "n_frames", 1) != 1):
                    raise ValueError(f"{role} 格式、扩展名、尺寸或帧数不合格：{path}")
                if role == "详情页横幅" and any_transparency(image):
                    raise ValueError("详情页横幅必须是不透明背景")
                if role in {"表情封面", "聊天页图标"} and not actual_transparency(image):
                    raise ValueError(f"{role} 缺少真实透明像素")
        except (OSError, UnidentifiedImageError) as error:
            raise ValueError(f"无法读取{role}：{path}") from error
        if role == "聊天页图标" and path.stat().st_size >= ICON_LIMIT:
            raise ValueError("聊天页图标必须小于 100KB")
        if role != "聊天页图标" and path.stat().st_size > COMPRESSION_THRESHOLD:
            warnings.append(f"{role} 超过 500KB，平台可能再次压缩")
        selected.append(path)
    extras = {path.name for path in directory.iterdir() if not path.name.startswith(".")} - allowed
    if extras:
        raise ValueError(f"附加素材目录含未识别文件：{sorted(extras)}")
    return selected, warnings


def prepare_image(source: Path, output: Path, role: str) -> Path:
    if role not in SIZES:
        raise ValueError(f"未知素材类型：{role}")
    source = source.expanduser().resolve(strict=True)
    output = output.expanduser().resolve()
    if output.name != f"{role}.png":
        raise ValueError(f"输出文件须命名为 {role}.png")
    if output.exists():
        raise FileExistsError(f"拒绝覆盖已有素材：{output}")
    with Image.open(source) as image:
        if getattr(image, "n_frames", 1) != 1:
            raise ValueError("附加素材源图须为单帧")
        if role in {"表情封面", "聊天页图标"}:
            if not actual_transparency(image):
                raise ValueError(f"{role} 源图须有真实透明背景")
            foreground = image.convert("RGBA")
            foreground.thumbnail(SIZES[role], Image.Resampling.LANCZOS)
            result = Image.new("RGBA", SIZES[role], (0, 0, 0, 0))
            result.alpha_composite(foreground, ((result.width - foreground.width) // 2,
                                                (result.height - foreground.height) // 2))
        else:
            if role == "详情页横幅" and any_transparency(image):
                raise ValueError("详情页横幅源图须为不透明背景")
            result = ImageOps.fit(image.convert("RGB" if role == "详情页横幅" else "RGBA"),
                                  SIZES[role], Image.Resampling.LANCZOS)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.stem}-{os.getpid()}.png")
    try:
        result.save(temporary, format="PNG", optimize=True, compress_level=9)
        with Image.open(temporary) as saved:
            if role in {"表情封面", "聊天页图标"} and not actual_transparency(saved):
                raise ValueError(f"{role} 导出后没有真实透明像素")
        if role == "聊天页图标" and temporary.stat().st_size >= ICON_LIMIT:
            raise ValueError("聊天页图标导出后不小于 100KB")
        temporary.rename(output)
    finally:
        temporary.unlink(missing_ok=True)
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("--source", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--role", choices=tuple(MODES), required=True)
    p = sub.add_parser("validate")
    p.add_argument("--directory", type=Path, required=True)
    p.add_argument("--no-reward", action="store_true")
    args = parser.parse_args()
    if args.command == "prepare":
        print(prepare_image(args.source, args.output, MODES[args.role]))
    else:
        paths, warnings = validate_assets(args.directory, include_rewards=not args.no_reward)
        print(f"OK: {len(paths)} 张附加素材通过文件检查")
        for warning in warnings:
            print(f"WARNING: {warning}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
