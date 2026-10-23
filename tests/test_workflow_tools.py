from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
from screen_selector import choose_screen  # noqa: E402
from artifact_manifest import record_artifact, verify_manifest  # noqa: E402


class WorkflowToolTests(unittest.TestCase):
    def test_delivery_can_live_beneath_audit_root_without_overwriting_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            media = root / "media"
            media.mkdir()
            Image.new("RGBA", (240, 240), (0, 0, 0, 0)).save(media / "01.png")
            for name in ["layout.json", "processing.json"]:
                (media / name).write_text("{}")
            for name in ["job-state.json", "prompts.json", "route.json"]:
                (root / name).write_text("{}")
            result = subprocess.run([PYTHON, str(SCRIPTS / "assemble_delivery.py"),
                "--media-dir", str(media), "--audit-dir", str(root),
                "--output", str(root / "delivered"), "--require-job-state",
                "--require-prompts", "--require-route"], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((root / "delivered/sticker-pack.zip").is_file())
            self.assertEqual((root / "job-state.json").read_text(), "{}")
            self.assertTrue((media / "01.png").is_file())

    def test_prepare_workflow_creates_one_consistent_work_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            image = root / "sheet.png"
            Image.new("RGBA", (20, 20), (255, 0, 0, 255)).save(image)
            layout = root / "layout.json"
            layout.write_text(json.dumps({"detected_layout": {"columns": 1, "rows": 1, "count": 1, "confidence": 0.99}}))
            prompts = root / "prompts.json"
            prompts.write_text(json.dumps({"detected_layout": {"columns": 1, "rows": 1, "count": 1}, "grid_video_prompt": "move"}))
            state = root / "job-state.json"
            state.write_text("{}")
            tile_plan = root / "tile-plan.json"
            tile_plan.write_text(json.dumps({"tiles": [{"id": "01", "motion": "move"}]}))
            work = root / "work"
            subprocess.run([
                PYTHON, str(ROOT / "scripts" / "prepare_workflow.py"),
                "--work-dir", str(work), "--image", str(image), "--layout", str(layout),
                "--prompts", str(prompts), "--state", str(state), "--tile-plan", str(tile_plan),
            ], check=True, stdout=subprocess.DEVNULL)
            task = json.loads((work / "video-task.json").read_text())
            self.assertEqual(Path(task["input_image"]), image.resolve())
            self.assertTrue(Path(task["output_directory"]).is_absolute())
            self.assertEqual(task["aspect_ratio"], "1:1")
            self.assertEqual(task["duration_seconds"], 6)
            self.assertEqual(task["provider_chain"], ["grok-build-local"])
            self.assertEqual(task["provider_key_colors"], {"grok-build-local": "#00FF00"})
            self.assertTrue(Path(task["provider_input_images"]["grok-build-local"]).is_file())
            self.assertEqual(
                task["provider_execution"],
                {"grok-build-local": {"duration_seconds": 6, "resolution": "720p"}},
            )
            self.assertEqual(
                task["provider_duration_seconds"],
                {"grok-build-local": 6, "xai-direct": 3},
            )
            self.assertTrue(Path(task["production_settings_file"]).is_file())
            self.assertEqual(Path(task["attempt_ledger_file"]), (work / "attempt-ledger.json").resolve())
            self.assertEqual(Path(task["artifact_manifest_file"]), (work / "artifact-manifest.json").resolve())
            manifest = json.loads((work / "artifact-manifest.json").read_text())
            self.assertGreaterEqual(len(manifest["artifacts"]), 8)
            self.assertEqual(task["max_retries"], 0)
            self.assertEqual(task["min_guard_fraction"], 0.10)
            self.assertEqual(task["max_foreground_bbox_fraction"], 0.75)
            self.assertTrue((work / "video-providers.json").is_file())
            self.assertTrue((work / "runtime-tools.json").is_file())
            providers = json.loads((work / "video-providers.json").read_text())["providers"]
            python_commands = [
                item["command"][0]
                for item in providers
                if item.get("id") in {"grok-build-local", "xai-direct"}
            ]
            self.assertEqual(python_commands, [PYTHON, PYTHON])
            capabilities = work / "capabilities.json"
            capabilities.write_text(
                json.dumps({"version": 1, "providers": [], "local_processing": {}}),
                encoding="utf-8",
            )
            subprocess.run(
                [
                    PYTHON,
                    str(ROOT / "scripts" / "route_video_provider.py"),
                    "--config",
                    str(work / "video-providers.json"),
                    "--capabilities",
                    str(capabilities),
                    "--task",
                    str(work / "video-task.json"),
                    "--output",
                    str(work / "route.json"),
                ],
                check=True,
                stdout=subprocess.DEVNULL,
            )
            self.assertTrue((work / "attempt-ledger.json").is_file())
            self.assertIn("preflight", json.loads((work / "route.json").read_text()))
            routed_manifest = json.loads((work / "artifact-manifest.json").read_text())
            routed_kinds = {
                item["kind"] for item in routed_manifest["artifacts"] if item.get("current", True)
            }
            self.assertIn("provider-route", routed_kinds)
            self.assertNotIn("attempt-ledger", routed_kinds)

    def test_prepare_workflow_can_select_xai_and_order_a_grok_fallback_per_task(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            image = root / "sheet.png"
            Image.new("RGBA", (20, 20), (255, 0, 0, 255)).save(image)
            inputs = {}
            for name, value in {
                "layout.json": {"detected_layout": {"columns": 1, "rows": 1, "count": 1, "confidence": 0.99}},
                "prompts.json": {"detected_layout": {"columns": 1, "rows": 1, "count": 1}, "grid_video_prompt": "move"},
                "job-state.json": {},
                "tile-plan.json": {"tiles": [{"id": "01", "motion": "move"}]},
            }.items():
                path = root / name
                path.write_text(json.dumps(value), encoding="utf-8")
                inputs[name] = path
            work = root / "work"
            subprocess.run(
                [
                    PYTHON, str(ROOT / "scripts" / "prepare_workflow.py"),
                    "--work-dir", str(work), "--image", str(image),
                    "--layout", str(inputs["layout.json"]), "--prompts", str(inputs["prompts.json"]),
                    "--state", str(inputs["job-state.json"]), "--tile-plan", str(inputs["tile-plan.json"]),
                    "--provider", "xai-direct", "--fallback-provider", "grok-build-local", "--allow-fallback",
                ],
                check=True,
                stdout=subprocess.DEVNULL,
            )
            task = json.loads((work / "video-task.json").read_text())
            settings = json.loads((work / "sticker-production.json").read_text())
            self.assertEqual(task["provider"], "xai-direct")
            self.assertEqual(task["provider_chain"], ["xai-direct", "grok-build-local"])
            self.assertEqual(task["duration_seconds"], 3)
            self.assertEqual(task["provider_execution"]["xai-direct"], {"duration_seconds": 3, "resolution": "720p"})
            self.assertEqual(task["provider_execution"]["grok-build-local"], {"duration_seconds": 6, "resolution": "720p"})
            self.assertTrue(task["allow_fallback"])
            self.assertEqual(settings["generation"]["provider"], "xai-direct")

    def test_non_grok_screen_selector_avoids_green_foreground(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "green-subject.png"
            image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
            for x in range(12, 52):
                for y in range(12, 52):
                    image.putpixel((x, y), (0, 255, 0, 255))
            image.save(source)
            report = choose_screen(source)
            self.assertNotEqual(report["selected"]["color"], "#00FF00")

    def test_grok_input_uses_non_green_key_for_green_subject(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            image = root / "green-subject.png"
            source = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
            ImageDraw.Draw(source).ellipse((24, 24, 104, 104), fill=(0, 255, 0, 255))
            source.save(image)
            inputs = {
                "layout.json": {"detected_layout": {"columns": 1, "rows": 1, "count": 1}},
                "prompts.json": {"detected_layout": {"columns": 1, "rows": 1, "count": 1},
                                 "background_mode": "transparent", "grid_video_prompt": "move"},
                "job-state.json": {},
                "tile-plan.json": {"tiles": [{"id": "01", "motion": "move"}]},
            }
            for name, value in inputs.items():
                (root / name).write_text(json.dumps(value), encoding="utf-8")
            work = root / "work"
            result = subprocess.run([
                PYTHON, str(SCRIPTS / "prepare_workflow.py"), "--work-dir", str(work),
                "--image", str(image), "--layout", str(root / "layout.json"),
                "--prompts", str(root / "prompts.json"), "--state", str(root / "job-state.json"),
                "--tile-plan", str(root / "tile-plan.json"),
            ], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            task = json.loads((work / "video-task.json").read_text())
            key = task["provider_key_colors"]["grok-build-local"]
            self.assertNotEqual(key, "#00FF00")
            screen = Image.open(task["provider_input_images"]["grok-build-local"]).convert("RGB")
            self.assertEqual(screen.getpixel((0, 0)), tuple(bytes.fromhex(key[1:])))
            self.assertEqual(task["screen_selection"]["policy"], "foreground-contrast-auto-or-explicit")

    def test_opaque_workflow_passes_original_scene_without_screen(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            image = root / "scene.png"
            Image.new("RGB", (128, 128), (30, 100, 140)).save(image)
            inputs = {
                "layout.json": {"detected_layout": {"columns": 1, "rows": 1, "count": 1}},
                "prompts.json": {"detected_layout": {"columns": 1, "rows": 1, "count": 1},
                                 "background_mode": "opaque", "grid_video_prompt": "preserve scene"},
                "job-state.json": {},
                "tile-plan.json": {"tiles": [{"id": "01", "motion": "move"}]},
            }
            for name, value in inputs.items():
                (root / name).write_text(json.dumps(value), encoding="utf-8")
            work = root / "work"
            result = subprocess.run([
                PYTHON, str(SCRIPTS / "prepare_workflow.py"), "--work-dir", str(work),
                "--image", str(image), "--layout", str(root / "layout.json"),
                "--prompts", str(root / "prompts.json"), "--state", str(root / "job-state.json"),
                "--tile-plan", str(root / "tile-plan.json"), "--provider", "xai-direct",
                "--background-mode", "opaque",
            ], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            task = json.loads((work / "video-task.json").read_text())
            self.assertEqual(task["background_mode"], "opaque")
            self.assertFalse(task["allow_key_background"])
            self.assertFalse(task["require_alpha"])
            self.assertEqual(task["provider_input_images"]["xai-direct"], str(image.resolve()))
            self.assertEqual(list(work.glob("input-screen-*.png")), [])

    def test_opaque_workflow_can_generate_scene_from_transparent_subject(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            image = root / "subject.png"
            source = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
            ImageDraw.Draw(source).ellipse((25, 15, 103, 113), fill=(40, 150, 80, 255))
            source.save(image)
            inputs = {
                "layout.json": {"detected_layout": {"columns": 1, "rows": 1, "count": 1}},
                "prompts.json": {"detected_layout": {"columns": 1, "rows": 1, "count": 1},
                                 "background_mode": "opaque", "scene_prompt": "阳光草地上的足球场",
                                 "grid_video_prompt": "generate scene"},
                "job-state.json": {},
                "tile-plan.json": {"tiles": [{"id": "01", "motion": "kick"}]},
            }
            for name, value in inputs.items():
                (root / name).write_text(json.dumps(value), encoding="utf-8")
            base = [
                PYTHON, str(SCRIPTS / "prepare_workflow.py"), "--work-dir", str(root / "work"),
                "--image", str(image), "--layout", str(root / "layout.json"),
                "--prompts", str(root / "prompts.json"), "--state", str(root / "job-state.json"),
                "--tile-plan", str(root / "tile-plan.json"), "--provider", "xai-direct",
                "--background-mode", "opaque",
            ]
            result = subprocess.run(base, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            task = json.loads((root / "work/video-task.json").read_text())
            self.assertEqual(task["provider_input_images"]["xai-direct"], str(image.resolve()))
            self.assertFalse(task["allow_key_background"])
            self.assertEqual(list((root / "work").glob("input-screen-*.png")), [])

            inputs["prompts.json"].pop("scene_prompt")
            (root / "prompts.json").write_text(json.dumps(inputs["prompts.json"]), encoding="utf-8")
            rejected = subprocess.run(base, capture_output=True, text=True)
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("透明主体首帧需提供 --scene-prompt", rejected.stderr)

    def test_prepare_workflow_reduces_large_alpha_subject_before_video(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            image = root / "large-subject.png"
            source = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
            ImageDraw.Draw(source).rectangle((18, 4, 110, 123), fill=(220, 60, 70, 255))
            source.save(image)
            inputs = {}
            for name, value in {
                "layout.json": {"detected_layout": {"columns": 1, "rows": 1, "count": 1, "confidence": 0.99}},
                "prompts.json": {"detected_layout": {"columns": 1, "rows": 1, "count": 1}, "grid_video_prompt": "move"},
                "job-state.json": {},
                "tile-plan.json": {"tiles": [{"id": "01", "motion": "move"}]},
            }.items():
                path = root / name
                path.write_text(json.dumps(value), encoding="utf-8")
                inputs[name] = path
            work = root / "work"
            subprocess.run([
                PYTHON, str(SCRIPTS / "prepare_workflow.py"),
                "--work-dir", str(work), "--image", str(image),
                "--layout", str(inputs["layout.json"]), "--prompts", str(inputs["prompts.json"]),
                "--state", str(inputs["job-state.json"]), "--tile-plan", str(inputs["tile-plan.json"]),
            ], check=True, stdout=subprocess.DEVNULL)
            task = json.loads((work / "video-task.json").read_text())
            screen = Image.open(task["provider_input_images"]["grok-build-local"]).convert("RGB")
            pixels = screen.load()
            points = [(x, y) for y in range(128) for x in range(128)
                      if pixels[x, y][0] > 150 and pixels[x, y][1] < 150]
            self.assertLessEqual(max(x for x, _ in points) - min(x for x, _ in points) + 1, 96)
            self.assertLessEqual(max(y for _, y in points) - min(y for _, y in points) + 1, 96)

    def test_independent_stickers_produce_numbered_media_and_zip(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs = root / "stickers"
            inputs.mkdir()
            for name, color in (("b.png", (0, 255, 0, 255)), ("a.png", (255, 0, 0, 255))):
                image = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
                ImageDraw.Draw(image).ellipse((8, 8, 24, 24), fill=color)
                image.save(inputs / name)
            output = root / "output"
            subprocess.run([
                PYTHON, str(ROOT / "scripts" / "process_independent_stickers.py"),
                str(inputs), str(output), "--fps", "2", "--duration", "0.25",
            ], check=True, stdout=subprocess.DEVNULL)
            self.assertTrue((output / "01.webp").is_file())
            self.assertTrue((output / "02.gif").is_file())
            self.assertTrue((output / "preview.png").is_file())
            with zipfile.ZipFile(output / "sticker-pack.zip") as bundle:
                self.assertIn("01.png", bundle.namelist())
                self.assertIn("preview.png", bundle.namelist())
                self.assertIn("processing.json", bundle.namelist())

    def test_independent_opaque_checkerboard_is_rejected_before_matting(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs = root / "stickers"
            inputs.mkdir()
            image = Image.new("RGB", (32, 32), (255, 255, 255))
            draw = ImageDraw.Draw(image)
            for row in range(4):
                for column in range(4):
                    if (row + column) % 2:
                        draw.rectangle((column * 8, row * 8, column * 8 + 7, row * 8 + 7), fill=(239, 239, 239))
            draw.ellipse((9, 9, 23, 23), fill=(240, 60, 80))
            image.save(inputs / "01.png")
            result = subprocess.run(
                [
                    PYTHON, str(ROOT / "scripts" / "process_independent_stickers.py"),
                    str(inputs), str(root / "output"), "--fps", "2", "--duration", "0.25",
                ],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("uniform edge background", result.stderr + result.stdout)

    def test_local_fallback_rejects_unapproved_revision(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            image = root / "sheet.png"
            Image.new("RGBA", (20, 20), (255, 0, 0, 255)).save(image)
            layout = root / "layout.json"
            layout.write_text(json.dumps({"detected_layout": {"columns": 1, "rows": 1, "count": 1, "confidence": 0.99}}))
            prompt = root / "static-prompt.json"
            prompt.write_text(json.dumps({"static_sheet_prompt": "static"}))
            anchor_approval = root / "subject-anchor-approval.json"
            subprocess.run([
                PYTHON, str(ROOT / "scripts" / "subject_anchor.py"),
                "--image", str(image), "--output", str(anchor_approval), "--confirmed-by-user",
            ], check=True, stdout=subprocess.DEVNULL)
            prompt.write_text(json.dumps({"static_sheet_prompt": "static", "reference_image": {
                "path": str(image), "sha256": json.loads(anchor_approval.read_text())["sha256"]}}))
            state = root / "job-state.json"
            subprocess.run([
                PYTHON, str(ROOT / "scripts" / "manage_job_state.py"), "create",
                "--image", str(image), "--layout", str(layout), "--static-prompt", str(prompt),
                "--anchor-approval", str(anchor_approval), "--output", str(state),
            ], check=True, stdout=subprocess.DEVNULL)
            result = subprocess.run([
                PYTHON, str(ROOT / "scripts" / "keyframe_fallback.py"), str(image), str(root / "output"),
                "--state", str(state), "--layout", str(layout),
            ], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("has not been approved", result.stderr + result.stdout)

    def test_delivery_assembler_includes_audit_files_in_zip(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            media = root / "media"
            audit = root / "audit"
            media.mkdir()
            audit.mkdir()
            for suffix in ("png", "webp", "gif"):
                (media / f"01.{suffix}").write_bytes(b"media")
            (media / "layout.json").write_text(json.dumps({"detected_layout": {"columns": 1, "rows": 1, "count": 1, "confidence": 1.0}}))
            (media / "processing.json").write_text("{}")
            short = media / "3s"
            short.mkdir()
            (short / "01.gif").write_bytes(b"short-media")
            (short / "processing.json").write_text("{}")
            (short / "sticker-pack.zip").write_bytes(b"redundant nested archive")
            for name in (
                "job-state.json",
                "prompts.json",
                "route.json",
                "static-prompt.json",
                "static-generation.json",
                "static-alpha.json",
                "artifact-manifest.json",
                "attempt-ledger.json",
            ):
                (audit / name).write_text("{}")
            keypose_audit = audit / "keyposes"
            keypose_audit.mkdir()
            (keypose_audit / "keypose-plan.json").write_text("{\"mode\": \"keypose-local\"}")
            (keypose_audit / "keypose-preparation.json").write_text("{\"mode\": \"keypose-local-preparation\"}")
            output = root / "delivered"
            subprocess.run([
                PYTHON, str(ROOT / "scripts" / "assemble_delivery.py"),
                "--media-dir", str(media), "--audit-dir", str(audit), "--output", str(output),
                "--require-job-state", "--require-prompts", "--require-route",
            ], check=True, stdout=subprocess.DEVNULL)
            with zipfile.ZipFile(output / "sticker-pack.zip") as bundle:
                self.assertTrue(
                    {
                        "job-state.json",
                        "prompts.json",
                        "route.json",
                        "static-prompt.json",
                        "static-generation.json",
                        "static-alpha.json",
                        "artifact-manifest.json",
                        "attempt-ledger.json",
                        "keypose-plan.json",
                        "keypose-preparation.json",
                        "3s/01.gif",
                        "3s/processing.json",
                    }.issubset(bundle.namelist())
                )
                self.assertNotIn("3s/sticker-pack.zip", bundle.namelist())
            self.assertFalse((output / "3s" / "sticker-pack.zip").exists())

    def test_delivery_assembler_can_remove_intermediate_media(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            media = root / "media"
            audit = root / "audit"
            media.mkdir()
            audit.mkdir()
            for suffix in ("png", "webp", "gif"):
                (media / f"01.{suffix}").write_bytes(b"media")
            (media / "layout.json").write_text("{}")
            (media / "processing.json").write_text("{}")
            manifest = audit / "artifact-manifest.json"
            record_artifact(manifest, media / "01.webp", kind="sticker-output", stage="processed")
            output = root / "delivered"
            subprocess.run([
                PYTHON, str(ROOT / "scripts" / "assemble_delivery.py"),
                "--media-dir", str(media), "--audit-dir", str(audit),
                "--output", str(output), "--cleanup-media-dir",
            ], check=True, stdout=subprocess.DEVNULL)
            self.assertFalse(media.exists())
            self.assertTrue((output / "sticker-pack.zip").is_file())
            self.assertTrue(verify_manifest(output / "artifact-manifest.json")["valid"])

    def test_prompt_only_delivery_is_explicitly_non_video(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs = []
            for name in ("static-prompt.json", "tile-plan.json", "prompts.json"):
                path = root / name
                path.write_text("{}")
                inputs.append(path)
            route = root / "route.json"
            route.write_text(json.dumps({
                "selected": {"id": "prompt-only", "driver": "none"},
                "attempts": [],
                "preflight": {"selected_provider": "prompt-only"},
            }))
            output = root / "prompt-only"
            subprocess.run([
                PYTHON, str(ROOT / "scripts" / "assemble_prompt_only.py"),
                "--static-prompt", str(inputs[0]), "--tile-plan", str(inputs[1]),
                "--prompts", str(inputs[2]), "--route", str(route), "--output", str(output),
            ], check=True, stdout=subprocess.DEVNULL)
            report = json.loads((output / "prompt-only.json").read_text())
            self.assertFalse(report["generated_video"])
            with zipfile.ZipFile(output / "prompt-only.zip") as bundle:
                self.assertIn("route.json", bundle.namelist())


if __name__ == "__main__":
    unittest.main()
