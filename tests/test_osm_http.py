"""Unit tests for bounded Overpass client validation."""
import json
import unittest
from unittest.mock import patch

from core.osm_http import fetch_overpass, query_overpass


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class OverpassClientTests(unittest.TestCase):
    @patch("core.osm_http.urllib.request.urlopen")
    def test_posts_query_and_parses_features(self, mocked):
        mocked.return_value = _Response({"elements": [{"type": "node"}]})
        result = fetch_overpass("https://example.test/api/interpreter", "[out:json];out;")
        self.assertEqual(len(result["elements"]), 1)
        request = mocked.call_args.args[0]
        self.assertEqual(request.method, "POST")
        self.assertIn(b"data=", request.data)

    def test_rejects_non_https_endpoint(self):
        with self.assertRaises(ValueError):
            fetch_overpass("http://example.test/interpreter", "out;")

    @patch("core.osm_http.fetch_overpass")
    def test_mirror_failover(self, mocked):
        mocked.side_effect = [TimeoutError("slow"), {"elements": []}]
        data, endpoint, error = query_overpass("out;", ["https://a.test", "https://b.test"], timeout=1)
        self.assertEqual(data, {"elements": []})
        self.assertEqual(endpoint, "https://b.test")
        self.assertEqual(error, "")


if __name__ == "__main__":
    unittest.main()
