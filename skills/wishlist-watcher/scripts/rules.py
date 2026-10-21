"""Trigger rules and state transitions for wishlist-watcher."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

COOLDOWN_HOURS = 24
SNOOZE_DAYS = 7
MAX_CHECKS = 90


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.astimezone()
    return parsed


def parse_deadline(value: str | None) -> datetime | None:
    """A YYYY-MM-DD deadline is inclusive through the end of that local day."""

    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.astimezone()
    if len(text) == 10:
        parsed = parsed.replace(hour=23, minute=59, second=59, microsecond=0)
    return parsed


def evaluate(
    item: dict[str, Any],
    current: dict[str, Any],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return whether this check should produce an alert.

    Rules are intentionally conservative:
    - only the item's target price and its own observed low are used;
    - page-price history from Haina is never compared with a checkout price;
    - a 24-hour cooldown suppresses repeat alerts;
    - missing prices and unmatched products never alert.
    """

    now = now or datetime.now().astimezone()

    if item.get("status") != "active":
        return {"trigger": False, "reason": "inactive", "message": "监控项不是 active 状态"}

    deadline = parse_deadline(item.get("deadline"))
    if deadline is not None and now > deadline:
        return {
            "trigger": False,
            "reason": "expired",
            "expire": True,
            "message": "已过截止时间",
        }

    snooze_until = parse_dt(item.get("snooze_until"))
    if snooze_until is not None and now < snooze_until:
        return {
            "trigger": False,
            "reason": "snoozed",
            "snooze_until": snooze_until.isoformat(timespec="seconds"),
            "message": "用户选择了再等等",
        }

    price = current.get("price_cents")
    if price is None:
        return {"trigger": False, "reason": "no_price", "message": "本轮没有拿到可靠价格"}

    if current.get("match_status") == "not_found":
        return {"trigger": False, "reason": "no_match", "message": "没有匹配到已确认的商品"}

    last_alert_at = parse_dt(item.get("last_alert_at"))
    if last_alert_at is not None:
        cooldown_until = last_alert_at + timedelta(hours=COOLDOWN_HOURS)
        if now < cooldown_until:
            return {
                "trigger": False,
                "reason": "cooldown",
                "cooldown_until": cooldown_until.isoformat(timespec="seconds"),
                "message": "24 小时冷却中",
            }

    target = item.get("target_price_cents")
    lowest = item.get("lowest_seen_cents")
    last_price = item.get("last_price_cents")

    if target is not None and price <= target:
        return {
            "trigger": True,
            "reason": "target",
            "message": "达到目标价",
            "diff_cents": target - price,
        }

    if (
        lowest is not None
        and last_price is not None
        and price < lowest
        and price < last_price
    ):
        return {
            "trigger": True,
            "reason": "new_low",
            "message": "跌破自入库以来最低价",
            "diff_cents": lowest - price,
        }

    return {"trigger": False, "reason": "not_met", "message": "未达到触发条件"}


def apply_check(
    item: dict[str, Any],
    current: dict[str, Any],
    evaluation: dict[str, Any],
    *,
    now: datetime | None = None,
) -> None:
    """Persist one check and update the item's observed low/last price."""

    now = now or datetime.now().astimezone()
    timestamp = now.isoformat(timespec="seconds")

    price = current.get("price_cents")
    check = {
        "checked_at": timestamp,
        "price_cents": price,
        "page_price_cents": current.get("page_price_cents"),
        "title": current.get("title", ""),
        "mall": current.get("mall", ""),
        "shop": current.get("shop", ""),
        "url": current.get("url", ""),
        "match_score": current.get("match_score"),
        "match_status": current.get("match_status", "matched"),
        "trigger": bool(evaluation.get("trigger")),
        "reason": evaluation.get("reason", ""),
    }
    checks = item.setdefault("checks", [])
    checks.append(check)
    item["checks"] = checks[-MAX_CHECKS:]
    item["last_checked_at"] = timestamp

    if price is not None:
        item["last_price_cents"] = price
        lowest = item.get("lowest_seen_cents")
        item["lowest_seen_cents"] = price if lowest is None else min(lowest, price)

    if evaluation.get("expire"):
        item["status"] = "expired"
        item["closed_at"] = timestamp

    if evaluation.get("trigger"):
        item["last_alert_at"] = timestamp
        item["last_alert_price_cents"] = price


def snooze(item: dict[str, Any], *, days: int = SNOOZE_DAYS, now: datetime | None = None) -> str:
    now = now or datetime.now().astimezone()
    until = now + timedelta(days=max(1, int(days)))
    item["snooze_until"] = until.isoformat(timespec="seconds")
    return item["snooze_until"]


def add_feedback(item: dict[str, Any], action: str, note: str = "", *, now: datetime | None = None) -> None:
    now = now or datetime.now().astimezone()
    item.setdefault("feedback", []).append(
        {
            "at": now.isoformat(timespec="seconds"),
            "action": action,
            "note": note.strip(),
        }
    )
