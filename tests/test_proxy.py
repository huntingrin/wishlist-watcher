from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

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
