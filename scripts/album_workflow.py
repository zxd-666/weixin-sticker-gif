#!/usr/bin/env python3
"""Plan an independent-video sticker album and package only verified GIFs.

This script never calls an image or video provider. The Skill uses the plan to
drive generation and the pack command as its final, deterministic acceptance gate.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageSequence

from album_assets import validate_assets
from attempt_ledger import progress_path_for, validate_ledger
from config_contract import object_sha256, read_json_object, validate_provider_config, validate_video_task
from execute_video_route import execute_attempt, provider_by_id
from manage_job_state import read_state, verify_state
from output_safety import begin_output_transaction
from route_video_provider import dependency_hashes
from subject_anchor import verify_approval
from video_connections import validate_execution


DEFAULT_REACTIONS = ("收到", "大笑", "抱抱", "谢谢", "加油", "惊讶", "委屈", "晚安")
MAX_GIF_BYTES = 500_000


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def reactions_from_text(value: str | None) -> list[str]:
    reactions = [part.strip() for part in value.replace("，", ",").split(",")] if value else list(DEFAULT_REACTIONS)
    if not 8 <= len(reactions) <= 24 or any(not item for item in reactions):
        raise ValueError("整套动态表情须有 8–24 个非空动作")
    if len(set(reactions)) != len(reactions):
        raise ValueError("动作名称重复；每张表情应有明确差异")
    return reactions


def build_plan(args: argparse.Namespace) -> dict:
    reactions = reactions_from_text(args.reactions)
    background_mode = args.background_mode
    if background_mode not in {"transparent", "opaque"}:
        raise ValueError("须先确定表情背景模式：transparent 或 opaque")
    if args.subject_description is not None and not args.subject_description.strip():
        raise ValueError("主体描述不能为空")
    source = args.reference_image or args.approved_anchor
    source_record = None
    if source:
        source = source.expanduser().resolve(strict=True)
        if not source.is_file():
            raise ValueError("主体参考图必须是文件")
        with Image.open(source) as image:
            image.verify()
        source_record = {"path": str(source), "sha256": sha256(source)}
    if args.approved_anchor:
        source_mode = "approved-anchor"
    elif args.reference_image:
        source_mode = "reference-image"
    else:
        source_mode = "text-description"
    items = [
        {"id": f"{index:02d}", "reaction": reaction, "static_group": (index - 1) // 4 + 1,
         "static_cell": (index - 1) % 4 + 1,
         "video_job": f"video/{index:02d}"}
        for index, reaction in enumerate(reactions, start=1)
    ]
    groups = [
        {"id": f"{start // 4 + 1:02d}", "items": [item["id"] for item in items[start:start + 4]],
         "layout": {"columns": 2 if len(items[start:start + 4]) == 4 else len(items[start:start + 4]),
                    "rows": 2 if len(items[start:start + 4]) == 4 else 1}}
        for start in range(0, len(items), 4)
    ]
    return {
        "version": 1, "kind": "independent-video-album-plan", "name": args.name.strip(),
        "subject": {"mode": source_mode, "description": args.subject_description,
                    "reference": source_record, "type": args.subject_type},
        "style": args.style.strip(), "count": len(items), "items": items, "static_groups": groups,
        "call_budget": {"subject_image_calls": 0 if source_mode == "approved-anchor" else 1,
                        "static_sheet_calls": len(groups), "video_calls": len(items),
                        "auxiliary_image_calls_max": 5,
                        "automatic_retries": 0, "extra_fee_status": "unverified"},
        "delivery": {"format": "GIF", "width": 240, "height": 240,
                     "max_gif_bytes": MAX_GIF_BYTES, "loop": 0,
                     "background_mode": background_mode},
    }


def validate_plan(plan: dict) -> None:
    if plan.get("version") != 1 or plan.get("kind") != "independent-video-album-plan":
        raise ValueError("不支持的整套任务清单")
    if plan.get("delivery", {}).get("background_mode", "transparent") not in {"transparent", "opaque"}:
        raise ValueError("任务清单的背景模式无效")
    items = plan.get("items")
    if not isinstance(items, list) or not 8 <= len(items) <= 24 or plan.get("count") != len(items):
        raise ValueError("任务清单的表情数量须为 8–24")
    if (not isinstance(plan.get("name"), str) or not plan["name"].strip()
            or not isinstance(plan.get("style"), str) or not plan["style"].strip()
            or plan.get("subject", {}).get("type") not in {"real-person", "fictional", "unknown"}):
        raise ValueError("任务清单缺少有效主体、风格或素材类型")
    if [item.get("id") for item in items] != [f"{i:02d}" for i in range(1, len(items) + 1)]:
        raise ValueError("任务清单编号不连续")
    if len({item.get("reaction") for item in items}) != len(items):
        raise ValueError("任务清单有重复动作")
    if any(item.get("video_job") != f"video/{index:02d}"
           or item.get("static_group") != (index - 1) // 4 + 1
           or item.get("static_cell") != (index - 1) % 4 + 1
           for index, item in enumerate(items, 1)):
        raise ValueError("任务清单的静态分组或视频目录不匹配")
    groups = plan.get("static_groups")
    if not isinstance(groups, list) or len(groups) != math.ceil(len(items) / 4):
        raise ValueError("静态分组数量不匹配")
    for group_index, group in enumerate(groups):
        members = items[group_index * 4:group_index * 4 + 4]
        layout = group.get("layout", {})
        if group.get("items") != [item["id"] for item in members] or layout.get("columns", 0) * layout.get("rows", 0) != len(members):
            raise ValueError("静态分组布局与动作数不匹配")


def check_gif(path: Path, *, background_mode: str = "transparent") -> dict:
    if background_mode not in {"transparent", "opaque"}:
        raise ValueError("GIF 背景模式无效")
    if not path.is_file() or path.stat().st_size > MAX_GIF_BYTES:
        raise ValueError(f"GIF 缺失或超过 500000 字节：{path}")
    with Image.open(path) as image:
        if image.format != "GIF" or image.size != (240, 240) or image.info.get("loop") != 0:
            raise ValueError(f"GIF 格式、240×240 尺寸或无限循环不合格：{path}")
        if background_mode == "transparent" and "transparency" not in image.info:
            raise ValueError(f"GIF 缺少透明背景：{path}")
        frames = 0
        hashes: set[bytes] = set()
        duration_ms = 0
        for frame in ImageSequence.Iterator(image):
            frames += 1
            duration_ms += frame.info.get("duration", 0)
            rgba = frame.convert("RGBA")
            alpha_min = rgba.getchannel("A").getextrema()[0]
            if background_mode == "transparent" and frames == 1 and alpha_min != 0:
                raise ValueError(f"GIF 首帧没有实际透明像素：{path}")
            if background_mode == "opaque" and alpha_min != 255:
                raise ValueError(f"保留背景的 GIF 第 {frames} 帧出现透明像素：{path}")
            hashes.add(hashlib.sha256(rgba.tobytes()).digest())
        if frames < 2 or len(hashes) < 2 or duration_ms <= 0:
            raise ValueError(f"GIF 没有有效动态帧：{path}")
    return {"bytes": path.stat().st_size, "frames": frames, "duration_ms": duration_ms,
            "sha256": sha256(path)}


def bind_anchor(plan_path: Path, image: Path, output: Path, approval_path: Path) -> dict:
    plan_path = plan_path.expanduser().resolve(strict=True)
    image = image.expanduser().resolve(strict=True)
    plan = read_json_object(plan_path)
    validate_plan(plan)
    with Image.open(image) as opened:
        opened.verify()
    approval_path = approval_path.expanduser().resolve(strict=True)
    verify_approval(approval_path, image)
    expected = (plan.get("subject", {}).get("reference") or {}).get("sha256")
    if plan["subject"]["mode"] == "approved-anchor" and expected != sha256(image):
        raise ValueError("复用主体图与已确认锚图不一致")
    record = {"version": 1, "kind": "album-anchor", "plan_sha256": sha256(plan_path),
              "image": str(image), "sha256": sha256(image), "approval": str(approval_path),
              "approval_sha256": sha256(approval_path)}
    output = output.expanduser().resolve()
    if output.exists():
        raise FileExistsError(f"拒绝覆盖主体锚图记录：{output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return record


def package(plan_path: Path, media_dir: Path, asset_dir: Path, output: Path, *,
            names_path: Path | None = None, include_rewards: bool = True) -> dict:
    plan_path = plan_path.expanduser().resolve(strict=True)
    media_dir = media_dir.expanduser().resolve(strict=True)
    asset_dir = asset_dir.expanduser().resolve(strict=True)
    plan = read_json_object(plan_path)
    validate_plan(plan)
    album_name = plan["name"]
    if (not re.search(r"[\u4e00-\u9fff]", album_name) or re.search(r"[A-Za-z0-9]", album_name)
            or any(char in album_name for char in "/\\") or ".." in album_name
            or any(ord(char) < 32 for char in album_name)):
        raise ValueError("专辑名及 ZIP 文件名须含中文，不含英文字母、数字或路径字符")
    names = ({item["id"]: item["reaction"] for item in plan["items"]}
             if names_path is None else read_json_object(names_path))
    if set(names) != {item["id"] for item in plan["items"]}:
        raise ValueError("表情主题名清单须与计划编号一一对应")
    if (any(not isinstance(name, str) or not re.fullmatch(r"[\u4e00-\u9fff]{1,4}", name)
            for name in names.values()) or len(set(names.values())) != len(names)):
        raise ValueError("每张 GIF 须有不重复的 1–4 字中文主题名；必要时用 --names-file 指定")
    expected = {f"{item['id']}.gif" for item in plan["items"]}
    observed = {path.name for path in media_dir.glob("*.gif")}
    if observed != expected:
        raise ValueError(f"GIF 数量或编号不符：缺少 {sorted(expected-observed)}，多出 {sorted(observed-expected)}")
    background_mode = plan["delivery"].get("background_mode", "transparent")
    checked = {item["id"]: check_gif(media_dir / f"{item['id']}.gif", background_mode=background_mode)
               for item in plan["items"]}
    assets, warnings = validate_assets(asset_dir, include_rewards=include_rewards)
    result = {"version": 1, "kind": "local-album-validation", "count": len(checked),
              "plan_sha256": sha256(plan_path), "background_mode": background_mode,
              "items": checked, "names": names,
              "auxiliary_assets": {path.name: {"sha256": sha256(path), "bytes": path.stat().st_size}
                                   for path in assets}, "warnings": warnings,
              "scope": "本地文件检查；角色、画面质量和微信平台审核须另行检查"}
    transaction = begin_output_transaction(
        output, overwrite=False, archive_names={f"{album_name}表情包.zip"},
        protected_paths=[plan_path, media_dir, asset_dir, *([names_path] if names_path else [])],
    )
    target = transaction.output
    materials = target / "专辑素材"
    sticker_output = materials / "表情"
    sticker_output.mkdir(parents=True)
    for item in plan["items"]:
        shutil.copyfile(media_dir / f"{item['id']}.gif", sticker_output / f"{names[item['id']]}.gif")
    for path in assets:
        shutil.copyfile(path, materials / path.name)
    (target / "album-plan.json").write_bytes(plan_path.read_bytes())
    (target / "validation.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    zip_path = target / f"{album_name}表情包.zip"
    members = sorted(path for path in materials.rglob("*") if path.is_file())
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as bundle:
        for path in members:
            bundle.write(path, arcname=path.relative_to(materials).as_posix())
    with zipfile.ZipFile(zip_path) as bundle:
        if bundle.testzip() is not None:
            raise ValueError("ZIP 完整性检查失败")
    transaction.commit()
    return {"output": str(target), "zip": str(zip_path), "files": len(members), **result}


def batch_preflight(plan_path: Path, job_root: Path) -> tuple[dict, list[dict]]:
    """Check every job and fee approval before the first external submission."""
    plan_path = plan_path.expanduser().resolve(strict=True)
    job_root = job_root.expanduser().resolve(strict=True)
    plan = read_json_object(plan_path)
    validate_plan(plan)
    anchor = read_json_object(job_root / "album-anchor.json")
    if (anchor.get("kind") != "album-anchor" or anchor.get("plan_sha256") != sha256(plan_path)
            or not Path(anchor.get("image", "")).is_file()
            or anchor.get("sha256") != sha256(Path(anchor["image"]))):
        raise ValueError("主体锚图或整套计划发生变化")
    approval_path = Path(anchor.get("approval", ""))
    if (not approval_path.is_file() or anchor.get("approval_sha256") != sha256(approval_path)):
        raise ValueError("主体图确认记录缺失或发生变化")
    verify_approval(approval_path, Path(anchor["image"]))
    ready = []
    paid_max = 0.0
    paid_estimate = 0.0
    currency = None
    approval_hashes = {}
    for item in plan["items"]:
        directory = job_root / item["video_job"]
        config_path = directory / "video-providers.json"
        task_path = directory / "video-task.json"
        route_path = directory / "route.json"
        approval_path = directory / "execution-approval.json"
        result_path = directory / "video-result.json"
        config = validate_provider_config(read_json_object(config_path))
        task = validate_video_task(read_json_object(task_path), require_execution_fields=True)
        route = read_json_object(route_path)
        if route.get("config_sha256") != object_sha256(config) or route.get("task_sha256") != object_sha256(task):
            raise ValueError(f"{item['id']} 路由与配置/任务哈希不一致")
        if route.get("dependency_sha256") != dependency_hashes(task):
            raise ValueError(f"{item['id']} 视频任务输入已变化")
        layout_data = read_json_object(Path(task["layout_file"]))
        prompt_data = read_json_object(Path(task["prompt_file"]))
        background_mode = plan["delivery"].get("background_mode", "transparent")
        if task.get("background_mode", "transparent") != background_mode or prompt_data.get("background_mode", "transparent") != background_mode:
            raise ValueError(f"{item['id']} 视频任务或提示词的背景模式与整套计划不一致")
        if background_mode == "opaque" and task.get("allow_key_background"):
            raise ValueError(f"{item['id']} 保留场景任务不能使用色键背景")
        layout = layout_data.get("detected_layout", layout_data)
        prompt_layout = prompt_data.get("detected_layout", prompt_data)
        if (layout.get("columns"), layout.get("rows"), layout.get("count")) != (1, 1, 1):
            raise ValueError(f"{item['id']} 批量任务应使用独立的 1×1 首帧")
        if (prompt_layout.get("columns"), prompt_layout.get("rows"), prompt_layout.get("count")) != (1, 1, 1):
            raise ValueError(f"{item['id']} 动作提示词与独立首帧不一致")
        if not isinstance(prompt_data.get("grid_video_prompt"), str) or not prompt_data["grid_video_prompt"].strip():
            raise ValueError(f"{item['id']} 缺少有效视频提示词")
        attempts = route.get("attempts")
        if not isinstance(attempts, list) or len(attempts) != 1 or route.get("fallback"):
            raise ValueError(f"{item['id']} 批量路线只能有一个后端且禁止自动切换")
        selected = attempts[0]
        if selected.get("attempt") != 1 or selected.get("driver") == "native-tool":
            raise ValueError(f"{item['id']} 批量执行只支持已有外部视频适配器")
        provider = provider_by_id(config, selected["id"], selected)
        if task.get("subject", {}).get("type") != plan["subject"]["type"]:
            raise ValueError(f"{item['id']} 主体类型与整套计划不一致")
        state = read_state(Path(task["approval_file"]))
        verify_state(state, Path(task["input_image"]), Path(task["layout_file"]))
        static_prompt_record = state.get("static_prompt") or {}
        if not static_prompt_record.get("path") or static_prompt_record.get("sha256") != sha256(Path(static_prompt_record["path"])):
            raise ValueError(f"{item['id']} 缺少有效的静态生成提示词")
        static_prompt = read_json_object(Path(static_prompt_record["path"]))
        if (static_prompt.get("reference_image") or {}).get("sha256") != anchor["sha256"]:
            raise ValueError(f"{item['id']} 静态首帧没有引用同一个主体锚图")
        if state.get("source_type") == "album-generated":
            state_approval = state.get("approval", {})
            if state_approval.get("album_plan_sha256") != sha256(plan_path) or state_approval.get("album_item") != item["id"]:
                raise ValueError(f"{item['id']} 静态首帧批准记录不属于当前整套计划")
        approval = validate_execution(task, provider, route, approval_path)
        if approval is None:
            raise ValueError(f"{item['id']} 缺少可验证的账号/费用确认")
        ledger_path = Path(task.get("attempt_ledger_file") or directory / "attempt-ledger.json")
        if result_path.exists():
            result = read_json_object(result_path)
            if result.get("status") != "succeeded":
                raise ValueError(f"{item['id']} 已有失败或不确定任务，批量运行不会重试")
            ledger = read_json_object(ledger_path)
            attempts_done = ledger.get("attempts", [])
            if (ledger.get("route_sha256") != object_sha256(route)
                    or ledger.get("task_sha256") != object_sha256(task)
                    or ledger.get("config_sha256") != object_sha256(config)
                    or len(attempts_done) != 1 or attempts_done[0].get("status") != "succeeded"):
                raise ValueError(f"{item['id']} 既有结果不属于当前任务")
            generated = attempts_done[0].get("generated", {})
            video = Path(result.get("output", ""))
            if not video.is_file() or generated.get("path") != str(video) or generated.get("sha256") != sha256(video):
                raise ValueError(f"{item['id']} 既有视频文件或哈希不匹配")
            status = "completed"
        elif ledger_path.exists():
            ledger = validate_ledger(read_json_object(ledger_path), route)
            attempts_done = ledger["attempts"]
            unstarted = (len(attempts_done) == 1
                         and attempts_done[0].get("attempt") == 1
                         and attempts_done[0].get("provider") == selected["id"]
                         and attempts_done[0].get("status") == "planned"
                         and attempts_done[0].get("cost_status") == "not-started"
                         and attempts_done[0].get("retry_count") == 0
                         and not attempts_done[0].get("request_id")
                         and len(attempts_done[0].get("events", [])) == 1
                         and attempts_done[0]["events"][0].get("status") == "planned"
                         and not progress_path_for(ledger_path, 1).exists())
            if not unstarted:
                raise ValueError(f"{item['id']} 已有尝试记录且未完成，请先核对远端任务")
            status = "ready"
        else:
            status = "ready"
        if approval["billing"] == "paid":
            if currency and currency != approval["currency"]:
                raise ValueError("整套付费任务币种不一致，不能相加")
            currency = approval["currency"]
            paid_max += approval["max_cost"]
            paid_estimate += approval["estimated_cost"]
        approval_hashes[item["id"]] = sha256(approval_path)
        ready.append({"id": item["id"], "directory": directory, "config": config_path,
                      "task": task_path, "route": route, "approval": approval_path,
                      "result": result_path, "status": status})
    report = {"version": 1, "plan_sha256": sha256(plan_path), "count": len(ready),
              "remaining_calls": sum(job["status"] == "ready" for job in ready),
              "estimated_extra_cost": paid_estimate, "maximum_extra_cost": paid_max,
              "currency": currency, "approval_sha256": approval_hashes,
              "jobs": [{"id": job["id"], "status": job["status"]} for job in ready],
              "note": "费用上限来自逐任务确认；订阅额度实际扣减仍以平台为准"}
    return report, ready


def authorize_batch(plan_path: Path, job_root: Path, output: Path, *, max_cost: float,
                    currency: str | None, confirmed: bool) -> dict:
    if not confirmed:
        raise ValueError("批量生成需要用户明确确认整套费用上限")
    report, _ = batch_preflight(plan_path, job_root)
    if not math.isfinite(max_cost) or max_cost < report["maximum_extra_cost"] or max_cost < 0:
        raise ValueError("整套费用上限低于逐张确认的费用合计")
    if report["currency"] != currency or (currency is None and max_cost != 0):
        raise ValueError("整套费用币种与逐张确认不一致")
    value = {"version": 1, "kind": "album-execution-approval", "confirmed_by_user": True,
             "confirmed_at": datetime.now(timezone.utc).isoformat(),
             "plan_sha256": report["plan_sha256"], "approval_sha256": report["approval_sha256"],
             "count": report["count"], "max_total_extra_cost": max_cost, "currency": currency}
    output = output.expanduser().resolve()
    if output.exists():
        raise FileExistsError(f"拒绝覆盖整套费用确认：{output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"approval": str(output), **value}


def run_batch(plan_path: Path, job_root: Path, batch_approval: Path) -> dict:
    report, jobs = batch_preflight(plan_path, job_root)
    approval = read_json_object(batch_approval)
    try:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(approval["confirmed_at"])).total_seconds()
    except (KeyError, TypeError, ValueError):
        age = float("inf")
    if (approval.get("version") != 1 or approval.get("kind") != "album-execution-approval"
            or approval.get("confirmed_by_user") is not True or not 0 <= age <= 3600
            or approval.get("plan_sha256") != report["plan_sha256"]
            or approval.get("approval_sha256") != report["approval_sha256"]
            or approval.get("count") != report["count"]
            or approval.get("currency") != report["currency"]
            or isinstance(approval.get("max_total_extra_cost"), bool)
            or not isinstance(approval.get("max_total_extra_cost"), (int, float))
            or not math.isfinite(approval["max_total_extra_cost"])
            or approval["max_total_extra_cost"] < report["maximum_extra_cost"]):
        raise ValueError("整套费用确认已过期，或不属于当前任务/账号/费用范围")
    for job in jobs:
        if job["status"] == "completed":
            continue
        execute_attempt(job["config"], job["task"], job["route"], job["result"], 1,
                        execution_approval_path=job["approval"])
        result = read_json_object(job["result"])
        if result.get("status") != "succeeded":
            raise ValueError(f"{job['id']} 未成功；已停止后续视频提交")
    report["remaining_calls"] = 0
    report["jobs"] = [{"id": job["id"], "status": "completed"} for job in jobs]
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="规划整套独立视频表情，或验收并打包最终 GIF")
    sub = parser.add_subparsers(dest="action", required=True)
    p = sub.add_parser("plan")
    p.add_argument("--name", required=True)
    source = p.add_mutually_exclusive_group(required=True)
    source.add_argument("--subject-description")
    source.add_argument("--reference-image", type=Path)
    source.add_argument("--approved-anchor", type=Path)
    p.add_argument("--subject-type", choices=["real-person", "fictional", "unknown"], required=True)
    p.add_argument("--style", required=True)
    p.add_argument("--background-mode", choices=["transparent", "opaque"], required=True,
                   help="最终 GIF 透明底或保留/生成场景；主体锚图只确认主体，背景模式在动作或视频生成前确定")
    p.add_argument("--reactions", help="逗号分隔 8–24 个动作；缺省为八个常用聊天动作")
    p.add_argument("--output", type=Path, required=True)
    p = sub.add_parser("pack")
    p.add_argument("--plan", type=Path, required=True)
    p.add_argument("--media-dir", type=Path, required=True)
    p.add_argument("--asset-dir", type=Path, required=True)
    p.add_argument("--names-file", type=Path, help="编号到 1–4 字中文主题名的 JSON；缺省用计划动作名")
    p.add_argument("--no-reward", action="store_true", help="用户明确不需要赞赏素材时才使用")
    p.add_argument("--output", type=Path, required=True)
    p = sub.add_parser("bind-anchor")
    p.add_argument("--plan", type=Path, required=True)
    p.add_argument("--image", type=Path, required=True)
    p.add_argument("--approval", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    for action in ("preflight", "run"):
        p = sub.add_parser(action)
        p.add_argument("--plan", type=Path, required=True)
        p.add_argument("--job-root", type=Path, required=True)
        if action == "run":
            p.add_argument("--batch-approval", type=Path, required=True)
    p = sub.add_parser("authorize-batch")
    p.add_argument("--plan", type=Path, required=True)
    p.add_argument("--job-root", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--max-total-cost", type=float, required=True)
    p.add_argument("--currency", choices=["CNY", "USD"])
    p.add_argument("--confirmed-by-user", action="store_true", required=True)
    args = parser.parse_args()
    if args.action == "plan":
        if not args.name.strip() or not args.style.strip():
            raise ValueError("主体名称和风格不能为空")
        plan = build_plan(args)
        target = args.output.expanduser().resolve()
        if target.exists():
            raise FileExistsError(f"拒绝覆盖已有整套任务清单：{target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        result = {"plan": str(target), "count": plan["count"], "call_budget": plan["call_budget"]}
    elif args.action == "pack":
        result = package(args.plan, args.media_dir, args.asset_dir, args.output,
                         names_path=args.names_file, include_rewards=not args.no_reward)
    elif args.action == "bind-anchor":
        result = bind_anchor(args.plan, args.image, args.output, args.approval)
    elif args.action == "preflight":
        result, _ = batch_preflight(args.plan, args.job_root)
    elif args.action == "authorize-batch":
        result = authorize_batch(args.plan, args.job_root, args.output,
                                 max_cost=args.max_total_cost, currency=args.currency,
                                 confirmed=args.confirmed_by_user)
    else:
        result = run_batch(args.plan, args.job_root, args.batch_approval)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
