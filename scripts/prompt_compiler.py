#!/usr/bin/env python3
"""Compile internally consistent static-sheet and grid-video prompts."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


DEFAULT_KEY_COLOR = "#00FF00"


def load_layout(path: Path, allow_low_confidence: bool = False) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    detected = data.get("detected_layout", data)
    columns = int(detected["columns"])
    rows = int(detected["rows"])
    count = columns * rows
    if not (1 <= columns <= 12 and 1 <= rows <= 12 and count <= 48):
        raise ValueError("detected layout must be at most 48 cells with dimensions from 1 to 12")
    if int(detected.get("count", count)) != count:
        raise ValueError("layout count must equal columns * rows")
    confidence = detected.get("confidence")
    if confidence is not None and float(confidence) < 0.75 and not allow_low_confidence:
        raise ValueError("layout confidence is below 0.75; confirm an override or pass --allow-low-confidence")
    return {"columns": columns, "rows": rows, "count": count, "confidence": confidence}


def load_tile_plan(path: Path | None, count: int, allow_generic: bool = False) -> list[dict]:
    if path is None:
        if not allow_generic:
            raise ValueError(
                "a per-cell --tile-plan is required; use --allow-generic-motions only for an intentional fallback"
            )
        return [
            {
                "id": f"{index:02d}",
                "motion": "根据该格现有表情和姿势做一个幅度很小的独立动作",
                "loop": "return-to-start",
                "amplitude": "small",
            }
            for index in range(1, count + 1)
        ]
    data = json.loads(path.read_text(encoding="utf-8"))
    tiles = data.get("tiles", data)
    if not isinstance(tiles, list):
        raise ValueError("tile plan must be an array or an object containing a tiles array")
    if len(tiles) != count:
        raise ValueError(f"tile plan has {len(tiles)} items; detected layout requires {count}")
    normalized = []
    for index, tile in enumerate(tiles, start=1):
        if not isinstance(tile, dict):
            raise ValueError(f"tile {index} must be an object")
        motion = tile.get("motion")
        if not isinstance(motion, str) or not motion.strip() or len(motion) > 200:
            raise ValueError(f"tile {index} motion must be 1-200 characters")
        tile_id = str(tile.get("id", f"{index:02d}"))
        if tile_id != f"{index:02d}":
            raise ValueError(f"tile {index} id must be {index:02d}")
        normalized.append({**tile, "id": tile_id, "motion": motion.strip()})
    return normalized


def validate_key_color(value: str | None) -> str | None:
    if value is None:
        return None
    if not re.fullmatch(r"#[0-9A-Fa-f]{6}", value):
        raise ValueError("key color must use #RRGGBB notation")
    red = int(value[1:3], 16)
    green = int(value[3:5], 16)
    blue = int(value[5:7], 16)
    chroma = max(red, green, blue) - min(red, green, blue)
    luma = 0.299 * red + 0.587 * green + 0.114 * blue
    if chroma < 40 and (luma <= 40 or luma >= 215):
        raise ValueError("key color must contrast with the subject; do not use a near-black or near-white plate")
    return value


def compile_prompts(
    layout: dict, tiles: list[dict], key_color: str | None, text_policy: dict | None = None,
    background_mode: str = "transparent", scene_prompt: str | None = None,
) -> dict:
    if background_mode not in {"transparent", "opaque"}:
        raise ValueError("background_mode must be transparent or opaque")
    if background_mode == "opaque" and layout["count"] != 1:
        raise ValueError("保留背景的图生视频路线当前只支持独立 1×1 首帧")
    scene_prompt = scene_prompt.strip() if scene_prompt else None
    if scene_prompt and background_mode != "opaque":
        raise ValueError("场景提示词只适用于保留背景的任务")
    columns, rows, count = layout["columns"], layout["rows"], layout["count"]
    grid = f"{columns} 列 × {rows} 行"
    sheet_name = "九宫格" if (columns, rows) == (3, 3) else f"{columns}×{rows} 网格"
    cells_name = "九格" if count == 9 else f"{count} 格"
    motions = "\n".join(
        f"- 第 {index:02d} 格：{tile['motion']}；幅度 {tile.get('amplitude', 'small')}；循环 {tile.get('loop', 'return-to-start')}。"
        for index, tile in enumerate(tiles, start=1)
    )
    background = (
        (f"围绕已确认的主体生成场景：{scene_prompt}。场景从首帧起完整、自然且连续，主体身份和已有道具不变；"
         "不要沿用输入图像的空白、纯色或透明底，不要换成绿幕或棋盘格。"
         if scene_prompt else
         "保留输入图像已有的场景；若输入只有主体或纯色底，根据主题生成自然、完整的场景。"
         "场景与主体组成完整画面；不要换成绿幕、透明底或棋盘格。")
        if background_mode == "opaque" else
        f"若无法输出真实透明通道，统一使用纯色 {key_color}，无阴影、渐变或纹理。"
        if key_color
        else (
            "优先输出真实透明通道；若模型不支持，执行前必须选择与所有角色主色都高对比的单一色键"
            "（优先绿或品红；禁止用接近角色颜色的黑、白或灰底板）。"
        )
    )
    text_rule = "保留输入图像中已经存在的文字或符号及其位置，不新增文字或标签。"
    opening = (
        "以输入图像中的主体为身份参考，制作单张 1:1 方形动态表情；背景由场景要求决定，不必沿用主体锚图的背景。"
        if background_mode == "opaque" else
        f"严格保持输入图像实际检测到的 {grid} 网格布局不变，共 {count} 格，并将这张表情图板动画化。"
    )
    composition = (
        "严格保持主体的造型、五官、颜色、服装、身体比例、已有道具与画面中的主体位置。"
        "允许按场景要求生成背景中的环境元素，但不要新增人物、肢体或无关道具；不要改变画布比例。"
        if background_mode == "opaque" else
        "严格保持每格角色的造型、五官、颜色、服装、身体比例、已有道具、位置和整体构图。"
        "不要新增角色、肢体、物体、特效、边框或阴影，不要改变画布比例。"
    )
    if background_mode == "opaque":
        video_prompt = f"""{opening}

镜头固定：禁止推近、拉远、平移、旋转、倾斜和抖动。{composition}{text_rule}

主体动作：{tiles[0]['motion']}；幅度 {tiles[0].get('amplitude', 'small')}；循环 {tiles[0].get('loop', 'return-to-start')}。

动作在视频开始后的前 2 秒内完成，结束时回到初始姿势或按指定循环策略闭合；余下时间仅允许极轻微呼吸。主体位置稳定，画面四周保留安全边距。{background} 场景在整段视频中保持连贯，避免闪烁或突变。"""
    else:
        video_prompt = f"""{opening}

镜头完全固定：禁止推近、拉远、平移、旋转、倾斜和抖动。每个角色只能在自己的格子内独立运动；禁止任何跨格、全画面同步运动或格子之间互相影响。{composition}{text_rule}

逐格动作（按从左到右、从上到下编号）：
{motions}

每格只完成一个原地微动作。动作必须在视频开始后的前 2 秒内完成并回到初始姿势；余下时间保持近乎静止，仅允许极轻微呼吸。角色身体中心和脚底基线固定，不得持续漂移。不要使用大幅甩动、长距离位移或跨边界运动。所有格子的前景包围盒目标约占所在格 70%–75%，四周至少保留约 10% 安全走廊。

每格动作自然、简洁、适合聊天，结束时回到初始姿势或按指定循环策略闭合。任何主体和已有道具都不能触碰或越过格子边界。{background} 从第一帧到最后一帧都必须保持同一纯色底板；不要用棋盘格模拟透明，不要产生白边、黑边、残留背景或半透明脏边。"""
    negative_prompt = (
        "camera motion, zoom, pan, tilt, roll, shake, global animation, synchronized board movement, "
        "cross-cell interaction, layout change, extra character, extra limb, duplicate prop, "
        "border, checkerboard transparency, white fringe, black fringe, dirty semi-transparent edge"
        + ("" if background_mode == "opaque" else ", scene, floor, gradient background, backdrop shadow")
    )
    return {
        "version": 1,
        "detected_layout": layout,
        "background_contract": ("generate-scene" if scene_prompt else "preserve-or-generate-scene") if background_mode == "opaque" else "provider-bound" if key_color is None else "explicit",
        "background_mode": background_mode,
        "scene_prompt": scene_prompt,
        "static_sheet_prompt_template": (
            "基于已确认主体图创建单张方形动作首帧，保持主体特征、服饰与姿势；场景可以在视频生成阶段按 scene_prompt 创建，无须出现在主体锚图或动作首帧中。"
            if background_mode == "opaque" else
            f"基于所附角色图像创建一套 3D 角色表情插画卡片{sheet_name}。无白边、无厚描边；"
            f"每格加入轻微、局部的情绪背景点缀，{cells_name}保持统一色调，并优先使用宽而完全透明的间隔；"
            "角色采用圆润玩具造型、光滑材质、柔和棚拍光和轻微环境遮蔽。"
            "生成后不要假定布局正确，必须重新检测实际行列数。"
        ),
        "grid_video_prompt": video_prompt,
        "negative_prompt": negative_prompt,
        "tile_plan": tiles,
        "text_policy": text_policy
        or {
            "user_requested_text": False,
            "default": "avoid",
            "post_generation": "record-only",
            "generated_text_is_not_a_failure": True,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--layout", type=Path, required=True)
    parser.add_argument("--tile-plan", type=Path)
    # The concrete screen belongs to the selected execution attempt, not to
    # the provider-neutral motion prompt.  Keep the flag for explicit legacy
    # callers, but do not silently compile green into every route.
    parser.add_argument("--key-color", type=str)
    parser.add_argument("--background-mode", choices=("transparent", "opaque"), default="transparent")
    parser.add_argument("--scene-prompt", help="保留背景模式下由视频模型生成的场景描述；不属于主体锚图确认")
    parser.add_argument(
        "--static-prompt",
        type=Path,
        help="optional static-prompt.json used to carry the text preference into video prompts",
    )
    parser.add_argument("--allow-generic-motions", action="store_true")
    parser.add_argument("--allow-low-confidence", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    key_color = validate_key_color(args.key_color)
    layout = load_layout(args.layout, args.allow_low_confidence)
    tiles = load_tile_plan(args.tile_plan, layout["count"], args.allow_generic_motions)
    text_policy = None
    if args.static_prompt:
        static_prompt = json.loads(args.static_prompt.read_text(encoding="utf-8"))
        text_policy = static_prompt.get("text_policy")
        if text_policy is not None and not isinstance(text_policy, dict):
            raise ValueError("static prompt text_policy must be an object")
    compiled = compile_prompts(layout, tiles, key_color, text_policy, args.background_mode, args.scene_prompt)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(compiled, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "count": layout["count"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
