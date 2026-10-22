from __future__ import annotations

import io
import json
import os
import sys
import urllib.error
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "wishlist-watcher" / "scripts"))

import haina  # noqa: E402


class ProxyConfigTests(unittest.TestCase):
    def test_round_trip_and_clear(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            with patch.dict(os.environ, {"WISHLIST_PROXY_URL": "", "WISHLIST_PROXY_TOKEN": ""}):
                path = haina.save_proxy_config(state_dir, "https://proxy.example/", "invite-123456")
                self.assertEqual(path, state_dir / "proxy.json")
                config = haina.load_proxy_config(state_dir)
                self.assertIsNotNone(config)
                assert config is not None
                self.assertEqual(config["url"], "https://proxy.example")
                self.assertEqual(config["token"], "invite-123456")

                haina.clear_proxy_config(state_dir)
                self.assertIsNone(haina.load_proxy_config(state_dir))

    def test_env_overrides_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            haina.save_proxy_config(state_dir, "https://file.example", "file-token")
            with patch.dict(
                os.environ,
                {"WISHLIST_PROXY_URL": "https://env.example/", "WISHLIST_PROXY_TOKEN": "env-token"},
            ):
                config = haina.load_proxy_config(state_dir)
                self.assertIsNotNone(config)
                assert config is not None
                self.assertEqual(config["url"], "https://env.example")
                self.assertEqual(config["token"], "env-token")

    def test_partial_env_is_an_error(self):
        with patch.dict(os.environ, {"WISHLIST_PROXY_URL": "https://env.example", "WISHLIST_PROXY_TOKEN": ""}):
            with self.assertRaises(haina.HainaError):
                haina.load_proxy_config(None)

    def test_token_only_env_uses_builtin_proxy(self):
        with patch.dict(os.environ, {"WISHLIST_PROXY_URL": "", "WISHLIST_PROXY_TOKEN": "invite-123456"}):
            config = haina.load_proxy_config(None)
            self.assertIsNotNone(config)
            assert config is not None
            self.assertEqual(config["url"], haina.DEFAULT_PROXY_URL)
            self.assertEqual(config["token"], "invite-123456")

    def test_bundled_beta_ships_no_token(self):
        config = haina.load_bundled_proxy_config()
        self.assertIsNotNone(config)
        assert config is not None
        self.assertEqual(config["url"], "https://watch.huntingrin.com")
        self.assertEqual(config["token"], "")

    def test_ensure_proxy_token_is_requested_once_and_stored_0600(self):
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self):
                return json.dumps(
                    {"token": "w1.abc.def", "expires_at": "2099-01-01T00:00:00Z"}
                ).encode("utf-8")

        calls = []

        def fake_urlopen(request, timeout=None):
            calls.append(request.full_url)
            return FakeResponse()

        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            with patch("urllib.request.urlopen", fake_urlopen):
                first = haina.ensure_proxy_token(state_dir, "https://proxy.example")
                second = haina.ensure_proxy_token(state_dir, "https://proxy.example")
            self.assertEqual(first, "w1.abc.def")
            self.assertEqual(second, "w1.abc.def")
            self.assertEqual(calls, ["https://proxy.example/v1/session"])
            stored = json.loads((state_dir / "session.json").read_text(encoding="utf-8"))
            self.assertEqual(stored["token"], "w1.abc.def")
            self.assertEqual((state_dir / "session.json").stat().st_mode & 0o777, 0o600)

    def test_expired_session_is_reissued(self):
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self):
                return json.dumps(
                    {"token": "w1.new.def", "expires_at": "2099-01-01T00:00:00Z"}
                ).encode("utf-8")

        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            (state_dir / "session.json").write_text(
                json.dumps(
                    {
                        "url": "https://proxy.example",
                        "client_id": "abcdefgh1234",
                        "token": "w1.old.def",
                        "expires_at": "2000-01-01T00:00:00Z",
                    }
                ),
                encoding="utf-8",
            )
            with patch("urllib.request.urlopen", lambda request, timeout=None: FakeResponse()):
                token = haina.ensure_proxy_token(state_dir, "https://proxy.example")
            self.assertEqual(token, "w1.new.def")
            stored = json.loads((state_dir / "session.json").read_text(encoding="utf-8"))
            self.assertEqual(stored["client_id"], "abcdefgh1234")

    def test_401_refreshes_session_once(self):
        class FakeResponse:
            def __init__(self, payload):
                self.payload = payload

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self):
                return self.payload.encode("utf-8")

        search_calls = {"count": 0}

        def fake_urlopen(request, timeout=None):
            if request.full_url.endswith("/v1/product/search"):
                search_calls["count"] += 1
                if search_calls["count"] == 1:
                    raise urllib.error.HTTPError(
                        request.full_url, 401, "unauthorized", {}, io.BytesIO(b"{}")
                    )
                return FakeResponse('{"error_code":0,"data":{"rows":[]}}')
            raise AssertionError(f"unexpected call {request.full_url}")

        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            issued = ["w1.first.one", "w1.second.one"]
            with patch.object(haina, "ensure_proxy_token", side_effect=issued):
                with patch.object(
                    haina,
                    "resolve_proxy_config",
                    return_value={"url": "https://proxy.example", "token": ""},
                ):
                    with patch("urllib.request.urlopen", fake_urlopen):
                        rows = haina.product_search(None, "索尼 A7C2", size=1, state_dir=state_dir)
            self.assertEqual(rows, [])
            self.assertEqual(search_calls["count"], 2)

    def test_product_search_uses_proxy_endpoint_and_bearer_header(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            with patch.dict(
                os.environ,
                {"WISHLIST_PROXY_URL": "https://proxy.example", "WISHLIST_PROXY_TOKEN": "invite-123456"},
            ):
                with patch.object(
                    haina,
                    "_post_json",
                    return_value={"error_code": 0, "data": {"rows": []}},
                ) as post:
                    rows = haina.product_search(None, "索尼 A7C2", size=3, state_dir=state_dir)
                    self.assertEqual(rows, [])
                    args, kwargs = post.call_args
                    self.assertEqual(args[0], "https://proxy.example/v1/product/search")
                    self.assertIsNone(args[2])
                    self.assertEqual(kwargs["proxy"]["token"], "invite-123456")
                    self.assertEqual(args[1]["size"], 3)


if __name__ == "__main__":
    unittest.main()
