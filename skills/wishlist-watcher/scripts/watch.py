#!/usr/bin/env python3
"""wishlist-watcher CLI.

A small, agent-agnostic command line interface.  Agents should call this
program instead of doing price arithmetic or guessing product matches in the
model.  All state is local JSON; the only network calls are to Haina.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from haina import (  # noqa: E402
    DEFAULT_PROXY_URL,
    HainaError,
    clear_proxy_config,
    find_best_match,
    format_cents,
    load_api_key,
    load_proxy_config,
    mask_key,
    normalize_product_row,
    price_to_cents,
    product_search,
    save_proxy_config,
)
from rules import add_feedback, apply_check, evaluate, parse_deadline, snooze  # noqa: E402
from store import (  # noqa: E402
    StateError,
    clear_pending,
    default_state_dir,
    find_item,
    load_pending,
    load_state,
    new_item_id,
    now_iso,
    save_pending,
    save_state,
    state_path,
)

VERSION = "0.4.0"

WELCOME_TEXT = """我可以帮你“盯价”：
1. 说“帮我盯 <商品>，降到 <目标价> 告诉我”
2. 我搜出候选，你选一个
3. 之后定期查价，到目标价或接近低点时提醒你
4. 收到提醒后回“买了 / 再等等 / 不准”

我只做提醒，不下单；价格以结算页为准。"""


def _state_dir(args: argparse.Namespace) -> Path:
    raw = getattr(args, "state_dir", None)
    if raw:
        return Path(raw).expanduser().resolve()
    return default_state_dir().resolve()


def _provider_key(args: argparse.Namespace) -> str | None:
    """Return a direct Haina key, or None when proxy mode is configured."""

    state_dir = _state_dir(args)
    proxy = load_proxy_config(state_dir)
    if proxy is not None:
        return None
    key = load_api_key(SKILL_DIR, state_dir)
    if not key:
        raise HainaError(
            "没有配置 HAINA_API_KEY 或代理。先运行 `watch.py setup --format json`，"
            "再按 next_action 操作；邀请用户只需 `watch.py login --token <邀请 token>`。"
        )
    return key


def _emit(payload: dict[str, Any], args: argparse.Namespace, markdown: str) -> None:
    if getattr(args, "format", "markdown") == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(markdown)


def _error(args: argparse.Namespace, message: str) -> None:
    if getattr(args, "format", "markdown") == "json":
        print(json.dumps({"status": "error", "error": message}, ensure_ascii=False, indent=2))
    else:
        print(f"错误：{message}")


def _short_title(title: str, limit: int = 70) -> str:
    title = " ".join(str(title or "").split())
    if len(title) <= limit:
        return title
    return title[: limit - 1] + "…"


def _candidate_line(index: int, candidate: dict[str, Any]) -> str:
    bits = [f"{index}. {_short_title(candidate.get('title', ''))}"]
    platform = " / ".join(
        part for part in [candidate.get("mall"), candidate.get("shop")] if part
    )
    if platform:
        bits.append(platform)
    bits.append(f"到手 {format_cents(candidate.get('price_cents'))}")
    if candidate.get("page_price_cents") and candidate.get("price_cents"):
        bits.append(f"页面 {format_cents(candidate.get('page_price_cents'))}")
    return " | ".join(bits)


def _candidate_payload(candidate: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "candidate_id",
        "title",
        "url",
        "image",
        "mall",
        "shop",
        "brand",
        "price_cents",
        "page_price_cents",
        "price_tags",
        "historical_low_cents",
        "low_30d_cents",
        "usual_price_cents",
        "promo_price_cents",
        "below_promo",
    ]
    return {key: candidate.get(key) for key in keys}


def _card_markdown(item: dict[str, Any], evaluation: dict[str, Any], current: dict[str, Any] | None = None) -> str:
    product = item.get("product") or {}
    title = product.get("title") or (item.get("input") or {}).get("raw") or "(未命名商品)"
    price = (current or {}).get("price_cents")
    if price is None:
        price = item.get("last_price_cents")
    page_price = (current or {}).get("page_price_cents")
    if page_price is None:
        page_price = product.get("page_price_cents")

    lines: list[str] = []
    header = "【值得买】" if evaluation.get("trigger") else "【盯价中】"
    lines.append(f"{header}{title}")
    price_line = f"当前到手 {format_cents(price)}"
    if page_price is not None:
        price_line += f"（页面价 {format_cents(page_price)}）"
    lines.append(price_line)

    platform = " · ".join(part for part in [product.get("mall"), product.get("shop")] if part)
    if platform:
        lines.append(platform)

    context: list[str] = []
    if product.get("historical_low_cents") is not None:
        context.append(f"历史最低 {format_cents(product.get('historical_low_cents'))}（页面价口径）")
    if product.get("low_30d_cents") is not None:
        context.append(f"30天最低 {format_cents(product.get('low_30d_cents'))}")
    if product.get("usual_price_cents") is not None:
        context.append(f"常卖价 {format_cents(product.get('usual_price_cents'))}")
    if context:
        lines.append(" / ".join(context))

    if evaluation.get("trigger"):
        lines.append(f"触发：{evaluation.get('message', '达到触发条件')}")
        diff = evaluation.get("diff_cents")
        if diff is not None:
            if evaluation.get("reason") == "target":
                lines.append(f"比目标价低 {format_cents(diff)}")
            elif evaluation.get("reason") == "new_low":
                lines.append(f"比自入库最低价低 {format_cents(diff)}")
    else:
        lines.append(
            f"目标价 {format_cents(item.get('target_price_cents'))}；"
            f"{evaluation.get('message', '未触发')}"
        )

    if item.get("deadline"):
        lines.append(f"截止：{item['deadline']}")
    if item.get("snooze_until"):
        lines.append(f"已设置再等等：{item['snooze_until']} 前不提醒")
    lines.append(f"检查时间：{(current or {}).get('checked_at') or item.get('last_checked_at') or '—'}")
    lines.append("条件：以结算页为准；如有地区/会员/券限制，请点开确认")
    if product.get("url"):
        lines.append(f"[查看商品]({product['url']})")
    return "\n".join(lines)


def _summary(item: dict[str, Any]) -> dict[str, Any]:
    product = item.get("product") or {}
    return {
        "id": item.get("id"),
        "status": item.get("status"),
        "title": product.get("title") or (item.get("input") or {}).get("raw"),
        "target_price_cents": item.get("target_price_cents"),
        "last_price_cents": item.get("last_price_cents"),
        "last_checked_at": item.get("last_checked_at"),
        "deadline": item.get("deadline"),
        "snooze_until": item.get("snooze_until"),
        "needs_review": item.get("needs_review", False),
    }


def _load_fixture(name: str) -> dict[str, Any]:
    path = SKILL_DIR / "fixtures" / name
    return json.loads(path.read_text(encoding="utf-8"))


def cmd_welcome(args: argparse.Namespace) -> int:
    state_dir = _state_dir(args)
    state = load_state(state_dir)
    first_run = not state.get("onboarded_at")
    if args.mark and first_run:
        state["onboarded_at"] = now_iso()
        save_state(state_dir, state)
    payload = {"first_run": first_run, "message": WELCOME_TEXT}
    _emit(payload, args, WELCOME_TEXT)
    return 0


def _state_dir_check(state_dir: Path) -> tuple[bool, str]:
    try:
        state_dir.mkdir(parents=True, exist_ok=True)
        probe = state_dir / ".setup-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        return False, f"{state_dir}（{exc}）"
    return True, str(state_dir)


def cmd_setup(args: argparse.Namespace) -> int:
    """Machine-readable first-run state for any host.

    Always exits 0 when the check itself ran: `ready=false` is a normal state
    that tells the agent which single action to take next.
    """

    state_dir = _state_dir(args)
    script = Path(__file__).resolve()
    python_ok = sys.version_info >= (3, 10)
    state_ok, state_detail = _state_dir_check(state_dir)

    proxy = None
    proxy_error = None
    try:
        proxy = load_proxy_config(state_dir)
    except HainaError as exc:
        proxy_error = str(exc)
    key = load_api_key(SKILL_DIR, state_dir)

    ready = False
    mode = None
    reason = None
    next_action = None

    if not python_ok:
        reason = "python_too_old"
        next_action = {
            "type": "install_python",
            "message": "需要 Python 3.10 或更高版本",
            "command": "python3 --version",
        }
    elif not state_ok:
        reason = "state_dir_unwritable"
        next_action = {
            "type": "fix_state_dir",
            "message": f"当前状态目录不可写：{state_detail}",
            "command": f'"{sys.executable}" "{script}" setup --state-dir <可写目录>',
        }
    elif proxy_error:
        reason = "proxy_config_invalid"
        next_action = {
            "type": "fix_proxy",
            "message": f"代理配置异常：{proxy_error}。可先 logout，再重新 login",
            "command": f'"{sys.executable}" "{script}" logout',
        }
    elif proxy is not None:
        ready = True
        mode = "proxy"
    elif key:
        ready = True
        mode = "direct"
    else:
        reason = "needs_data_source"
        next_action = {
            "type": "login",
            "message": "向维护者要一个邀请 token，然后运行这条命令；不需要海纳 Key",
            "command": f'"{sys.executable}" "{script}" login --token <邀请 token>',
            "alternative": {
                "type": "direct",
                "message": "如果已有海纳 Key，也可以直连",
                "command": "export HAINA_API_KEY=<你的 Key>",
            },
        }

    payload: dict[str, Any] = {
        "status": "ok",
        "version": VERSION,
        "ready": ready,
        "mode": mode,
        "reason": reason,
        "next_action": next_action,
        "state_dir": str(state_dir),
        "skill_dir": str(SKILL_DIR),
        "python": sys.version.split()[0],
        "proxy_url": proxy["url"] if proxy else None,
        "api_key": mask_key(key),
        "message": "配置已就绪；首次查价会验证网络" if ready else (next_action or {}).get("message"),
    }
    if ready:
        markdown = "\n".join(
            [
                "# 安装状态",
                "",
                "配置已就绪（网络在首次查价时验证）。",
                f"模式：{mode}",
                f"状态目录：{state_dir}",
                "",
                '直接说“帮我盯 <商品>，降到 <目标价> 告诉我”即可。',
            ]
        )
    else:
        markdown = "\n".join(
            [
                "# 还差一步",
                "",
                f"原因：{reason}",
                f"说明：{(next_action or {}).get('message', '')}",
                "",
                "运行：",
                "",
                "```bash",
                (next_action or {}).get("command", ""),
                "```",
            ]
        )
    _emit(payload, args, markdown)
    return 0


def cmd_login(args: argparse.Namespace) -> int:
    state_dir = _state_dir(args)
    token = (args.token or os.environ.get("WISHLIST_PROXY_TOKEN", "")).strip()
    if not token:
        _error(args, "请用 --token 或环境变量 WISHLIST_PROXY_TOKEN 提供邀请 token")
        return 1
    url = (
        args.url
        or os.environ.get("WISHLIST_PROXY_URL", "")
        or DEFAULT_PROXY_URL
    ).strip()
    try:
        path = save_proxy_config(state_dir, url, token)
    except HainaError as exc:
        _error(args, str(exc))
        return 1
    url = url.rstrip("/")
    payload = {
        "status": "ok",
        "mode": "proxy",
        "url": url,
        "config": str(path),
        "message": "已配置内测代理",
    }
    _emit(payload, args, f"已配置内测代理：{url}\n邀请 token 已保存到 {path}（不会显示在输出里）")
    return 0


def cmd_logout(args: argparse.Namespace) -> int:
    state_dir = _state_dir(args)
    try:
        clear_proxy_config(state_dir)
    except HainaError as exc:
        _error(args, str(exc))
        return 1
    payload = {"status": "ok", "mode": "direct", "message": "已删除本地代理配置"}
    _emit(payload, args, "已删除本地代理配置；如果还设置了环境变量，请一并取消。")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    state_dir = _state_dir(args)
    key = load_api_key(SKILL_DIR, state_dir)
    proxy = None
    proxy_error = None
    try:
        proxy = load_proxy_config(state_dir)
    except HainaError as exc:
        proxy_error = str(exc)
    mode = "proxy" if proxy is not None else "direct"
    checks: list[dict[str, Any]] = []

    python_ok = sys.version_info >= (3, 10)
    checks.append(
        {
            "name": "python",
            "required": True,
            "ok": python_ok,
            "detail": sys.version.split()[0],
        }
    )

    state_ok = True
    state_detail = str(state_dir)
    try:
        state_dir.mkdir(parents=True, exist_ok=True)
        probe = state_dir / ".doctor-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        state_ok = False
        state_detail = f"{state_dir}（{exc}）"
    checks.append(
        {
            "name": "state_dir",
            "required": True,
            "ok": state_ok,
            "detail": state_detail,
        }
    )

    if proxy_error:
        provider_ok = False
        provider_detail = proxy_error
    elif proxy is not None:
        provider_ok = True
        provider_detail = f"代理模式：{proxy['url']}（token 已配置）"
    else:
        provider_ok = bool(key)
        provider_detail = f"直连模式：{mask_key(key)}"
    checks.append(
        {
            "name": "api_key",
            "required": True,
            "ok": provider_ok,
            "detail": provider_detail,
        }
    )

    checks.append(
        {
            "name": "fixtures",
            "required": False,
            "ok": (SKILL_DIR / "fixtures" / "product-search-sony-a7c2.json").is_file(),
            "detail": str(SKILL_DIR / "fixtures"),
        }
    )

    if args.network:
        if not provider_ok:
            checks.append(
                {
                    "name": "network",
                    "required": False,
                    "ok": False,
                    "detail": "未配置 Key 或代理，跳过联网检查",
                }
            )
        else:
            try:
                rows = product_search(key, "iphone16", size=1, state_dir=state_dir)
                checks.append(
                    {
                        "name": "network",
                        "required": False,
                        "ok": True,
                        "detail": f"数据源可达，返回 {len(rows)} 条",
                    }
                )
            except Exception as exc:  # noqa: BLE001 - doctor reports the message
                checks.append(
                    {
                        "name": "network",
                        "required": False,
                        "ok": False,
                        "detail": str(exc),
                    }
                )

    ok = all(check["ok"] for check in checks if check["required"])
    payload = {
        "ok": ok,
        "ready": ok,
        "mode": mode,
        "version": VERSION,
        "python": sys.version.split()[0],
        "skill_dir": str(SKILL_DIR),
        "state_dir": str(state_dir),
        "state_file": str(state_path(state_dir)),
        "api_key": mask_key(key),
        "proxy_url": proxy["url"] if proxy else None,
        "checks": checks,
    }
    lines = ["# 环境自检", "", f"总体：{'通过' if ok else '未通过'}", f"模式：{mode}"]
    for check in checks:
        mark = "[OK]" if check["ok"] else "[FAIL]"
        lines.append(f"- {mark} {check['name']}: {check['detail']}")
    if not provider_ok:
        lines.append("")
        lines.append("直连：`export HAINA_API_KEY=...`")
        lines.append("邀请用户：`python3 <skill-dir>/scripts/watch.py login --token <邀请 token>`")
    _emit(payload, args, "\n".join(lines))
    return 0 if ok else 1


def cmd_add(args: argparse.Namespace) -> int:
    query = " ".join(args.query).strip()
    if not query:
        _error(args, "商品搜索词不能为空")
        return 1

    target_cents = price_to_cents(args.target)
    if target_cents is None or target_cents <= 0:
        _error(args, f"目标价格式不正确: {args.target}")
        return 1

    deadline = args.deadline.strip() if args.deadline else None
    if deadline and parse_deadline(deadline) is None:
        _error(args, f"截止时间格式应为 YYYY-MM-DD: {deadline}")
        return 1

    state_dir = _state_dir(args)
    pending = None
    if args.pick is not None:
        try:
            pending = load_pending(state_dir)
        except StateError as exc:
            _error(args, str(exc))
            return 1

    can_use_pending = bool(
        pending
        and pending.get("query") == query
        and pending.get("target_price_cents") == target_cents
        and pending.get("deadline") == deadline
        and isinstance(pending.get("candidates"), list)
        and pending["candidates"]
    )

    if can_use_pending:
        candidates = pending["candidates"]
    else:
        if pending is not None:
            clear_pending(state_dir)
        try:
            key = _provider_key(args)
            candidates = product_search(key, query, size=args.size, state_dir=state_dir)
        except HainaError as exc:
            _error(args, str(exc))
            return 1

    if not candidates:
        _error(args, f"没有搜到商品候选: {query}")
        return 1

    pick = args.pick
    if pick is None:
        if len(candidates) == 1:
            pick = 1
        else:
            save_pending(
                state_dir,
                {
                    "query": query,
                    "target_price_cents": target_cents,
                    "target_raw": args.target,
                    "deadline": deadline,
                    "size": args.size,
                    "candidates": candidates,
                    "created_at": now_iso(),
                },
            )
            payload = {
                "status": "needs_pick",
                "query": query,
                "candidates": [_candidate_payload(candidate) for candidate in candidates],
                "message": "找到多个候选，请让用户确认后用 --pick N 选择",
            }
            lines = [f"找到 {len(candidates)} 个候选，请确认是哪一个：", ""]
            for index, candidate in enumerate(candidates, start=1):
                lines.append(_candidate_line(index, candidate))
            lines.append("")
            lines.append(f"确认后执行：watch.py add \"{query}\" --target {args.target} --pick N")
            _emit(payload, args, "\n".join(lines))
            return 0

    if pick < 1 or pick > len(candidates):
        _error(args, f"--pick 超出范围: {pick}（共 {len(candidates)} 个候选）")
        return 1

    selected = candidates[pick - 1]
    current_price = selected.get("price_cents")
    if current_price is None:
        current_price = selected.get("page_price_cents")
    if current_price is None:
        _error(args, "这个候选没有可用价格，换一个候选或稍后再试")
        return 1

    timestamp = now_iso()
    item: dict[str, Any] = {
        "id": new_item_id(),
        "status": "active",
        "created_at": timestamp,
        "input": {"raw": query, "type": "keyword"},
        "product": {**selected, "search_query": query},
        "target_price_cents": target_cents,
        "deadline": deadline,
        "created_price_cents": current_price,
        "lowest_seen_cents": current_price,
        "last_price_cents": current_price,
        "last_checked_at": timestamp,
        "last_alert_at": None,
        "last_alert_price_cents": None,
        "snooze_until": None,
        "needs_review": False,
        "feedback": [],
        "checks": [],
    }

    state = load_state(state_dir)
    state.setdefault("items", []).append(item)
    save_state(state_dir, state)
    clear_pending(state_dir)

    payload = {
        "status": "created",
        "item": item,
        "message": "已建档，之后用 check 查价，到目标价会提醒",
    }
    markdown = "\n".join(
        [
            f"已建档：{item['product'].get('title', query)}",
            f"ID：`{item['id']}`",
            f"当前到手 {format_cents(current_price)}；目标 {format_cents(target_cents)}"
            + (f"；截止 {deadline}" if deadline else ""),
            "之后可以用 `check` 查价，到目标价或跌破自入库最低价时会提醒。",
        ]
    )
    _emit(payload, args, markdown)
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    state = load_state(_state_dir(args))
    items = list(state.get("items", []))
    items.sort(key=lambda item: item.get("created_at", ""), reverse=True)
    payload = {"count": len(items), "items": [_summary(item) for item in items]}
    if not items:
        _emit(payload, args, "还没有监控项。先说“帮我盯 <商品>，降到 <目标价> 告诉我”。")
        return 0

    lines = [f"共 {len(items)} 个监控项", ""]
    for item in items:
        summary = _summary(item)
        lines.append(
            f"- `{summary['id']}` [{summary['status']}] {_short_title(summary['title'], 48)}"
            f" | 目标 {format_cents(summary['target_price_cents'])}"
            f" | 上次 {format_cents(summary['last_price_cents'])}"
            f" | {summary['last_checked_at'] or '未查过'}"
        )
    _emit(payload, args, "\n".join(lines))
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    state = load_state(_state_dir(args))
    try:
        item = find_item(state, args.id)
    except StateError as exc:
        _error(args, str(exc))
        return 1
    recent = list(item.get("checks", []))[-5:]
    payload = {"item": item, "recent_checks": recent}
    evaluation = {"trigger": False, "message": "查看当前状态"}
    markdown = _card_markdown(item, evaluation)
    if recent:
        markdown += "\n\n最近检查：\n" + "\n".join(
            f"- {check.get('checked_at', '')}：{format_cents(check.get('price_cents'))}"
            f"（{check.get('reason', '')}）"
            for check in recent
        )
    _emit(payload, args, markdown)
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    state_dir = _state_dir(args)
    state = load_state(state_dir)
    if args.id:
        try:
            item = find_item(state, args.id)
        except StateError as exc:
            _error(args, str(exc))
            return 1
        if item.get("status") != "active":
            payload = {
                "checked": 0,
                "alerts": [],
                "results": [],
                "summary": {"alert_count": 0, "checked": 0},
                "message": f"监控项状态为 {item.get('status')}，不检查",
            }
            _emit(payload, args, payload["message"])
            return 0
        items = [item]
    else:
        items = [item for item in state.get("items", []) if item.get("status") == "active"]

    if not items:
        _emit(
            {"checked": 0, "alerts": [], "results": [], "summary": {"alert_count": 0, "checked": 0}},
            args,
            "没有需要检查的监控项。",
        )
        return 0

    try:
        key = _provider_key(args)
    except HainaError as exc:
        _error(args, str(exc))
        return 1

    results: list[dict[str, Any]] = []
    alerts: list[dict[str, Any]] = []

    for item in items:
        now = datetime.now().astimezone()
        query = (item.get("product") or {}).get("search_query") or (item.get("input") or {}).get("raw", "")
        if not query:
            results.append({"id": item.get("id"), "error": "缺少搜索词"})
            continue

        try:
            candidates = product_search(key, query, size=10, state_dir=state_dir)
        except HainaError as exc:
            results.append({"id": item.get("id"), "error": str(exc)})
            continue

        selected, score = find_best_match(
            candidates,
            (item.get("product") or {}).get("title", ""),
            selected_id=(item.get("product") or {}).get("candidate_id"),
        )

        if selected is None:
            current = {
                "price_cents": None,
                "page_price_cents": None,
                "match_status": "not_found",
                "match_score": round(score, 3),
                "checked_at": now.isoformat(timespec="seconds"),
            }
            evaluation = evaluate(item, current, now=now)
            apply_check(item, current, evaluation, now=now)
            results.append(
                {
                    "id": item.get("id"),
                    "title": (item.get("product") or {}).get("title"),
                    "evaluation": evaluation,
                    "match_score": round(score, 3),
                }
            )
            continue

        current = {
            "price_cents": selected.get("price_cents"),
            "page_price_cents": selected.get("page_price_cents"),
            "title": selected.get("title"),
            "mall": selected.get("mall"),
            "shop": selected.get("shop"),
            "url": selected.get("url"),
            "price_tags": selected.get("price_tags"),
            "match_status": "matched",
            "match_score": round(score, 3),
            "checked_at": now.isoformat(timespec="seconds"),
        }
        evaluation = evaluate(item, current, now=now)
        apply_check(item, current, evaluation, now=now)

        result = {
            "id": item.get("id"),
            "title": selected.get("title"),
            "price_cents": current["price_cents"],
            "page_price_cents": current["page_price_cents"],
            "target_price_cents": item.get("target_price_cents"),
            "evaluation": evaluation,
            "match_score": round(score, 3),
        }
        results.append(result)
        if evaluation.get("trigger"):
            alerts.append({**result, "card": _card_markdown(item, evaluation, current)})

    save_state(state_dir, state)

    payload = {
        "checked": len(results),
        "alerts": alerts,
        "results": results,
        "summary": {"alert_count": len(alerts), "checked": len(results)},
    }

    lines: list[str] = []
    if alerts:
        for alert in alerts:
            lines.append(alert["card"])
            lines.append("")
    else:
        lines.append(f"本轮检查 {len(results)} 个监控项，没有触发提醒。")

    for result in results:
        if result.get("error"):
            lines.append(f"- `{result.get('id')}` 检查失败：{result['error']}")
        elif not result.get("evaluation", {}).get("trigger"):
            evaluation = result.get("evaluation", {})
            lines.append(
                f"- `{result.get('id')}` {_short_title(result.get('title', ''), 48)}"
                f" | 到手 {format_cents(result.get('price_cents'))}"
                f" | {evaluation.get('message', '未触发')}"
            )

    _emit(payload, args, "\n".join(lines).strip())
    return 0


def cmd_feedback(args: argparse.Namespace) -> int:
    state_dir = _state_dir(args)
    state = load_state(state_dir)
    try:
        item = find_item(state, args.id)
    except StateError as exc:
        _error(args, str(exc))
        return 1

    action = args.action
    timestamp = now_iso()
    if action == "wait":
        until = snooze(item, days=args.days)
        add_feedback(item, "wait", args.note)
        message = f"已设置再等等：{until} 前不提醒。"
    elif action == "bought":
        item["status"] = "bought"
        item["closed_at"] = timestamp
        add_feedback(item, "bought", args.note)
        message = "已标记为买了，之后不再检查。"
    elif action == "inaccurate":
        item["needs_review"] = True
        until = snooze(item, days=1)
        add_feedback(item, "inaccurate", args.note)
        message = f"已记录价格不准，先暂停提醒到 {until}，请核对商品/价格条件。"
    elif action == "resume":
        item["status"] = "active"
        item["snooze_until"] = None
        item["needs_review"] = False
        item.pop("closed_at", None)
        add_feedback(item, "resume", args.note)
        message = "已恢复监控。"
    else:
        _error(args, f"未知动作: {action}")
        return 1

    save_state(state_dir, state)
    payload = {"status": "ok", "item": _summary(item), "message": message}
    _emit(payload, args, message)
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    fixture = _load_fixture("product-search-sony-a7c2.json")
    rows = ((fixture.get("data") or {}).get("rows") or [])
    candidates = [
        normalize_product_row(row)
        for row in rows
        if isinstance(row, dict)
    ]
    if not candidates:
        _error(args, "demo fixture 没有候选")
        return 1

    lines = ["离线演示（使用 fixture，不联网）", ""]
    for index, candidate in enumerate(candidates, start=1):
        lines.append(_candidate_line(index, candidate))
    lines.append("")

    selected = candidates[-1]
    current_price = selected.get("price_cents") or selected.get("page_price_cents")
    base_item = {
        "id": "demo",
        "status": "active",
        "input": {"raw": "索尼 A7C2", "type": "keyword"},
        "product": {**selected, "search_query": "索尼 A7C2"},
        "target_price_cents": 900000,
        "created_price_cents": current_price,
        "lowest_seen_cents": current_price,
        "last_price_cents": current_price,
        "last_checked_at": now_iso(),
        "last_alert_at": None,
        "last_alert_price_cents": None,
        "snooze_until": None,
        "checks": [],
    }
    current = {
        "price_cents": current_price,
        "page_price_cents": selected.get("page_price_cents"),
        "title": selected.get("title"),
        "mall": selected.get("mall"),
        "shop": selected.get("shop"),
        "url": selected.get("url"),
        "checked_at": now_iso(),
    }
    triggered = evaluate(base_item, current)
    apply_check(base_item, current, triggered)
    trigger_card = _card_markdown(base_item, triggered, current)

    quiet_item = dict(base_item)
    quiet_item["target_price_cents"] = 800000
    quiet_item["lowest_seen_cents"] = current_price
    quiet_item["last_price_cents"] = current_price
    quiet_item["last_alert_at"] = None
    quiet_item["checks"] = []
    quiet = evaluate(quiet_item, current)
    apply_check(quiet_item, current, quiet)

    lines.append("## 场景 1：目标价 9000（触发）")
    lines.append(trigger_card)
    lines.append("")
    lines.append("## 场景 2：目标价 8000（不触发）")
    lines.append(_card_markdown(quiet_item, quiet, current))

    payload = {
        "status": "demo",
        "candidates": [_candidate_payload(candidate) for candidate in candidates],
        "triggered": {"evaluation": triggered, "card": trigger_card},
        "not_triggered": {"evaluation": quiet, "card": _card_markdown(quiet_item, quiet, current)},
    }
    _emit(payload, args, "\n".join(lines))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="watch.py",
        description="心愿单盯价：建档、查价、提醒、反馈（本地 JSON，海纳取价）。",
    )
    parser.add_argument("--version", action="version", version=f"wishlist-watcher {VERSION}")
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--state-dir", help="状态目录；默认 ~/.wishlist-watcher")
        p.add_argument("--format", choices=["markdown", "json"], default="markdown")

    welcome = sub.add_parser("welcome", help="输出首次使用说明")
    welcome.add_argument("--mark", action="store_true", help="标记已展示过首次说明")
    common(welcome)
    welcome.set_defaults(func=cmd_welcome)

    doctor = sub.add_parser("doctor", help="检查 Python、状态目录、API Key/代理")
    doctor.add_argument("--network", action="store_true", help="额外做一次真实数据源请求")
    common(doctor)
    doctor.set_defaults(func=cmd_doctor)

    setup = sub.add_parser("setup", help="首次运行状态机：检查是否已就绪")
    common(setup)
    setup.set_defaults(func=cmd_setup)

    login = sub.add_parser("login", help="配置邀请代理（只需 token）")
    login.add_argument("--url", help="代理地址；默认使用内置地址")
    login.add_argument("--token", help="邀请 token；也可用 WISHLIST_PROXY_TOKEN")
    common(login)
    login.set_defaults(func=cmd_login)

    logout = sub.add_parser("logout", help="删除本地代理配置")
    common(logout)
    logout.set_defaults(func=cmd_logout)

    add = sub.add_parser("add", help="搜索商品并建立监控")
    add.add_argument("query", nargs="+", help="商品名/型号，例如 索尼 A7C2")
    add.add_argument("--target", required=True, help="目标到手价，例如 8000")
    add.add_argument("--deadline", help="截止日期 YYYY-MM-DD")
    add.add_argument("--pick", type=int, help="候选序号（从 1 开始）")
    add.add_argument("--size", type=int, default=5, help="候选数量，默认 5")
    common(add)
    add.set_defaults(func=cmd_add)

    list_cmd = sub.add_parser("list", help="列出监控项")
    common(list_cmd)
    list_cmd.set_defaults(func=cmd_list)

    show = sub.add_parser("show", help="查看单个监控项")
    show.add_argument("id", help="监控项 ID，支持唯一前缀")
    common(show)
    show.set_defaults(func=cmd_show)

    check = sub.add_parser("check", help="检查监控项；不传 --id 则检查全部 active")
    check.add_argument("--id", help="只检查一个监控项")
    common(check)
    check.set_defaults(func=cmd_check)

    feedback = sub.add_parser("feedback", help="记录买了/再等等/不准/恢复")
    feedback.add_argument("id", help="监控项 ID")
    feedback.add_argument("--action", required=True, choices=["wait", "bought", "inaccurate", "resume"])
    feedback.add_argument("--note", default="", help="备注")
    feedback.add_argument("--days", type=int, default=7, help="再等等的天数，默认 7")
    common(feedback)
    feedback.set_defaults(func=cmd_feedback)

    demo = sub.add_parser("demo", help="离线演示，不联网")
    common(demo)
    demo.set_defaults(func=cmd_demo)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except HainaError as exc:
        _error(args, str(exc))
        return 1
    except StateError as exc:
        _error(args, str(exc))
        return 1
    except KeyboardInterrupt:
        return 130
    except Exception as exc:  # noqa: BLE001 - top-level CLI boundary
        _error(args, f"未预期错误：{exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
