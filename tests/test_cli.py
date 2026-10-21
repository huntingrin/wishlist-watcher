from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WATCH = ROOT / "scripts" / "watch.py"


class CliTests(unittest.TestCase):
    def run_cli(self, *args, state_dir=None, env=None):
        command = [sys.executable, str(WATCH), *args]
        if state_dir:
            command.extend(["--state-dir", state_dir])
        return subprocess.run(
            command,
            cwd=str(ROOT),
            text=True,
            capture_output=True,
            check=False,
            env=env,
        )

    def test_demo_is_offline_and_contains_trigger_card(self):
        result = self.run_cli("demo", "--format", "markdown")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("离线演示", result.stdout)
        self.assertIn("【值得买】", result.stdout)
        self.assertIn("目标价 8000", result.stdout)

    def test_welcome_is_stable_and_marks_first_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = self.run_cli("welcome", "--format", "json", state_dir=tmp)
            self.assertEqual(first.returncode, 0, first.stderr)
            payload = json.loads(first.stdout)
            self.assertTrue(payload["first_run"])
            self.assertIn("盯价", payload["message"])

            marked = self.run_cli("welcome", "--mark", "--format", "json", state_dir=tmp)
            self.assertEqual(marked.returncode, 0, marked.stderr)

            second = self.run_cli("welcome", "--format", "json", state_dir=tmp)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertFalse(json.loads(second.stdout)["first_run"])

    def test_doctor_reports_missing_key_without_crashing(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = {**os.environ, "HAINA_API_KEY": ""}
            result = self.run_cli("doctor", "--format", "json", state_dir=tmp, env=env)
            # Missing Key is a required failure, but the command still returns JSON.
            self.assertEqual(result.returncode, 1)
            payload = json.loads(result.stdout)
            self.assertFalse(payload["ok"])
            names = {check["name"]: check for check in payload["checks"]}
            self.assertIn("python", names)
            self.assertIn("state_dir", names)
            self.assertIn("api_key", names)
            self.assertFalse(names["api_key"]["ok"])

    def test_add_without_key_fails_cleanly(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = {**os.environ, "HAINA_API_KEY": ""}
            result = self.run_cli(
                "add",
                "索尼 A7C2",
                "--target",
                "8000",
                "--format",
                "json",
                state_dir=tmp,
                env=env,
            )
            self.assertEqual(result.returncode, 1)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["status"], "error")
            self.assertIn("HAINA_API_KEY", payload["error"])

    def test_feedback_bought_archives_item(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = {
                "version": 1,
                "onboarded_at": "2026-10-21T12:00:00+08:00",
                "items": [
                    {
                        "id": "w_test",
                        "status": "active",
                        "product": {"title": "测试商品"},
                        "target_price_cents": 100,
                        "last_price_cents": 90,
                    }
                ],
            }
            (Path(tmp) / "watchlist.json").write_text(
                json.dumps(state, ensure_ascii=False), encoding="utf-8"
            )
            result = self.run_cli(
                "feedback",
                "w_test",
                "--action",
                "bought",
                "--format",
                "json",
                state_dir=tmp,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["item"]["status"], "bought")
            saved = json.loads((Path(tmp) / "watchlist.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["items"][0]["status"], "bought")
            self.assertTrue(saved["items"][0]["feedback"])

    def test_check_inactive_item_is_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = {
                "version": 1,
                "onboarded_at": "2026-10-21T12:00:00+08:00",
                "items": [
                    {
                        "id": "w_test",
                        "status": "bought",
                        "product": {"title": "测试商品"},
                        "target_price_cents": 100,
                        "last_price_cents": 90,
                    }
                ],
            }
            (Path(tmp) / "watchlist.json").write_text(
                json.dumps(state, ensure_ascii=False), encoding="utf-8"
            )
            env = {**os.environ, "HAINA_API_KEY": ""}
            result = self.run_cli(
                "check",
                "--id",
                "w_test",
                "--format",
                "json",
                state_dir=tmp,
                env=env,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["checked"], 0)
            self.assertIn("bought", payload["message"])

    def test_add_can_use_pending_candidates_without_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            candidate = {
                "candidate_id": "abc123",
                "title": "测试商品 单机身",
                "url": "https://example.com/item",
                "image": "",
                "mall": "京东",
                "shop": "测试旗舰店",
                "brand": "测试品牌",
                "price_cents": 9000,
                "page_price_cents": 10000,
                "price_tags": [],
                "historical_low_cents": None,
                "low_30d_cents": None,
                "usual_price_cents": None,
                "promo_price_cents": None,
                "below_promo": False,
            }
            pending = {
                "query": "测试商品",
                "target_price_cents": 9500,
                "target_raw": "95",
                "deadline": None,
                "size": 5,
                "candidates": [candidate],
                "created_at": "2026-10-21T12:00:00+08:00",
            }
            (Path(tmp) / "pending-add.json").write_text(
                json.dumps(pending, ensure_ascii=False), encoding="utf-8"
            )
            env = {**os.environ, "HAINA_API_KEY": ""}
            result = self.run_cli(
                "add",
                "测试商品",
                "--target",
                "95",
                "--pick",
                "1",
                "--format",
                "json",
                state_dir=tmp,
                env=env,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["status"], "created")
            self.assertEqual(payload["item"]["product"]["title"], "测试商品 单机身")
            self.assertFalse((Path(tmp) / "pending-add.json").exists())
            saved = json.loads((Path(tmp) / "watchlist.json").read_text(encoding="utf-8"))
            self.assertEqual(len(saved["items"]), 1)

    def test_login_saves_proxy_config_without_echoing_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = {**os.environ, "HAINA_API_KEY": "", "WISHLIST_PROXY_TOKEN": ""}
            result = self.run_cli(
                "login",
                "--url",
                "https://proxy.example",
                "--token",
                "invite-123456",
                "--format",
                "json",
                state_dir=tmp,
                env=env,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn("invite-123456", result.stdout)
            config_path = Path(tmp) / "proxy.json"
            self.assertTrue(config_path.is_file())
            config = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertEqual(config["token"], "invite-123456")
            self.assertEqual(config["url"], "https://proxy.example")

            doctor = self.run_cli("doctor", "--format", "json", state_dir=tmp, env=env)
            self.assertEqual(doctor.returncode, 0, doctor.stderr)
            doctor_payload = json.loads(doctor.stdout)
            self.assertEqual(doctor_payload["mode"], "proxy")
            self.assertTrue(doctor_payload["ok"])

            logout = self.run_cli("logout", "--format", "json", state_dir=tmp, env=env)
            self.assertEqual(logout.returncode, 0, logout.stderr)
            self.assertFalse(config_path.exists())


if __name__ == "__main__":
    unittest.main()
