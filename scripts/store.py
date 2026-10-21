"""Local state for the wishlist-watcher skill.

The state is a single JSON document in a user-level directory by default, so a
different agent session can pick up the same watchlist.  All prices are stored
as integer cents; no floating-point money arithmetic is done in the state.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

STATE_VERSION = 1
STATE_FILENAME = "watchlist.json"
PENDING_FILENAME = "pending-add.json"


class StateError(Exception):
    """A user-facing state error."""


def default_state_dir() -> Path:
    override = os.environ.get("WISHLIST_WATCHER_HOME", "").strip()
    if override:
        return Path(override).expanduser()
    return Path.home() / ".wishlist-watcher"


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def new_item_id() -> str:
    return f"w_{uuid4().hex[:12]}"


def state_path(state_dir: Path) -> Path:
    return state_dir / STATE_FILENAME


def pending_path(state_dir: Path) -> Path:
    return state_dir / PENDING_FILENAME


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.stem}-", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def empty_state() -> dict[str, Any]:
    return {"version": STATE_VERSION, "onboarded_at": None, "items": []}


def load_state(state_dir: Path) -> dict[str, Any]:
    path = state_path(state_dir)
    if not path.exists():
        return empty_state()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StateError(f"无法读取状态文件 {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise StateError(f"状态文件格式异常: {path}")
    version = data.get("version")
    if version != STATE_VERSION:
        raise StateError(f"状态文件版本不兼容: {version}，当前支持 {STATE_VERSION}")
    items = data.get("items")
    if not isinstance(items, list):
        raise StateError(f"状态文件缺少 items 列表: {path}")
    data.setdefault("onboarded_at", None)
    return data


def save_state(state_dir: Path, state: dict[str, Any]) -> Path:
    state = dict(state)
    state["version"] = STATE_VERSION
    state.setdefault("items", [])
    path = state_path(state_dir)
    _atomic_write_json(path, state)
    return path


def save_pending(state_dir: Path, payload: dict[str, Any]) -> Path:
    path = pending_path(state_dir)
    _atomic_write_json(path, payload)
    return path


def load_pending(state_dir: Path) -> dict[str, Any] | None:
    path = pending_path(state_dir)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StateError(f"无法读取待选候选文件 {path}: {exc}") from exc
    return data if isinstance(data, dict) else None


def clear_pending(state_dir: Path) -> None:
    try:
        pending_path(state_dir).unlink()
    except FileNotFoundError:
        pass
    except OSError as exc:
        raise StateError(f"无法清理待选候选文件: {exc}") from exc


def find_item(state: dict[str, Any], item_id: str) -> dict[str, Any]:
    item_id = item_id.strip()
    exact = [item for item in state.get("items", []) if item.get("id") == item_id]
    if len(exact) == 1:
        return exact[0]
    prefix = [item for item in state.get("items", []) if str(item.get("id", "")).startswith(item_id)]
    if len(prefix) == 1:
        return prefix[0]
    if not prefix:
        raise StateError(f"找不到监控项: {item_id}")
    raise StateError(f"监控项前缀不唯一: {item_id}")
