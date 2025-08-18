from __future__ import annotations

import json
from pathlib import Path
import unittest

from kover.uri_parser import is_valid_uri


class InvalidUriTests(unittest.TestCase):
    def __init__(self, *args: ..., **kwargs: ...) -> None:
        super().__init__(*args, **kwargs)
        self._json_p = Path(__file__).parent / "invalid_uris.json"

    def test_all_tests_from_json(self) -> None:
        with self._json_p.open("r", encoding="utf-8") as fp:
            loaded = json.load(fp)
            for test in loaded["tests"]:
                assert is_valid_uri(test["uri"]) == test["valid"]


if __name__ == "__main__":
    unittest.main()
