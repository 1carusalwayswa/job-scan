import unittest

from scripts import dedup


class TrackerParsingTests(unittest.TestCase):
    def test_parses_role_column_from_table(self):
        tracker = """
| Date | Company | Role | Status |
| --- | --- | --- | --- |
| 2026-07-01 | Example AB | AI Engineer | Submitted |
"""

        self.assertEqual(
            dedup.parse_tracker(tracker),
            [{"company": "Example AB", "title": "AI Engineer"}],
        )

    def test_parses_company_and_role_fields(self):
        tracker = """
- Company: Example AB
- Role: Backend Engineer
- Location: Stockholm
- Status: Submitted
"""

        self.assertEqual(
            dedup.parse_tracker(tracker),
            [{"company": "Example AB", "title": "Backend Engineer"}],
        )


if __name__ == "__main__":
    unittest.main()
