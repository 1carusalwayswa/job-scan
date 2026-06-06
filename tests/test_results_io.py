import os
import tempfile
import unittest

from scripts import results_io


def make_job(link, **kw):
    base = {
        "link": link, "company": "C", "title": "T", "location": "L",
        "summary": "S", "score": 50, "lane": "Backend", "reason": "r",
        "source": "jobtech",
    }
    base.update(kw)
    return base


class TestMerge(unittest.TestCase):
    def test_new_job_inserted_as_xin(self):
        merged = results_io.merge({}, [make_job("http://x/1")], {"http://x/1"}, "2026-06-06")
        job = merged["http://x/1"]
        self.assertEqual(job["status"], "新")
        self.assertEqual(job["first_seen"], "2026-06-06")
        self.assertEqual(job["last_seen"], "2026-06-06")

    def test_ignored_job_not_resurfaced_on_rescan(self):
        day1 = results_io.merge({}, [make_job("http://x/1")], {"http://x/1"}, "2026-06-06")
        results_io.set_status(day1, "http://x/1", "已忽略")
        day2 = results_io.merge(day1, [make_job("http://x/1", score=99)], {"http://x/1"}, "2026-06-07")
        self.assertEqual(day2["http://x/1"]["status"], "已忽略")
        self.assertEqual(day2["http://x/1"]["first_seen"], "2026-06-06")
        self.assertEqual(day2["http://x/1"]["last_seen"], "2026-06-07")

    def test_existing_only_in_seen_bumps_last_seen(self):
        day1 = results_io.merge({}, [make_job("http://x/1")], {"http://x/1"}, "2026-06-06")
        results_io.set_status(day1, "http://x/1", "已看")
        day2 = results_io.merge(day1, [], {"http://x/1"}, "2026-06-07")
        self.assertEqual(day2["http://x/1"]["last_seen"], "2026-06-07")
        self.assertEqual(day2["http://x/1"]["status"], "已看")

    def test_disappeared_job_kept(self):
        day1 = results_io.merge({}, [make_job("http://x/1")], {"http://x/1"}, "2026-06-06")
        day2 = results_io.merge(day1, [], set(), "2026-06-07")
        self.assertIn("http://x/1", day2)
        self.assertEqual(day2["http://x/1"]["last_seen"], "2026-06-06")

    def test_existing_in_scored_updates_score_preserves_status(self):
        day1 = results_io.merge({}, [make_job("http://x/1", score=40)], {"http://x/1"}, "2026-06-06")
        results_io.set_status(day1, "http://x/1", "待确认")
        day2 = results_io.merge(day1, [make_job("http://x/1", score=88)], {"http://x/1"}, "2026-06-07")
        self.assertEqual(day2["http://x/1"]["score"], 88)
        self.assertEqual(day2["http://x/1"]["status"], "待确认")


class TestFilterUnscored(unittest.TestCase):
    def test_returns_only_new_links(self):
        existing = {"http://x/1": make_job("http://x/1")}
        raw = [make_job("http://x/1"), make_job("http://x/2")]
        todo = results_io.filter_unscored(existing, raw)
        self.assertEqual([j["link"] for j in todo], ["http://x/2"])


class TestFilterPending(unittest.TestCase):
    def test_returns_unscored_xin_jobs(self):
        existing = {
            "http://x/1": {"link": "http://x/1", "status": "新"},
            "http://x/2": make_job("http://x/2", status="新", score=72),
        }
        pending = results_io.filter_pending(existing)
        self.assertEqual([j["link"] for j in pending], ["http://x/1"])

    def test_excludes_user_triaged_even_if_unscored(self):
        existing = {
            "http://x/1": {"link": "http://x/1", "status": "已忽略"},
            "http://x/2": {"link": "http://x/2", "status": "新"},
        }
        pending = results_io.filter_pending(existing)
        self.assertEqual([j["link"] for j in pending], ["http://x/2"])


class TestSanitize(unittest.TestCase):
    def test_escapes_pipe_and_newline(self):
        self.assertEqual(results_io.sanitize("a|b\nc"), "a\\|b c")

    def test_empty(self):
        self.assertEqual(results_io.sanitize(""), "")


class TestRenderMd(unittest.TestCase):
    def test_sorted_by_score_desc(self):
        jobs = {
            "http://x/1": make_job("http://x/1", score=10, title="lowscore"),
            "http://x/2": make_job("http://x/2", score=90, title="highscore"),
        }
        md = results_io.render_md(jobs)
        self.assertLess(md.index("highscore"), md.index("lowscore"))

    def test_sanitizes_summary_in_table(self):
        jobs = {"http://x/1": make_job("http://x/1", summary="line1\nline2|x")}
        md = results_io.render_md(jobs)
        self.assertNotIn("line1\nline2", md)
        self.assertIn("line1 line2\\|x", md)


class TestSetStatus(unittest.TestCase):
    def test_updates_by_link(self):
        jobs = {"http://x/1": make_job("http://x/1")}
        results_io.set_status(jobs, "http://x/1", "待确认")
        self.assertEqual(jobs["http://x/1"]["status"], "待确认")

    def test_missing_link_raises(self):
        with self.assertRaises(KeyError):
            results_io.set_status({}, "http://x/none", "已看")


class TestRoundTrip(unittest.TestCase):
    def test_save_load_roundtrip(self):
        jobs = {"http://x/1": make_job("http://x/1", status="新", first_seen="2026-06-06")}
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "r.jsonl")
            results_io.save_jsonl(path, jobs)
            loaded = results_io.load_jsonl(path)
        self.assertEqual(loaded["http://x/1"]["status"], "新")

    def test_load_missing_file_returns_empty(self):
        self.assertEqual(results_io.load_jsonl("/no/such/file.jsonl"), {})


if __name__ == "__main__":
    unittest.main()
