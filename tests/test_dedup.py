import unittest

from scripts import dedup

TRACKER = """# Applications

| 公司 | 岗位 | 渠道 | 状态 |
|---|---|---|---|
| Acme | Software Engineer | LinkedIn | 静默 |
| Globex | Integration Engineer | 门户 | 进行中 |
"""

# date-first 表头（投递日|公司|岗位|…）回归用，全虚构
REAL_TRACKER = """## 追踪表

| 投递日 | 公司 | 岗位 | 级别 | 地点 | 渠道 | 赛道 | 状态 | 最近动态 |
|---|---|---|---|---|---|---|---|---|
| 2026-01-10 | Initech | Experienced C++ SW Engineer | Mid | Lund | LinkedIn | Backend | ⚪ | 无回音 |
| 2026-01-12 | Globex | Integration Engineer | Mid | Göteborg | 门户 | Backend | 🟢 | 进行中 |
"""


class TestParseTracker(unittest.TestCase):
    def test_extracts_company_title_rows(self):
        rows = dedup.parse_tracker(TRACKER)
        self.assertIn({"company": "Acme", "title": "Software Engineer"}, rows)
        self.assertEqual(len(rows), 2)

    def test_skips_header_and_separator(self):
        companies = [r["company"] for r in dedup.parse_tracker(TRACKER)]
        self.assertNotIn("公司", companies)
        self.assertNotIn("---", companies)


class TestParseTrackerRealSchema(unittest.TestCase):
    def test_date_first_maps_company_and_title(self):
        rows = dedup.parse_tracker(REAL_TRACKER)
        self.assertIn({"company": "Initech", "title": "Experienced C++ SW Engineer"}, rows)
        self.assertEqual(len(rows), 2)

    def test_date_first_does_not_leak_header_or_date(self):
        companies = [r["company"] for r in dedup.parse_tracker(REAL_TRACKER)]
        self.assertNotIn("投递日", companies)
        self.assertNotIn("2026-01-10", companies)

    def test_date_first_dedup_matches_despite_legal_name(self):
        rows = dedup.parse_tracker(REAL_TRACKER)
        job = {"company": "Globex Sweden AB", "title": "Integration Engineer"}
        self.assertTrue(dedup.is_likely_applied(job, rows))


class TestIsLikelyApplied(unittest.TestCase):
    def setUp(self):
        self.rows = dedup.parse_tracker(TRACKER)

    def test_matches_known_applied(self):
        job = {"company": "Acme", "title": "Software Engineer"}
        self.assertTrue(dedup.is_likely_applied(job, self.rows))

    def test_rejects_unrelated(self):
        job = {"company": "Spotify", "title": "Data Scientist"}
        self.assertFalse(dedup.is_likely_applied(job, self.rows))

    def test_matches_strong_title_despite_legal_name(self):
        job = {"company": "Globex Sweden AB", "title": "Integration Engineer"}
        self.assertTrue(dedup.is_likely_applied(job, self.rows))


class TestFlag(unittest.TestCase):
    def test_adds_maybe_applied_field(self):
        jobs = [
            {"company": "Acme", "title": "Software Engineer"},
            {"company": "Spotify", "title": "Data Scientist"},
        ]
        dedup.flag(jobs, TRACKER)
        self.assertTrue(jobs[0]["maybe_applied"])
        self.assertFalse(jobs[1]["maybe_applied"])

    def test_empty_tracker_flags_nothing(self):
        jobs = [{"company": "Acme", "title": "Software Engineer"}]
        dedup.flag(jobs, "")
        self.assertFalse(jobs[0]["maybe_applied"])


if __name__ == "__main__":
    unittest.main()
