"""Minimal Haina API client for the wishlist-watcher skill.

Only the Python standard library is used so the skill can run in any agent
that can execute a shell command.  No API key is ever written to logs.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

PRODUCT_URL = "https://gw-openapi.zhidemai.com/product/v1"
DISCOUNT_URL = "https://gw-openapi.zhidemai.com/hj-search/discount/v2"
# Invite-only proxy for the small alpha.  Override with WISHLIST_PROXY_URL or
# `watch.py login --url ...` when self-hosting.
DEFAULT_PROXY_URL = "https://watch.huntingrin.com"
PROXY_CONFIG_FILENAME = "proxy.json"
# Zero-config beta channel: shipped inside the skill so a friend can install and
# use it without being handed a token.  It is a *public* credential by design —
# treat it as an open beta key, not a secret.  Rotation happens server-side via
# the Worker's PROXY_TOKENS secret.
BUNDLED_PROXY_FILENAME = "beta-proxy.json"
DEFAULT_TIMEOUT = 30
MAX_RETRIES = 2
RETRY_STATUS = {429, 500, 502, 503, 504}
PROXY_RETRY_STATUS = {500, 502, 503, 504}

ERROR_MESSAGES = {
    401: "API Key 无效或缺失，请检查 HAINA_API_KEY",
    403: "该 Key 未开通对应能力，或 Key 已失效",
    422: "请求参数校验失败",
    429: "超过 QPS 上限或调用额度已用完",
    500: "海纳服务内部错误",
    502: "海纳服务暂时不可用",
    503: "海纳服务暂时不可用",
    504: "海纳服务超时",
}


class HainaError(Exception):
    """A user-facing Haina API error."""

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        code: Any = None,
        body: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.body = body


def load_api_key(skill_dir: Path | None = None, state_dir: Path | None = None) -> str | None:
    """Read the key from the environment, then from an optional local .env.local.

    The skill never ships a key.  `.env.local` is ignored by git and is only a
    convenience for local runs.
    """

    env_key = os.environ.get("HAINA_API_KEY", "").strip()
    if env_key:
        return env_key

    candidates: list[Path] = []
    if state_dir is not None:
        candidates.append(state_dir / ".env.local")
    elif skill_dir is not None:
        # Only fall back to the skill directory when no state directory is used.
        candidates.append(skill_dir / ".env.local")

    for path in candidates:
        if not path.is_file():
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, value = line.split("=", 1)
            if name.strip() == "HAINA_API_KEY":
                value = value.strip().strip("'\"")
                if value:
                    return value
    return None


def mask_key(key: str | None) -> str:
    if not key:
        return "未配置"
    if len(key) <= 8:
        return "***"
    return f"{key[:4]}…{key[-4:]}"


def proxy_config_path(state_dir: Path) -> Path:
    return state_dir / PROXY_CONFIG_FILENAME


def load_proxy_config(state_dir: Path | None = None) -> dict[str, str] | None:
    """Resolve proxy URL/token from env first, then state_dir/proxy.json.

    Env is useful for CI and one-off runs; the file is what `watch.py login`
    writes for an internal tester.  The token is never logged.
    """

    env_url = os.environ.get("WISHLIST_PROXY_URL", "").strip()
    env_token = os.environ.get("WISHLIST_PROXY_TOKEN", "").strip()
    if env_token and not env_url:
        # The invite build ships with one known proxy; a token alone is enough.
        env_url = DEFAULT_PROXY_URL
    if env_url or env_token:
        if not env_url or not env_token:
            raise HainaError("WISHLIST_PROXY_URL 和 WISHLIST_PROXY_TOKEN 必须同时设置")
        return {"url": env_url.rstrip("/"), "token": env_token}

    if state_dir is None:
        try:
            from store import default_state_dir  # local import avoids a cycle at import time
        except Exception:
            return None
        state_dir = default_state_dir()

    path = proxy_config_path(state_dir)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HainaError(f"无法读取代理配置 {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise HainaError(f"代理配置格式异常: {path}")
    url = str(data.get("url") or "").strip().rstrip("/")
    token = str(data.get("token") or "").strip()
    if not url or not token:
        raise HainaError(f"代理配置缺少 url 或 token: {path}")
    return {"url": url, "token": token}


def load_bundled_proxy_config() -> dict[str, str] | None:
    """Return the built-in beta proxy, if this build ships one."""

    override = os.environ.get("WISHLIST_BETA_FILE", "").strip()
    path = Path(override) if override else Path(__file__).resolve().parents[1] / BUNDLED_PROXY_FILENAME
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    url = str(data.get("url") or "").strip().rstrip("/")
    token = str(data.get("token") or "").strip()
    if not url:
        return None
    # No token means "request a short-lived session from the proxy at run time".
    return {"url": url, "token": token}


def resolve_proxy_config(
    state_dir: Path | None = None,
    api_key: str | None = None,
) -> dict[str, str] | None:
    """Pick the transport: explicit config > own Haina key > bundled beta.

    A user who configured an invite token, or who has their own Haina key,
    always wins over the bundled public beta channel.
    """

    proxy = load_proxy_config(state_dir)
    if proxy is not None:
        return proxy
    if api_key:
        return None
    return load_bundled_proxy_config()


SESSION_FILENAME = "session.json"


def session_path(state_dir: Path) -> Path:
    return state_dir / SESSION_FILENAME


def _read_session(state_dir: Path) -> dict[str, Any]:
    path = session_path(state_dir)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_session(state_dir: Path, data: dict[str, Any]) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=".session-", suffix=".tmp", dir=str(state_dir))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.chmod(temp_name, 0o600)
        os.replace(temp_name, session_path(state_dir))
    except BaseException:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def _client_id(state_dir: Path) -> str:
    data = _read_session(state_dir)
    client_id = str(data.get("client_id") or "").strip()
    if re.fullmatch(r"[A-Za-z0-9_-]{8,64}", client_id):
        return client_id
    return uuid.uuid4().hex


def _session_is_fresh(state_dir: Path, url: str) -> str | None:
    data = _read_session(state_dir)
    if str(data.get("url") or "").rstrip("/") != url:
        return None
    token = str(data.get("token") or "")
    expires_at = str(data.get("expires_at") or "")
    if not token or not expires_at:
        return None
    try:
        deadline = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=timezone.utc)
    if deadline - datetime.now(timezone.utc) < timedelta(minutes=2):
        return None
    return token


def ensure_proxy_token(
    state_dir: Path | None,
    url: str,
    *,
    timeout: int = DEFAULT_TIMEOUT,
    force: bool = False,
) -> str:
    """Return a bearer token for the proxy, asking the proxy for one if needed.

    The repository ships no credential.  On first use the client posts its
    stable client_id to /v1/session and receives a signed, expiring token which
    is stored under the user's state directory (0600).
    """

    if state_dir is None:
        try:
            from store import default_state_dir
        except Exception:
            state_dir = Path.home() / ".wishlist-watcher"
        else:
            state_dir = default_state_dir()
    state_dir = Path(state_dir)
    url = url.rstrip("/")

    if not force:
        cached = _session_is_fresh(state_dir, url)
        if cached:
            return cached

    client_id = _client_id(state_dir)
    body = json.dumps({"client_id": client_id}).encode("utf-8")
    request = urllib.request.Request(
        f"{url}/v1/session",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "wishlist-watcher/0.5",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        if exc.code == 429:
            raise HainaError("申请代理通行证太快，请稍后再试", status=429, body=raw[:300]) from exc
        raise HainaError(f"代理拒绝了通行证申请（HTTP {exc.code}）", status=exc.code, body=raw[:300]) from exc
    except urllib.error.URLError as exc:
        raise HainaError(f"无法连接代理申请通行证：{exc.reason}") from exc
    except TimeoutError as exc:
        raise HainaError("申请代理通行证超时") from exc

    token = str((payload or {}).get("token") or "")
    expires_at = str((payload or {}).get("expires_at") or "")
    if not token or not expires_at:
        raise HainaError("代理返回的通行证格式异常")

    _write_session(
        state_dir,
        {"url": url, "client_id": client_id, "token": token, "expires_at": expires_at},
    )
    return token


def save_proxy_config(state_dir: Path, url: str, token: str) -> Path:
    url = url.strip().rstrip("/")
    token = token.strip()
    if not (url.startswith("https://") or url.startswith("http://")):
        raise HainaError("代理地址必须以 http:// 或 https:// 开头")
    if len(token) < 8:
        raise HainaError("邀请 token 太短，至少 8 个字符")

    state_dir.mkdir(parents=True, exist_ok=True)
    path = proxy_config_path(state_dir)
    fd, temp_name = tempfile.mkstemp(prefix=".proxy-", suffix=".tmp", dir=str(state_dir))
    try:
        os.chmod(temp_name, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump({"url": url, "token": token}, handle, ensure_ascii=False, indent=2)
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
    return path


def clear_proxy_config(state_dir: Path) -> None:
    try:
        proxy_config_path(state_dir).unlink()
    except FileNotFoundError:
        pass
    except OSError as exc:
        raise HainaError(f"无法删除代理配置: {exc}") from exc


def price_to_cents(value: Any) -> int | None:
    """Parse a price from int/float/string into integer cents.

    Accepts forms such as 7996.11, "¥7,996.11", "7996元".  Returns None for
    empty, non-numeric, or range values (a range is not a reliable quote).
    """

    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value * 100
    if isinstance(value, float):
        return int(round(value * 100))

    text = str(value).strip()
    if not text:
        return None
    text = text.replace("¥", "").replace("￥", "").replace(",", "").replace(" ", "")
    text = text.replace("元", "").replace("起", "")
    # A range such as "7996-8199" is ambiguous for a price monitor.
    numbers = re.findall(r"\d+(?:\.\d+)?", text)
    if len(numbers) != 1:
        return None
    try:
        return int(round(float(numbers[0]) * 100))
    except ValueError:
        return None


def format_cents(cents: int | None) -> str:
    if cents is None:
        return "—"
    return f"¥{cents / 100:,.2f}"


def _stable_id(*parts: str) -> str:
    raw = "|".join(parts).encode("utf-8", errors="replace")
    return hashlib.sha1(raw).hexdigest()[:12]


def _extract_rows(data: dict[str, Any]) -> list[dict[str, Any]]:
    payload = data.get("data")
    if isinstance(payload, dict):
        rows = payload.get("rows")
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    return []


def _check_error(data: dict[str, Any]) -> None:
    code = data.get("error_code")
    if code in (None, 0, "0"):
        return
    message = data.get("error_msg") or data.get("message") or "未知错误"
    raise HainaError(f"海纳返回错误 {code}: {message}", code=code)


def _post_json(
    url: str,
    payload: dict[str, Any],
    api_key: str | None = None,
    *,
    proxy: dict[str, str] | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    retries: int = MAX_RETRIES,
    state_dir: Path | None = None,
) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "wishlist-watcher/0.5",
    }
    token = ""
    if proxy is not None:
        token = proxy.get("token", "")
        if not token:
            token = ensure_proxy_token(state_dir, proxy["url"], timeout=timeout)
    else:
        headers["x-api-key"] = api_key or ""

    retry_status = PROXY_RETRY_STATUS if proxy is not None else RETRY_STATUS
    last_error: Exception | None = None
    refreshed = False
    for attempt in range(retries + 1):
        if proxy is not None:
            headers["Authorization"] = f"Bearer {token}"
        request = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read().decode("utf-8", errors="replace")
            try:
                data = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise HainaError("数据源返回的内容不是合法 JSON", body=raw[:500]) from exc
            if not isinstance(data, dict):
                raise HainaError("数据源返回格式异常", body=raw[:500])
            _check_error(data)
            return data
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            if proxy is not None:
                if exc.code == 401 and token.startswith("w1.") and not refreshed:
                    refreshed = True
                    token = ensure_proxy_token(state_dir, proxy["url"], timeout=timeout, force=True)
                    continue
                if exc.code == 401:
                    message = "代理凭证无效或缺失，请重新登录"
                elif exc.code == 429:
                    message = "代理限流或达到日上限，请稍后再试"
                elif exc.code == 502:
                    message = "代理暂时无法访问海纳，请稍后再试"
                else:
                    message = f"代理 HTTP {exc.code}"
            else:
                message = ERROR_MESSAGES.get(exc.code, f"海纳 HTTP {exc.code}")
            if exc.code in retry_status and attempt < retries:
                last_error = exc
                time.sleep(1.5 ** attempt)
                continue
            raise HainaError(message, status=exc.code, body=raw[:500]) from exc
        except urllib.error.URLError as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(1.5 ** attempt)
                continue
            raise HainaError(f"网络错误：{exc.reason}") from exc
        except TimeoutError as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(1.5 ** attempt)
                continue
            raise HainaError("请求超时") from exc

    raise HainaError(f"请求失败：{last_error}")


def normalize_product_row(row: dict[str, Any]) -> dict[str, Any]:
    title = str(row.get("title") or "").strip()
    mall = str(row.get("mall_name") or "").strip()
    shop = str(row.get("shop_name") or "").strip()
    brand = str(row.get("brand_name") or "").strip()
    url = str(row.get("url") or row.get("direct_link") or "").strip()
    image = str(row.get("main_picture") or row.get("focus_pic_url") or "").strip()

    tags: list[dict[str, Any]] = []
    for tag in row.get("price_tags") or []:
        if not isinstance(tag, dict):
            continue
        tag_title = str(tag.get("title") or "").strip()
        if not tag_title:
            continue
        tags.append({"title": tag_title, "price_cents": price_to_cents(tag.get("price"))})

    tag_map = {tag["title"]: tag["price_cents"] for tag in tags}
    price_cents = price_to_cents(row.get("price"))
    page_price_cents = price_to_cents(row.get("page_price"))

    return {
        "candidate_id": _stable_id(title, mall, shop),
        "title": title,
        "url": url,
        "image": image,
        "mall": mall,
        "shop": shop,
        "brand": brand,
        "price_cents": price_cents,
        "page_price_cents": page_price_cents,
        "price_tags": tags,
        "historical_low_cents": tag_map.get("历史最低"),
        "low_30d_cents": tag_map.get("30天最低"),
        "usual_price_cents": tag_map.get("常卖价"),
        "promo_price_cents": tag_map.get("大促价") or tag_map.get("618价"),
        "below_promo": any(tag["title"] == "低于大促价" for tag in tags),
    }


def normalize_discount_row(row: dict[str, Any]) -> dict[str, Any]:
    title = str(row.get("title") or "").strip()
    mall = str(row.get("mall_name") or "").strip()
    brand = str(row.get("brand_name") or "").strip()
    url = str(row.get("url") or row.get("direct_link") or row.get("haojia_dplink") or "").strip()
    price_cents = (
        price_to_cents(row.get("digital_price"))
        or price_to_cents(row.get("price"))
        or price_to_cents(row.get("page_price"))
    )
    return {
        "candidate_id": _stable_id(title, mall, ""),
        "title": title,
        "url": url,
        "mall": mall,
        "brand": brand,
        "price_cents": price_cents,
        "page_price_cents": price_to_cents(row.get("page_price")),
        "digital_price_cents": price_to_cents(row.get("digital_price")),
        "reason": str(row.get("bl_reason") or "").strip(),
        "buy_step": str(row.get("product_buy_step") or "").strip(),
        "article_id": str(row.get("article_id") or "").strip(),
    }


def product_search(
    api_key: str | None,
    query: str,
    *,
    size: int = 10,
    timeout: int = DEFAULT_TIMEOUT,
    question_id: str | None = None,
    state_dir: Path | None = None,
) -> list[dict[str, Any]]:
    """Search products and return normalized rows.

    Uses the proxy when WISHLIST_PROXY_URL/token or proxy.json is configured;
    otherwise calls Haina directly with api_key.  This endpoint takes a
    keyword, not a URL.  Callers should keep the original query so later
    checks use the same recall set.
    """

    query = query.strip()
    if not query:
        raise HainaError("商品搜索词不能为空")
    proxy = resolve_proxy_config(state_dir, api_key)
    if proxy is None and not api_key:
        raise HainaError("没有配置 HAINA_API_KEY 或代理")
    size = max(1, min(int(size), 10 if proxy is not None else 20))
    payload = {
        "product_query": query,
        "request_from": os.environ.get("HAINA_REQUEST_FROM", "wishlist-watcher"),
        "question_id": question_id or uuid.uuid4().hex,
        "query_process": 1,
        "size": size,
    }
    url = f"{proxy['url']}/v1/product/search" if proxy is not None else PRODUCT_URL
    data = _post_json(url, payload, api_key, proxy=proxy, timeout=timeout, state_dir=state_dir)
    return [normalize_product_row(row) for row in _extract_rows(data)]


def discount_search(
    api_key: str | None,
    query: str,
    *,
    size: int = 5,
    timeout: int = DEFAULT_TIMEOUT,
    question_id: str | None = None,
    state_dir: Path | None = None,
) -> list[dict[str, Any]]:
    """Search current deals and return normalized rows."""

    query = query.strip()
    if not query:
        raise HainaError("商品搜索词不能为空")
    proxy = resolve_proxy_config(state_dir, api_key)
    if proxy is None and not api_key:
        raise HainaError("没有配置 HAINA_API_KEY 或代理")
    size = max(1, min(int(size), 10))
    payload = {
        "product_query": query,
        "request_from": os.environ.get("HAINA_REQUEST_FROM", "wishlist-watcher"),
        "question_id": question_id or uuid.uuid4().hex,
        "query_process": 1,
        "size": size,
    }
    url = f"{proxy['url']}/v1/discount/search" if proxy is not None else DISCOUNT_URL
    data = _post_json(url, payload, api_key, proxy=proxy, timeout=timeout, state_dir=state_dir)
    return [normalize_discount_row(row) for row in _extract_rows(data)]


def _normalize_title(title: str) -> str:
    lowered = title.lower()
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", lowered)


def find_best_match(
    candidates: list[dict[str, Any]],
    selected_title: str,
    *,
    selected_id: str | None = None,
) -> tuple[dict[str, Any] | None, float]:
    """Find the candidate that corresponds to the user-confirmed product.

    A stable candidate id is preferred.  Otherwise use a conservative title
    similarity score so a changed title does not silently match an accessory.
    """

    if not candidates:
        return None, 0.0

    if selected_id:
        for candidate in candidates:
            if candidate.get("candidate_id") == selected_id:
                return candidate, 1.0

    target = _normalize_title(selected_title)
    if not target:
        return None, 0.0

    best: dict[str, Any] | None = None
    best_score = 0.0
    for candidate in candidates:
        score = difflib.SequenceMatcher(None, target, _normalize_title(candidate.get("title", ""))).ratio()
        if score > best_score:
            best = candidate
            best_score = score

    if best is not None and best_score >= 0.55:
        return best, best_score
    return None, best_score
