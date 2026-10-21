from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from store import (  # noqa: E402
    StateError,
    clear_pending,
    find_item,
    load_pending,
    load_state,
    save_pending,
    save_state,
)


class StoreTests(unittest.TestCase):
    def test_empty_state_when_file_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = load_state(Path(tmp))
            self.assertEqual(state["version"], 1)
            self.assertIsNone(state["onboarded_at"])
            self.assertEqual(state["items"], [])

    def test_round_trip_and_unicode(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            state = load_state(state_dir)
            state["onboarded_at"] = "2026-10-21T12:00:00+08:00"
            state["items"].append({"id": "w_1", "title": "索尼 A7C2"})
            save_state(state_dir, state)

            loaded = load_state(state_dir)
            self.assertEqual(loaded["items"][0]["title"], "索尼 A7C2")
            self.assertEqual(loaded["onboarded_at"], "2026-10-21T12:00:00+08:00")

    def test_find_by_exact_and_unique_prefix(self):
        state = {"items": [{"id": "w_abc123"}, {"id": "w_def456"}]}
        self.assertEqual(find_item(state, "w_abc123")["id"], "w_abc123")
        self.assertEqual(find_item(state, "w_abc")["id"], "w_abc123")
        with self.assertRaises(StateError):
            find_item(state, "w_zzz")

    def test_invalid_json_raises_state_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "watchlist.json"
            path.write_text("{not json", encoding="utf-8")
            with self.assertRaises(StateError):
                load_state(Path(tmp))

    def test_save_leaves_no_temp_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            save_state(state_dir, load_state(state_dir))
            leftovers = [p.name for p in state_dir.iterdir() if p.name.startswith(".watchlist-")]
            self.assertEqual(leftovers, [])
            self.assertTrue((state_dir / "watchlist.json").is_file())
            json.loads((state_dir / "watchlist.json").read_text(encoding="utf-8"))

    def test_pending_candidates_round_trip_and_clear(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            payload = {"query": "索尼 A7C2", "candidates": [{"title": "测试"}]}
            save_pending(state_dir, payload)
            self.assertEqual(load_pending(state_dir)["query"], "索尼 A7C2")
            clear_pending(state_dir)
            self.assertIsNone(load_pending(state_dir))
            clear_pending(state_dir)  # idempotent


if __name__ == "__main__":
    unittest.main()
