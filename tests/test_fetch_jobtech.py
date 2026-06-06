import unittest

from scripts import fetch_jobtech


class TestNormalizeHit(unittest.TestCase):
    def test_uses_webpage_url_as_link(self):
        hit = {
            "id": "abc123",
            "headline": "Integration Engineer",
            "webpage_url": "https://arbetsformedlingen.se/ad/abc123",
            "employer": {"name": "Acme AB"},
            "workplace_address": {"municipality": "Göteborg"},
            "description": {"text": "We integrate things."},
        }
        job = fetch_jobtech.normalize_hit(hit)
        self.assertEqual(job["link"], "https://arbetsformedlingen.se/ad/abc123")
        self.assertEqual(job["company"], "Acme AB")
        self.assertEqual(job["title"], "Integration Engineer")
        self.assertEqual(job["location"], "Göteborg")
        self.assertEqual(job["summary"], "We integrate things.")
        self.assertEqual(job["source"], "jobtech")

    def test_constructs_link_from_id_when_url_missing(self):
        job = fetch_jobtech.normalize_hit({"id": "xyz789", "headline": "Dev"})
        self.assertIn("xyz789", job["link"])
        self.assertTrue(job["link"].startswith("http"))

    def test_missing_fields_default_to_empty(self):
        job = fetch_jobtech.normalize_hit({"id": "1", "webpage_url": "http://x/1"})
        self.assertEqual(job["company"], "")
        self.assertEqual(job["title"], "")
        self.assertEqual(job["location"], "")
        self.assertEqual(job["summary"], "")


class TestBuildQueries(unittest.TestCase):
    CONFIG = {
        "occupation_field": "apaJ_2ja_LuF",
        "municipality_ids": ["AvNB_uwa_6n6"],
        "limit": 50,
        "lanes": [
            {"name": "Backend", "keywords": ["integration engineer", "middleware"]},
            {"name": "Data & ML", "keywords": ["AI engineer", "agentic"]},
        ],
    }

    def test_one_query_per_lane(self):
        self.assertEqual(len(fetch_jobtech.build_queries(self.CONFIG)), 2)

    def test_never_searches_by_company_name(self):
        for params in fetch_jobtech.build_queries(self.CONFIG):
            keys = {k.lower() for k in params}
            self.assertNotIn("employer", keys)
            self.assertNotIn("company", keys)
            self.assertIn("occupation-field", params)

    def test_query_carries_keywords_and_municipality(self):
        params = fetch_jobtech.build_queries(self.CONFIG)[0]
        self.assertIn("integration engineer", params["q"])
        self.assertEqual(params["municipality"], ["AvNB_uwa_6n6"])

    def test_fetch_dedups_by_link(self):
        payload = {"hits": [
            {"id": "1", "webpage_url": "http://x/1", "headline": "A"},
            {"id": "1", "webpage_url": "http://x/1", "headline": "A"},
        ]}
        jobs = fetch_jobtech.fetch(self.CONFIG, http_get=lambda url: payload)
        self.assertEqual(len(jobs), 1)


if __name__ == "__main__":
    unittest.main()
