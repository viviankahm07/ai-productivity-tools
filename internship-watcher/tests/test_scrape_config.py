"""Tests for ENABLED_COMPANIES resolution in scrape.py.

Run with: python -m unittest discover -s tests
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import scrape
from scrapers import SCRAPERS


class GetEnabledScrapersTest(unittest.TestCase):
    def test_unset_env_runs_everything(self):
        with mock.patch.dict("os.environ", {}, clear=False):
            import os
            os.environ.pop("ENABLED_COMPANIES", None)
            enabled = dict(scrape.get_enabled_scrapers())
        self.assertEqual(set(enabled), set(SCRAPERS))

    def test_blank_env_runs_everything(self):
        with mock.patch.dict("os.environ", {"ENABLED_COMPANIES": "   "}):
            enabled = dict(scrape.get_enabled_scrapers())
        self.assertEqual(set(enabled), set(SCRAPERS))

    def test_filters_to_requested_companies(self):
        with mock.patch.dict("os.environ", {"ENABLED_COMPANIES": "accenture,bain"}):
            enabled = dict(scrape.get_enabled_scrapers())
        self.assertEqual(set(enabled), {"accenture", "bain"})

    def test_normalizes_whitespace_and_case(self):
        with mock.patch.dict("os.environ", {"ENABLED_COMPANIES": " Accenture , BAIN ,two_sigma "}):
            enabled = dict(scrape.get_enabled_scrapers())
        self.assertEqual(set(enabled), {"accenture", "bain", "two_sigma"})

    def test_unknown_company_is_skipped_not_fatal(self):
        with mock.patch.dict("os.environ", {"ENABLED_COMPANIES": "accenture,not_a_real_company"}):
            enabled = dict(scrape.get_enabled_scrapers())
        self.assertEqual(set(enabled), {"accenture"})

    def test_all_unknown_yields_empty_without_crashing(self):
        with mock.patch.dict("os.environ", {"ENABLED_COMPANIES": "not_a_real_company"}):
            enabled = scrape.get_enabled_scrapers()
        self.assertEqual(enabled, [])


if __name__ == "__main__":
    unittest.main()
