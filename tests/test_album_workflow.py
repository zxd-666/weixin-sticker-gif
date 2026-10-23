"""Offline checks for the full-album plan and final GIF acceptance gate."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import unittest
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from album_workflow import bind_anchor, build_plan, package, reactions_from_text, run_batch  # noqa: E402
from manage_job_state import create_state, verify_state  # noqa: E402
from subject_anchor import approve, verify_approval  # noqa: E402


class AlbumWorkflowTests(unittest.TestCase):
    def make_assets(self, root: Path, *, rewards: bool = True) -> Path:
        assets = root / "album-assets"
        assets.mkdir()
        Image.new("RGB", (750, 400), "#ffae67").save(assets / "详情页横幅.png")
        for name, size in (("表情封面", (240, 240)), ("聊天页图标", (50, 50))):
            image = Image.new("RGBA", size, (0, 0, 0, 0))
            image.putpixel((size[0] // 2, size[1] // 2), (255, 0, 0, 255))
            image.save(assets / f"{name}.png")
        if rewards:
            Image.new("RGB", (750, 560), "#ffae67").save(assets / "赞赏引导图.png")
            Image.new("RGB", (750, 750), "#ffae67").save(assets / "赞赏致谢图.png")
        return assets

    def make_anchor_approval(self, root: Path, image: Path | None = None) -> Path:
        image = image or root / "anchor.png"
        if not image.exists():
            Image.new("RGBA", (32, 32), "red").save(image)
        receipt = root / "subject-anchor-approval.json"
        approve(image, receipt, confirmed_by_user=True)
        return receipt

    def make_plan(self, root: Path, reactions: str | None = None,
                  background_mode: str = "transparent") -> tuple[dict, Path]:
        args = argparse.Namespace(name="小猫", subject_description="黑猫，黄眼睛", reference_image=None,
                                  approved_anchor=None, subject_type="fictional", style="2D 手绘",
                                  reactions=reactions, background_mode=background_mode)
        plan = build_plan(args)
        path = root / "album-plan.json"
        path.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
        return plan, path

    def write_gif(self, path: Path, *, loop: int = 0, opaque: bool = False) -> None:
        frames = ([Image.new("RGB", (240, 240), "red"), Image.new("RGB", (240, 240), "blue")]
                  if opaque else [Image.new("RGBA", (240, 240), (255, 0, 0, 0)),
                                  Image.new("RGBA", (240, 240), (0, 0, 255, 255))])
        frames[0].save(path, save_all=True, append_images=frames[1:], duration=120, loop=loop)

    def test_pack_accepts_scene_album_and_rejects_mixed_background(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan, plan_path = self.make_plan(root, background_mode="opaque")
            media = root / "media"
            media.mkdir()
            for item in plan["items"]:
                self.write_gif(media / f"{item['id']}.gif", opaque=True)
            assets = self.make_assets(root)
            result = package(plan_path, media, assets, root / "scene-delivery")
            self.assertEqual(result["background_mode"], "opaque")
            self.assertEqual(result["count"], 8)
            self.write_gif(media / "01.gif")
            with self.assertRaisesRegex(ValueError, "出现透明像素"):
                package(plan_path, media, assets, root / "mixed-delivery")

    def test_plan_exact_count_and_distinct_actions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            plan, _ = self.make_plan(Path(temporary), ",".join(f"动作{i}" for i in range(10)))
            self.assertEqual(plan["count"], 10)
            self.assertEqual([g["layout"]["columns"] * g["layout"]["rows"] for g in plan["static_groups"]], [4, 4, 2])
            self.assertEqual(plan["call_budget"]["video_calls"], 10)
            self.assertEqual(plan["call_budget"]["auxiliary_image_calls_max"], 5)
            self.assertEqual(plan["call_budget"]["extra_fee_status"], "unverified")
        with self.assertRaises(ValueError):
            reactions_from_text("收到,大笑,抱抱")
        with self.assertRaises(ValueError):
            reactions_from_text("收到," * 8)

    def test_pack_requires_complete_valid_album(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan, plan_path = self.make_plan(root)
            assets = self.make_assets(root)
            media = root / "media"
            media.mkdir()
            for item in plan["items"]:
                self.write_gif(media / f"{item['id']}.gif")
            (media / "08.gif").unlink()
            with self.assertRaisesRegex(ValueError, "缺少"):
                package(plan_path, media, assets, root / "delivered")
            self.write_gif(media / "08.gif", loop=1)
            with self.assertRaisesRegex(ValueError, "无限循环"):
                package(plan_path, media, assets, root / "delivered")
            self.write_gif(media / "08.gif")
            result = package(plan_path, media, assets, root / "delivered")
            self.assertEqual(result["count"], 8)
            with zipfile.ZipFile(result["zip"]) as archive:
                self.assertEqual(len(archive.namelist()), 13)
                self.assertIn("表情/收到.gif", archive.namelist())
                self.assertIn("详情页横幅.png", archive.namelist())
                self.assertIn("赞赏致谢图.png", archive.namelist())
                self.assertNotIn("validation.json", archive.namelist())
                self.assertIsNone(archive.testzip())
            with self.assertRaises(FileExistsError):
                package(plan_path, media, assets, root / "delivered")

    def test_pack_requires_reward_pair_by_default_and_chinese_names(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan, plan_path = self.make_plan(root)
            assets = self.make_assets(root, rewards=False)
            media = root / "media"
            media.mkdir()
            for item in plan["items"]:
                self.write_gif(media / f"{item['id']}.gif")
            with self.assertRaisesRegex(ValueError, "赞赏引导图"):
                package(plan_path, media, assets, root / "delivered")
            names = root / "names.json"
            names.write_text(json.dumps({**{item["id"]: item["reaction"] for item in plan["items"]},
                                         "01": "ok"}, ensure_ascii=False))
            with self.assertRaisesRegex(ValueError, "中文主题名"):
                package(plan_path, media, assets, root / "delivered", names_path=names,
                        include_rewards=False)
            names.write_text(json.dumps({**{item["id"]: item["reaction"] for item in plan["items"]},
                                         "01": "明白"}, ensure_ascii=False))
            custom = package(plan_path, media, assets, root / "custom-delivery", names_path=names,
                             include_rewards=False)
            with zipfile.ZipFile(custom["zip"]) as archive:
                self.assertIn("表情/明白.gif", archive.namelist())
            result = package(plan_path, media, assets, root / "delivered", include_rewards=False)
            with zipfile.ZipFile(result["zip"]) as archive:
                self.assertEqual(len(archive.namelist()), 11)
                self.assertNotIn("赞赏引导图.png", archive.namelist())

    def test_pack_rejects_path_characters_in_album_name(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan, plan_path = self.make_plan(root)
            plan["name"] = "../小猫"
            plan_path.write_text(json.dumps(plan, ensure_ascii=False))
            media = root / "media"
            media.mkdir()
            assets = self.make_assets(root)
            with self.assertRaisesRegex(ValueError, "路径字符"):
                package(plan_path, media, assets, root / "delivered")
            self.assertFalse((root / "delivered").exists())

    def test_batch_does_not_submit_when_total_cost_approval_is_wrong(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            approval = root / "album-execution-approval.json"
            approval.write_text(json.dumps({"version": 1, "kind": "album-execution-approval",
                                            "confirmed_by_user": True,
                                            "confirmed_at": datetime.now(timezone.utc).isoformat(),
                                            "plan_sha256": "plan", "approval_sha256": {"01": "task"},
                                            "count": 1, "max_total_extra_cost": 4, "currency": "CNY"}))
            report = {"plan_sha256": "plan", "approval_sha256": {"01": "task"},
                      "count": 1, "maximum_extra_cost": 5, "currency": "CNY"}
            with patch("album_workflow.batch_preflight", return_value=(report, [{"id": "01", "status": "ready"}])), \
                    patch("album_workflow.execute_attempt") as execute:
                with self.assertRaisesRegex(ValueError, "费用确认"):
                    run_batch(root / "album-plan.json", root, approval)
                execute.assert_not_called()

    def test_one_click_static_state_is_bound_to_album_and_exact_image(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, plan_path = self.make_plan(root)
            image = root / "static.png"
            Image.new("RGBA", (240, 240), (255, 0, 0, 0)).save(image)
            layout = root / "layout.json"
            layout.write_text(json.dumps({"detected_layout": {"columns": 1, "rows": 1,
                                                               "count": 1, "confidence": 1.0}}))
            prompt = root / "static-prompt.json"
            prompt.write_text("{}")
            anchor_approval = self.make_anchor_approval(root)
            prompt.write_text(json.dumps({"reference_image": {
                "path": str(root / "anchor.png"),
                "sha256": json.loads(anchor_approval.read_text())["sha256"]}}))
            with self.assertRaisesRegex(ValueError, "direct-completion"):
                create_state(image, layout, prompt, "album-generated", album_plan=plan_path,
                             album_item="01", anchor_approval=anchor_approval)
            state = create_state(image, layout, prompt, "album-generated", album_plan=plan_path,
                                 album_item="01", direct_completion_authorized=True,
                                 anchor_approval=anchor_approval)
            self.assertEqual(state["approval"]["kind"], "album-direct-completion")
            self.assertTrue(verify_state(state, image, layout)["valid"])
            Image.new("RGBA", (240, 240), (0, 0, 255, 0)).save(image)
            with self.assertRaisesRegex(ValueError, "approved static revision"):
                verify_state(state, image, layout)

    def test_direct_generated_sample_requires_user_instruction_and_binds_image(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            image = root / "static.png"
            Image.new("RGBA", (240, 240), (255, 0, 0, 0)).save(image)
            layout = root / "layout.json"
            layout.write_text(json.dumps({"detected_layout": {"columns": 1, "rows": 1,
                                                               "count": 1, "confidence": 1.0}}))
            prompt = root / "static-prompt.json"
            prompt.write_text("{}")
            anchor_approval = self.make_anchor_approval(root)
            prompt.write_text(json.dumps({"reference_image": {
                "path": str(root / "anchor.png"),
                "sha256": json.loads(anchor_approval.read_text())["sha256"]}}))
            with self.assertRaisesRegex(ValueError, "static prompt"):
                create_state(image, layout, None, "generated-direct", direct_completion_authorized=True,
                             anchor_approval=anchor_approval)
            with self.assertRaisesRegex(ValueError, "direct-completion"):
                create_state(image, layout, prompt, "generated-direct", anchor_approval=anchor_approval)
            with self.assertRaisesRegex(ValueError, "subject anchor"):
                create_state(image, layout, prompt, "generated-direct", direct_completion_authorized=True)
            wrong_prompt = root / "wrong-prompt.json"
            wrong_prompt.write_text(json.dumps({"reference_image": {"path": str(root / "anchor.png"),
                                                                       "sha256": "wrong"}}))
            with self.assertRaisesRegex(ValueError, "must reference the confirmed"):
                create_state(image, layout, wrong_prompt, "generated-direct",
                             direct_completion_authorized=True, anchor_approval=anchor_approval)
            state = create_state(image, layout, prompt, "generated-direct",
                                 direct_completion_authorized=True, anchor_approval=anchor_approval)
            self.assertEqual(state["phase"], "static-approved")
            self.assertEqual(state["approval"]["kind"], "user-requested-direct-completion")
            self.assertTrue(verify_state(state, image, layout)["valid"])
            Image.new("RGBA", (240, 240), (0, 0, 255, 0)).save(image)
            with self.assertRaisesRegex(ValueError, "approved static revision"):
                verify_state(state, image, layout)

    def test_reused_anchor_must_match_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "anchor.png"
            Image.new("RGBA", (32, 32), "red").save(source)
            args = argparse.Namespace(name="小猫", subject_description=None, reference_image=None,
                                      approved_anchor=source, subject_type="fictional", style="2D 手绘",
                                      reactions=None, background_mode="transparent")
            plan = build_plan(args)
            plan_path = root / "album-plan.json"
            plan_path.write_text(json.dumps(plan, ensure_ascii=False))
            approval = self.make_anchor_approval(root, source)
            record = bind_anchor(plan_path, source, root / "album-anchor.json", approval)
            self.assertEqual(record["sha256"], plan["subject"]["reference"]["sha256"])
            other = root / "other.png"
            Image.new("RGBA", (32, 32), "blue").save(other)
            with self.assertRaisesRegex(ValueError, "主体图未获用户确认"):
                bind_anchor(plan_path, other, root / "wrong-anchor.json", approval)

    def test_anchor_approval_is_required_and_revoked_by_image_change(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, plan_path = self.make_plan(root)
            image = root / "anchor.png"
            Image.new("RGBA", (32, 32), "red").save(image)
            with self.assertRaisesRegex(ValueError, "明确确认"):
                approve(image, root / "unapproved.json", confirmed_by_user=False)
            with self.assertRaises(FileNotFoundError):
                bind_anchor(plan_path, image, root / "album-anchor.json", root / "missing.json")
            approval = self.make_anchor_approval(root, image)
            bind_anchor(plan_path, image, root / "album-anchor.json", approval)
            Image.new("RGBA", (32, 32), "blue").save(image)
            with self.assertRaisesRegex(ValueError, "发生变化"):
                verify_approval(approval, image)


if __name__ == "__main__":
    unittest.main()
