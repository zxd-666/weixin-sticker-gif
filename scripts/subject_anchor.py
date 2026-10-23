"""Hash-bound confirmation for a single generated subject image."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_approval(approval_path: Path, image: Path | None = None) -> dict:
    approval = json.loads(approval_path.expanduser().resolve(strict=True).read_text(encoding="utf-8"))
    if not isinstance(approval, dict):
        raise ValueError("主体确认记录无效")
    recorded = Path(approval.get("image", ""))
    if (approval.get("version") != 1 or approval.get("kind") != "subject-anchor-approval"
            or approval.get("confirmed_by_user") is not True or not recorded.is_file()
            or approval.get("sha256") != sha256(recorded)
            or (image is not None and (image.expanduser().resolve(strict=True) != recorded.resolve()
                                       or sha256(image) != approval["sha256"]))):
        raise ValueError("主体图未获用户确认，或已发生变化")
    return approval


def approve(image: Path, output: Path, *, confirmed_by_user: bool) -> dict:
    if not confirmed_by_user:
        raise ValueError("须先向用户展示唯一主体图并获得对这张图的明确确认")
    image = image.expanduser().resolve(strict=True)
    with Image.open(image) as opened:
        opened.verify()
    output = output.expanduser().resolve()
    if output.exists():
        raise FileExistsError(f"拒绝覆盖主体确认记录：{output}")
    record = {"version": 1, "kind": "subject-anchor-approval", "confirmed_by_user": True,
              "confirmed_at": datetime.now(timezone.utc).isoformat(), "image": str(image),
              "sha256": sha256(image)}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description="在用户明确确认单张主体图后，记录其图片哈希")
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--confirmed-by-user", action="store_true", required=True)
    args = parser.parse_args()
    print(json.dumps(approve(args.image, args.output, confirmed_by_user=args.confirmed_by_user), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
