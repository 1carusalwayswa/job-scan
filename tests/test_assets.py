import json
import os
import unittest

from scripts import fetch_jobtech

ASSETS = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets")


class TestSearchConfigExample(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(ASSETS, "search_config.example.json"), encoding="utf-8") as f:
            self.config = json.load(f)

    def test_has_required_keys(self):
        for key in ("occupation_field", "lanes", "thresholds"):
            self.assertIn(key, self.config)

    def test_has_at_least_one_lane(self):
        self.assertTrue(self.config["lanes"])

    def test_every_lane_has_keywords_and_threshold(self):
        for lane in self.config["lanes"]:
            self.assertTrue(lane["keywords"])
            self.assertIn(lane["name"], self.config["thresholds"])

    def test_drives_build_queries_without_company(self):
        for params in fetch_jobtech.build_queries(self.config):
            self.assertIn("occupation-field", params)
            self.assertNotIn("company", {k.lower() for k in params})


class TestTargetCompaniesExample(unittest.TestCase):
    def test_each_company_has_name_and_url(self):
        with open(os.path.join(ASSETS, "target_companies.example.json"), encoding="utf-8") as f:
            data = json.load(f)
        self.assertIn("companies", data)
        for c in data["companies"]:
            self.assertTrue(c["name"])
            self.assertTrue(c["careers_url"].startswith("http"))


if __name__ == "__main__":
    unittest.main()
