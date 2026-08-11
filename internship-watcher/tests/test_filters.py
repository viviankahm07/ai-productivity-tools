"""Tests for the U.S. software-engineering internship filter.

Run with: python -m unittest discover -s tests
"""

import sys
import unittest
from pathlib import Path

# Allow running this file directly without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from filters import matches_role


class MatchingRolesTest(unittest.TestCase):
    """Postings that should be treated as U.S. SWE internships."""

    def test_software_engineer_intern_new_york(self):
        self.assertTrue(matches_role("Software Engineer Intern", "New York, NY"))

    def test_software_engineering_internship_seattle(self):
        self.assertTrue(matches_role("Software Engineering Internship", "Seattle, WA"))

    def test_backend_engineer_intern_san_francisco(self):
        self.assertTrue(matches_role("Backend Engineer Intern", "San Francisco, CA"))

    def test_technology_summer_internship_software_engineering(self):
        self.assertTrue(
            matches_role("2027 Technology Summer Internship - Software Engineering", "United States")
        )

    def test_frontend_engineer_intern_remote_us(self):
        self.assertTrue(matches_role("Frontend Engineer Intern", "Remote - US"))

    def test_full_stack_engineer_intern_state_abbreviation_only(self):
        # Location isn't in the hardcoded city list, but ", MA" should still
        # register as a U.S. signal.
        self.assertTrue(matches_role("Full-Stack Engineer Intern", "Cambridge, MA"))


class NonMatchingRolesTest(unittest.TestCase):
    """Postings that should NOT be treated as U.S. SWE internships."""

    def test_senior_software_engineer(self):
        self.assertFalse(matches_role("Senior Software Engineer", "New York, NY"))

    def test_product_management_intern(self):
        self.assertFalse(matches_role("Product Management Intern", "New York, NY"))

    def test_investment_banking_summer_analyst(self):
        self.assertFalse(matches_role("Investment Banking Summer Analyst", "New York, NY"))

    def test_investment_banking_intern(self):
        self.assertFalse(matches_role("Investment Banking Intern", "New York, NY"))

    def test_software_engineer_non_us_location(self):
        self.assertFalse(matches_role("Software Engineer", "London, UK"))

    def test_marketing_intern(self):
        self.assertFalse(matches_role("Marketing Intern", "New York, NY"))

    def test_software_engineer_no_internship_signal(self):
        self.assertFalse(matches_role("Software Engineer", "New York, NY"))

    def test_state_abbreviation_does_not_match_inside_words(self):
        # "IN" and "OR" are state codes, but shouldn't fire from ordinary
        # lowercase words that happen to contain them.
        self.assertFalse(matches_role("Marketing Intern", "Remote"))


if __name__ == "__main__":
    unittest.main()
