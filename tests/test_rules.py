from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "wishlist-watcher" / "scripts"))

from haina import format_cents, price_to_cents  # noqa: E402
from rules import apply_check, evaluate, snooze  # noqa: E402


def make_item(**overrides):
    item = {
        "id": "w_test",
        "status": "active",
        "target_price_cents": 800000,
        "lowest_seen_cents": 850000,
        "last_price_cents": 850000,
        "last_alert_at": None,
        "snooze_until": None,
        "deadline": None,
        "checks": [],
    }
    item.update(overrides)
    return item


def make_current(**overrides):
    current = {
        "price_cents": 850000,
        "page_price_cents": 1000000,
        "match_status": "matched",
        "checked_at": "2026-10-21T12:00:00+08:00",
    }
    current.update(overrides)
    return current


class PriceTests(unittest.TestCase):
    def test_parses_number_and_currency_strings(self):
        self.assertEqual(price_to_cents(7996.11), 799611)
        self.assertEqual(price_to_cents("¥8,531.45"), 853145)
        self.assertEqual(price_to_cents("7996元"), 799600)

    def test_rejects_empty_and_ranges(self):
        self.assertIsNone(price_to_cents(""))
        self.assertIsNone(price_to_cents(None))
        self.assertIsNone(price_to_cents("7996-8199"))

    def test_formats_cents(self):
        self.assertEqual(format_cents(799611), "¥7,996.11")
        self.assertEqual(format_cents(None), "—")


class RuleTests(unittest.TestCase):
    def test_target_price_triggers(self):
        result = evaluate(make_item(), make_current(price_cents=800000))
        self.assertTrue(result["trigger"])
        self.assertEqual(result["reason"], "target")
        self.assertEqual(result["diff_cents"], 0)

    def test_below_target_triggers(self):
        result = evaluate(make_item(), make_current(price_cents=790000))
        self.assertTrue(result["trigger"])
        self.assertEqual(result["diff_cents"], 10000)

    def test_new_low_triggers_only_when_strictly_lower(self):
        result = evaluate(
            make_item(target_price_cents=700000),
            make_current(price_cents=840000),
        )
        self.assertTrue(result["trigger"])
        self.assertEqual(result["reason"], "new_low")
        self.assertEqual(result["diff_cents"], 10000)

    def test_equal_to_lowest_does_not_trigger(self):
        result = evaluate(
            make_item(target_price_cents=700000),
            make_current(price_cents=850000),
        )
        self.assertFalse(result["trigger"])
        self.assertEqual(result["reason"], "not_met")

    def test_cooldown_suppresses_alert(self):
        now = datetime.now().astimezone()
        item = make_item(last_alert_at=(now - timedelta(hours=1)).isoformat())
        result = evaluate(item, make_current(price_cents=790000), now=now)
        self.assertFalse(result["trigger"])
        self.assertEqual(result["reason"], "cooldown")

    def test_snooze_suppresses_alert(self):
        now = datetime.now().astimezone()
        item = make_item(snooze_until=(now + timedelta(days=1)).isoformat())
        result = evaluate(item, make_current(price_cents=790000), now=now)
        self.assertFalse(result["trigger"])
        self.assertEqual(result["reason"], "snoozed")

    def test_deadline_expires_item(self):
        now = datetime.now().astimezone()
        item = make_item(deadline=(now.date() - timedelta(days=1)).isoformat())
        result = evaluate(item, make_current(price_cents=790000), now=now)
        self.assertFalse(result["trigger"])
        self.assertEqual(result["reason"], "expired")
        self.assertTrue(result["expire"])

    def test_missing_price_never_alerts(self):
        result = evaluate(make_item(), make_current(price_cents=None))
        self.assertFalse(result["trigger"])
        self.assertEqual(result["reason"], "no_price")

    def test_unmatched_product_never_alerts(self):
        result = evaluate(make_item(), make_current(price_cents=790000, match_status="not_found"))
        self.assertFalse(result["trigger"])
        self.assertEqual(result["reason"], "no_match")

    def test_apply_check_updates_low_and_alert_state(self):
        now = datetime.now().astimezone()
        item = make_item()
        current = make_current(price_cents=790000, checked_at=now.isoformat())
        evaluation = evaluate(item, current, now=now)
        apply_check(item, current, evaluation, now=now)

        self.assertEqual(item["last_price_cents"], 790000)
        self.assertEqual(item["lowest_seen_cents"], 790000)
        self.assertEqual(item["last_alert_price_cents"], 790000)
        self.assertEqual(len(item["checks"]), 1)
        self.assertTrue(item["checks"][0]["trigger"])

    def test_snooze_sets_future_time(self):
        now = datetime.now().astimezone()
        item = make_item()
        until = snooze(item, days=3, now=now)
        self.assertGreater(datetime.fromisoformat(until), now)


if __name__ == "__main__":
    unittest.main()
