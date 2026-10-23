#!/usr/bin/env python3
"""Create one consistent work directory for routing and execution."""

from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import sys
from pathlib import Path

from PIL import Image

from artifact_manifest import record_artifact
from character_workspace import character_workspace, write_character_manifest
from config_contract import is_python_interpreter, validate_provider_config, validate_video_task
from screen_selector import choose_screen, materialize_screen
from video_background_qc import materialize_green_input
from sticker_production_config import default_settings_path, load_production_settings, match_duration_profile
from video_connections import validate_selection, validate_subject


def read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def write_json(path: Path, value: dict, *, overwrite: bool) -> None:
    if path.exists() and not overwrite:
        raise FileExistsError(f"refusing to overwrite {path}; pass --overwrite")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def copy_file(source: Path, target: Path, *, overwrite: bool) -> None:
    if source.expanduser().resolve() == target.expanduser().resolve():
        return
    if target.exists() and not overwrite:
        raise FileExistsError(f"refusing to overwrite {target}; pass --overwrite")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)


def usable_provider_config(source: Path, skill_root: Path) -> dict:
    config = read_json(source)
    for provider in config.get("providers", []):
        for field in ("command", "adapter_command"):
            command = provider.get(field)
            if not isinstance(command, list):
                continue
            for index, value in enumerate(command):
                markers = ("/absolute/path/to/weixin-sticker-gif/scripts/", "/absolute/path/to/motion-sticker-pack/scripts/")
                if isinstance(value, str) and value.startswith(markers):
                    command[index] = str(skill_root / "scripts" / Path(value).name)
            first = command[0]
            if isinstance(first, str) and is_python_interpreter(first) and not Path(first).is_absolute():
                command[0] = sys.executable
    return validate_provider_config(config)


def parse_provider_assignment(value: str, *, kind: str) -> tuple[str, int | str]:
    provider_id, separator, raw = value.partition("=")
    if not separator or not provider_id or not raw:
        raise argparse.ArgumentTypeError(f"{kind} must use PROVIDER=VALUE")
    if kind == "duration":
        try:
            duration = int(raw)
        except ValueError as exc:
            raise argparse.ArgumentTypeError("provider duration must be an integer") from exc
        if not 1 <= duration <= 30:
            raise argparse.ArgumentTypeError("provider duration must be between 1 and 30")
        return provider_id, duration
    if raw not in {"480p", "720p", "768p", "1080p", "2k"}:
        raise argparse.ArgumentTypeError("provider resolution must be 480p, 720p, 768p, 1080p or 2k")
    return provider_id, raw


def source_aspect_ratio(path: Path) -> str:
    with Image.open(path) as image:
        width, height = image.size
    ratio = width / height
    supported = {"1:1": 1.0, "4:3": 4 / 3, "3:4": 3 / 4, "16:9": 16 / 9, "9:16": 9 / 16}
    return min(supported, key=lambda name: abs(math.log(ratio / supported[name])))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--work-dir", type=Path)
    parser.add_argument("--character", help="character display name; creates works/<slug>/ under --skill-root")
    parser.add_argument("--skill-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--layout", type=Path, required=True)
    parser.add_argument("--prompts", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--tile-plan", type=Path, required=True)
    parser.add_argument("--provider-template", type=Path)
    parser.add_argument('--connection', type=Path, help='用户确认的 connection.json；选择模型不会自动提交生成')
    parser.add_argument('--portrait-asset', type=Path, help='Seedance 真人素材的平台资产资格记录')
    parser.add_argument("--tool-manifest-template", type=Path)
    parser.add_argument("--duration-seconds", type=float)
    parser.add_argument("--provider", help="task-level preferred provider id; does not edit the global template")
    parser.add_argument(
        "--fallback-provider", action="append", default=[],
        help="ordered task-level fallback provider id; repeat to build the fallback chain",
    )
    parser.add_argument(
        "--provider-duration", action="append", default=[], metavar="PROVIDER=SECONDS",
        help="per-provider generation duration override",
    )
    parser.add_argument(
        "--provider-resolution", action="append", default=[], metavar="PROVIDER=480p|720p",
        help="per-provider resolution override",
    )
    fallback_group = parser.add_mutually_exclusive_group()
    fallback_group.add_argument("--allow-fallback", dest="allow_fallback", action="store_true")
    fallback_group.add_argument("--no-fallback", dest="allow_fallback", action="store_false")
    parser.set_defaults(allow_fallback=None)
    parser.add_argument(
        "--settings",
        type=Path,
        default=default_settings_path(),
        help="single editable sticker-production settings JSON",
    )
    parser.add_argument("--key-color", help="one-off override for generation.key_color")
    parser.add_argument("--background-mode", choices=("transparent", "opaque"), default="transparent",
                        help="opaque 保留输入首帧的场景背景，不制作色键输入")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    connection = read_json(args.connection) if args.connection else None
    selected_spec = validate_selection(connection) if connection else None
    if selected_spec:
        if args.provider and args.provider != selected_spec['provider_id']:
            raise ValueError('显式 provider 与用户选择的账号/模型不一致')
        args.provider = selected_spec['provider_id']
        args.provider_template = args.provider_template or args.connection.parent / 'selected-providers.json'
        if args.fallback_provider or args.allow_fallback:
            raise ValueError('账号选择流程一次只授权一个后端，切换后端需要重新选择')

    skill_root = args.skill_root.expanduser().resolve()
    if args.character:
        work = args.work_dir.expanduser().resolve() if args.work_dir else character_workspace(skill_root, args.character)
        write_character_manifest(work, args.character)
    elif args.work_dir:
        work = args.work_dir.expanduser().resolve()
        work.mkdir(parents=True, exist_ok=True)
    else:
        raise ValueError("pass --character <name> or --work-dir <path>")
    provider_template = args.provider_template or skill_root / "assets" / "video-providers.example.json"
    manifest_template = args.tool_manifest_template or skill_root / "assets" / "tool-manifest.example.json"
    for path in (args.image, args.layout, args.prompts, args.state, args.tile_plan, provider_template, manifest_template):
        if not path.expanduser().is_file():
            raise FileNotFoundError(path)
    settings_source = args.settings.expanduser().resolve()
    settings = load_production_settings(settings_source)
    config = usable_provider_config(provider_template.expanduser().resolve(), skill_root)
    configured = {item["id"]: item for item in config["providers"]}
    provider = args.provider or settings["generation"]["provider"]
    provider_chain = [provider, *args.fallback_provider]
    if len(provider_chain) != len(set(provider_chain)):
        raise ValueError("provider and fallback-provider values must not contain duplicates")
    for provider_id in provider_chain:
        candidate = configured.get(provider_id)
        if not candidate:
            raise ValueError(f"provider {provider_id!r} is not present in the provider config")
        if not candidate["enabled"]:
            raise ValueError(f"provider {provider_id!r} is disabled in the provider config")
    allow_fallback = args.allow_fallback if args.allow_fallback is not None else bool(args.fallback_provider)
    if args.fallback_provider and not allow_fallback:
        raise ValueError("fallback-provider requires --allow-fallback")
    if args.key_color and not re.fullmatch(r"#[0-9A-Fa-f]{6}", args.key_color):
        raise ValueError("key-color must use #RRGGBB notation")
    if args.background_mode == "opaque":
        if "grok-build-local" in provider_chain:
            raise ValueError("当前 Grok 适配器强制绿幕；保留场景请选支持原图输入的模型，勿提交绿幕任务")
        if args.key_color:
            raise ValueError("保留场景模式不能同时指定色键")
        prompt_data = read_json(args.prompts.expanduser().resolve())
        if prompt_data.get("background_mode") != "opaque":
            raise ValueError("动作提示词与保留场景模式不一致")
        with Image.open(args.image.expanduser().resolve()) as source_image:
            has_transparency = source_image.convert("RGBA").getchannel("A").getextrema()[0] != 255
        if has_transparency and not prompt_data.get("scene_prompt"):
            raise ValueError("透明主体首帧需提供 --scene-prompt，让视频模型生成完整场景")
    provider_durations = dict(settings["generation"]["provider_duration_seconds"])
    if selected_spec:
        provider_durations.setdefault(provider, 6)
    duration_overrides = dict(
        parse_provider_assignment(value, kind="duration") for value in args.provider_duration
    )
    resolution_overrides = dict(
        parse_provider_assignment(value, kind="resolution") for value in args.provider_resolution
    )
    unknown_overrides = (set(duration_overrides) | set(resolution_overrides)) - set(provider_chain)
    if unknown_overrides:
        raise ValueError(f"provider overrides target providers outside provider_chain: {sorted(unknown_overrides)}")
    provider_durations.update(duration_overrides)
    if provider not in provider_durations:
        raise ValueError(f"no duration configured for selected provider {provider!r}; use --provider-duration")
    duration_seconds = provider_durations[provider]
    if args.duration_seconds is not None:
        rounded_duration = round(args.duration_seconds)
        if rounded_duration != args.duration_seconds or not 1 <= rounded_duration <= 30:
            raise ValueError("duration-seconds must be an integer between 1 and 30")
        duration_seconds = rounded_duration
        provider_durations[provider] = rounded_duration
    missing_durations = [provider_id for provider_id in provider_chain if provider_id not in provider_durations]
    if missing_durations:
        raise ValueError(f"no duration configured for providers {missing_durations}; use --provider-duration")
    provider_execution = {
        provider_id: {
            "duration_seconds": provider_durations[provider_id],
            "resolution": resolution_overrides.get(provider_id, selected_spec['default_resolution'] if selected_spec else settings["generation"]["resolution"]),
        }
        for provider_id in provider_chain
    }
    for provider_id, execution in provider_execution.items():
        if selected_spec:
            duration = execution['duration_seconds']
            if not selected_spec['duration'][0] <= duration <= selected_spec['duration'][1] or execution['resolution'] not in selected_spec['resolutions']:
                raise ValueError('时长或分辨率不符合所选模型的规格')
        try:
            match_duration_profile(settings, float(execution["duration_seconds"]))
        except ValueError as exc:
            if selected_spec:
                # New models may return 4–30s. Keep returned duration and reuse
                # the existing output contract rather than silently speeding it up.
                import copy
                profile = copy.deepcopy(settings['duration_profiles'][-1])
                duration = execution['duration_seconds']
                profile.update(id=f'returned-{duration}s', match_duration={
                    'minimum_seconds': duration - .25, 'maximum_seconds': duration + .25})
                settings['duration_profiles'].append(profile)
                continue
            raise ValueError(
                f"provider {provider_id!r} duration {execution['duration_seconds']}s has no output profile"
            ) from exc
    aspect_ratio = source_aspect_ratio(args.image.expanduser().resolve())
    automatic_screen = choose_screen(args.image.expanduser().resolve()) if args.background_mode == "transparent" else None
    automatic_color = str(automatic_screen["selected"]["color"]).upper() if automatic_screen else "#00FF00"
    green_score = next((item for item in automatic_screen["candidates"] if item["id"] == "green"), None) if automatic_screen else None
    grok_color = args.key_color.upper() if args.key_color else (
        "#00FF00" if green_score and green_score["foreground_collision_fraction"] == 0
        and green_score["foreground_distance_p05"] >= 100 else automatic_color
    )
    if args.background_mode == "transparent" and args.key_color and automatic_screen:
        from screen_selector import hex_rgb, foreground_pixels
        import numpy as np
        source_image, mask, _ = foreground_pixels(args.image.expanduser().resolve())
        try:
            pixels = np.asarray(source_image, dtype=np.uint8)[:, :, :3][mask].astype(np.float32)
            distances = np.sqrt(np.sum((pixels - hex_rgb(args.key_color)) ** 2, axis=1))
            if float(np.percentile(distances, 5)) < 80:
                raise ValueError("指定色键与主体颜色冲突，请换用高反差色键")
        finally:
            source_image.close()
    provider_key_colors = {
        provider_id: (
            grok_color
            if provider_id == "grok-build-local"
            else (args.key_color or automatic_color).upper()
        )
        for provider_id in provider_chain
    }
    screen_selection = (
        {"policy": "preserve-scene", "provider_key_colors": provider_key_colors}
        if args.background_mode == "opaque" else
        {**automatic_screen, "policy": "foreground-contrast-auto-or-explicit",
         "explicit_override": args.key_color.upper() if args.key_color else None,
         "provider_key_colors": provider_key_colors}
    )
    color_targets = {
        color: work / f"input-screen-{color[1:].lower()}.png"
        for color in sorted(set(provider_key_colors.values())) if args.background_mode == "transparent"
    }
    provider_input_images = {
        provider_id: str(color_targets[color].resolve()) if args.background_mode == "transparent" else str(args.image.expanduser().resolve())
        for provider_id, color in provider_key_colors.items()
    }
    settings_snapshot = work / "sticker-production.json"
    planned_targets = [
        work / "video-providers.json",
        work / "tile-plan.json",
        settings_snapshot,
        work / "video-task.json",
        *color_targets.values(),
    ]
    existing_targets = [path for path in planned_targets if path.exists()]
    if existing_targets and not args.overwrite:
        names = ", ".join(path.name for path in existing_targets)
        raise FileExistsError(f"refusing partial workflow update; existing targets: {names}; pass --overwrite")
    write_json(work / "video-providers.json", config, overwrite=args.overwrite)
    runtime_manifest = work / "runtime-tools.json"
    if not runtime_manifest.exists() or args.overwrite:
        copy_file(manifest_template.expanduser().resolve(), runtime_manifest, overwrite=args.overwrite)
    copy_file(args.tile_plan.expanduser().resolve(), work / "tile-plan.json", overwrite=args.overwrite)
    for color, target in color_targets.items():
        if automatic_screen["mask_method"] == "source-alpha":
            materialize_green_input(
                args.image.expanduser().resolve(), target, color,
                layout=read_json(args.layout.expanduser().resolve()),
                safe_scale=0.75, min_guard_fraction=0.10,
                max_foreground_bbox_fraction=0.75,
            )
        else:
            materialize_screen(args.image.expanduser().resolve(), target, color)
    effective_settings = {key: value for key, value in settings.items() if key != "_meta"}
    effective_settings["generation"] = dict(effective_settings["generation"])
    effective_settings["generation"]["provider"] = provider
    effective_settings["generation"]["provider_duration_seconds"] = provider_durations
    effective_settings["generation"]["resolution"] = provider_execution[provider]["resolution"]
    effective_settings["generation"]["key_color"] = provider_key_colors[provider]
    write_json(settings_snapshot, effective_settings, overwrite=args.overwrite)
    load_production_settings(settings_snapshot)

    output_directory = (work / "raw-video").resolve()
    task = read_json(skill_root / "assets" / "video-task.example.json")
    task.update(
        {
            "provider": provider,
            "provider_chain": provider_chain,
            "provider_selection_source": "task-override" if args.provider else "production-settings",
            "allow_fallback": allow_fallback,
            "max_retries": settings["generation"]["max_retries"],
            "input_image": str(args.image.expanduser().resolve()),
            "layout_file": str(args.layout.expanduser().resolve()),
            "prompt_file": str(args.prompts.expanduser().resolve()),
            "approval_file": str(args.state.expanduser().resolve()),
            "output_directory": str(output_directory),
            "duration_seconds": duration_seconds,
            "provider_duration_seconds": provider_durations,
            "provider_execution": provider_execution,
            "aspect_ratio": aspect_ratio,
            "key_color": provider_key_colors[provider],
            "background_mode": args.background_mode,
            "allow_key_background": args.background_mode == "transparent",
            "require_alpha": args.background_mode == "transparent",
            "provider_key_colors": provider_key_colors,
            "provider_input_images": provider_input_images,
            "screen_selection": screen_selection,
            "production_settings_file": str(settings_snapshot.resolve()),
            "attempt_ledger_file": str((work / "attempt-ledger.json").resolve()),
            "artifact_manifest_file": str((work / "artifact-manifest.json").resolve()),
            "safe_grid_scale": 0.75,
            "min_guard_fraction": 0.10,
            "max_foreground_bbox_fraction": 0.75,
            "motion_active_seconds": 2.0,
            "loop_min_seconds": 1.5,
            "loop_max_seconds": 2.5,
        }
    )
    task_path = work / "video-task.json"
    if connection:
        task['connection_file'] = str(args.connection.expanduser().resolve())
        task['subject'] = {'type': connection['subject_type']}
        if args.portrait_asset:
            asset = read_json(args.portrait_asset)
            task['subject']['seedance_asset'] = asset
            task['input_asset_uri'] = asset.get('uri')
        validate_subject(task, configured[provider])
    write_json(task_path, validate_video_task(task, require_execution_fields=True), overwrite=args.overwrite)
    artifact_manifest = work / "artifact-manifest.json"
    source_ids = [
        record_artifact(artifact_manifest, path, kind=kind, stage="prepared-input", workspace=work)
        for path, kind in (
            (args.image, "static-sheet"),
            (args.layout, "layout"),
            (args.prompts, "motion-prompts"),
            (args.state, "approval-state"),
        )
    ]
    if args.connection:
        source_ids.append(record_artifact(artifact_manifest, args.connection, kind='account-selection', stage='prepared-input', workspace=work))
    screen_ids = [
        record_artifact(
            artifact_manifest,
            target,
            kind="provider-screen-input",
            stage="prepared-input",
            dependencies=[source_ids[0]],
        )
        for target in color_targets.values()
    ]
    config_id = record_artifact(
        artifact_manifest, work / "video-providers.json", kind="provider-config", stage="prepared"
    )
    settings_id = record_artifact(
        artifact_manifest, settings_snapshot, kind="production-settings", stage="prepared"
    )
    tile_id = record_artifact(
        artifact_manifest, work / "tile-plan.json", kind="tile-plan", stage="prepared"
    )
    task_id = record_artifact(
        artifact_manifest,
        task_path,
        kind="video-task",
        stage="prepared",
        dependencies=[*source_ids, *screen_ids, config_id, settings_id, tile_id],
    )
    result = {
        "work_dir": str(work),
        "config": str((work / "video-providers.json").resolve()),
        "runtime_tools": str((work / "runtime-tools.json").resolve()),
        "tile_plan": str((work / "tile-plan.json").resolve()),
        "production_settings": str(settings_snapshot.resolve()),
        "task": str((work / "video-task.json").resolve()),
        "attempt_ledger": str((work / "attempt-ledger.json").resolve()),
        "artifact_manifest": str(artifact_manifest.resolve()),
        "screen_selection": screen_selection,
        "provider_input_images": provider_input_images,
        "task_artifact_id": task_id,
    }
    manifest = work / "character.json"
    if manifest.is_file():
        result["character"] = read_json(manifest)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
