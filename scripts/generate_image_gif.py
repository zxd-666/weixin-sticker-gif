#!/usr/bin/env python3
"""Submit one approved GPT Image 2.6 text-to-GIF request to the Image API."""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import os
import tempfile
import urllib.request
from pathlib import Path

from PIL import Image


MODELS = {"gpt-image-2.6-sunburst", "gpt-image-2.6-flare"}
ENDPOINT = "https://api.openai.com/v1/images/generations"


def request_payload(prompt: str, *, model: str, frame_count: int,
                    frame_duration_ms: int, size: str, quality: str) -> dict:
    if model not in MODELS or not 2 <= frame_count <= 16 or not 20 <= frame_duration_ms <= 2000:
        raise ValueError("模型、GIF 帧数或帧时长无效")
    if size != "auto":
        try:
            width, height = (int(value) for value in size.lower().split("x"))
        except (ValueError, TypeError):
            raise ValueError("尺寸须为 auto 或 WIDTHxHEIGHT") from None
        if width <= 0 or height <= 0 or width % 16 or height % 16:
            raise ValueError("GIF 每帧宽高须为正数且是 16 的倍数")
    if quality not in {"low", "medium", "high", "xhigh", "max"} or not prompt.strip():
        raise ValueError("画质或提示词无效")
    return {"model": model, "prompt": prompt.strip(), "output_format": "gif",
            "frame_count": frame_count, "frame_duration_ms": frame_duration_ms,
            "size": size, "quality": quality, "n": 1}


def generate(prompt_path: Path, output: Path, *, model: str = "gpt-image-2.6-sunburst",
             frame_count: int = 9, frame_duration_ms: int = 200,
             size: str = "auto", quality: str = "medium",
             cost_confirmed: bool = False, receipt_path: Path | None = None) -> dict:
    if not cost_confirmed:
        raise ValueError("提交可能计费的图像请求前须确认本次费用范围")
    prompt_path = prompt_path.expanduser().resolve(strict=True)
    output = output.expanduser().resolve()
    receipt_path = (receipt_path or output.with_suffix(".receipt.json")).expanduser().resolve()
    if output.exists() or receipt_path.exists() or output == receipt_path:
        raise FileExistsError(f"拒绝覆盖已有 GIF 或收据：{output} / {receipt_path}")
    prompt = prompt_path.read_text(encoding="utf-8")
    payload = request_payload(prompt, model=model, frame_count=frame_count,
                              frame_duration_ms=frame_duration_ms, size=size, quality=quality)
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("当前进程没有 OPENAI_API_KEY；未提交请求")
    request = urllib.request.Request(
        ENDPOINT, data=json.dumps(payload).encode("utf-8"), method="POST",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        result = json.load(response)
    data = result.get("data") or []
    if len(data) != 1 or not isinstance(data[0].get("b64_json"), str):
        raise ValueError("Image API 未返回一张可解码的 GIF")
    gif = base64.b64decode(data[0]["b64_json"], validate=True)
    if not gif.startswith((b"GIF87a", b"GIF89a")):
        raise ValueError("Image API 返回的内容不是 GIF")
    with Image.open(io.BytesIO(gif)) as image:
        if image.n_frames < 2:
            raise ValueError("Image API 返回的 GIF 没有实际动画帧")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=output.parent, suffix=".gif", delete=False) as file:
            temporary = Path(file.name)
            file.write(gif)
        temporary.replace(output)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    receipt = {"model": model, "endpoint": ENDPOINT, "output": str(output),
               "bytes": len(gif), "sha256": hashlib.sha256(gif).hexdigest(),
               "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
               "requested": {"frame_count": frame_count, "frame_duration_ms": frame_duration_ms,
                             "size": size, "quality": quality}, "usage": result.get("usage")}
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {**receipt, "receipt": str(receipt_path)}


def main() -> int:
    parser = argparse.ArgumentParser(description="发起一次已核对费用的 GPT Image 2.6 GIF 生成")
    parser.add_argument("--prompt-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, help="默认在 GIF 旁生成 .receipt.json")
    parser.add_argument("--model", choices=sorted(MODELS), default="gpt-image-2.6-sunburst")
    parser.add_argument("--frame-count", type=int, default=9)
    parser.add_argument("--frame-duration-ms", type=int, default=200)
    parser.add_argument("--size", default="auto")
    parser.add_argument("--quality", choices=["low", "medium", "high", "xhigh", "max"], default="medium")
    parser.add_argument("--cost-confirmed", action="store_true")
    args = parser.parse_args()
    print(json.dumps(generate(args.prompt_file, args.output, model=args.model,
                              frame_count=args.frame_count, frame_duration_ms=args.frame_duration_ms,
                              size=args.size, quality=args.quality,
                              cost_confirmed=args.cost_confirmed, receipt_path=args.receipt),
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
