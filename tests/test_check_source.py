"""
Unit tests for src/ingestion/check_source.py: only the bulk file is required.
No network needed: the two checks are replaced by fakes.

Run from the project folder:
    python -m unittest discover tests
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "ingestion"))
import check_source  # noqa: E402


class CheckSourceTest(unittest.TestCase):

    def run_main(self, api, bulk):
        with mock.patch.object(check_source, "check_api", api), \
                mock.patch.object(check_source, "check_bulk", bulk), \
                mock.patch("builtins.print"):
            check_source.main()

    def test_api_down_is_only_a_warning(self):
        timeout = mock.Mock(side_effect=requests.exceptions.ReadTimeout("Read timed out"))
        self.run_main(api=timeout, bulk=mock.Mock(return_value=True))

    def test_bulk_down_fails(self):
        with self.assertRaises(SystemExit):
            self.run_main(api=mock.Mock(return_value=True), bulk=mock.Mock(return_value=False))


if __name__ == "__main__":
    unittest.main()
