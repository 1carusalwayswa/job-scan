import json
import os
import tempfile
import unittest

from scripts import render_html


def _rows(tmp, rows):
    p = os.path.join(tmp, "r.jsonl")
    with open(p, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return p


class TestRenderHtml(unittest.TestCase):
    def test_writes_sorted_html_with_dynamic_lane_colors(self):
        with tempfile.TemporaryDirectory() as d:
            src = _rows(d, [
                {"link": "http://x/1", "company": "Acme", "title": "lo", "lane": "Backend", "score": 10, "status": "新"},
                {"link": "http://x/2", "company": "Globex", "title": "hi", "lane": "Data & ML", "score": 90, "status": "待确认"},
            ])
            out = os.path.join(d, "o.html")
            render_html.render(src, out, home=None)
            doc = open(out, encoding="utf-8").read()
        self.assertLess(doc.index("Globex"), doc.index("Acme"))  # 按分降序（用公司名作唯一标记，避免与 CSS color: 子串冲突）
        self.assertIn("Backend", doc)
        self.assertIn("Data &amp; ML", doc)                     # HTML 转义
        self.assertNotIn("Atlantis", doc)                          # 无个人地点
        self.assertNotIn("data-f=\"local\"", doc)               # 未传 home → 无地点筛选按钮

    def test_home_marker_and_filter_when_home_given(self):
        with tempfile.TemporaryDirectory() as d:
            src = _rows(d, [
                {"link": "http://x/1", "company": "Acme", "title": "t", "lane": "Backend",
                 "score": 50, "status": "新", "location": "Lund"},
            ])
            out = os.path.join(d, "o.html")
            render_html.render(src, out, home="Lund")
            doc = open(out, encoding="utf-8").read()
        self.assertIn("📍", doc)
        self.assertIn("data-f=\"local\"", doc)

    def test_handles_none_location(self):
        with tempfile.TemporaryDirectory() as d:
            src = _rows(d, [{"link": "http://x/1", "company": "Acme", "title": "t",
                             "lane": "Backend", "score": 50, "status": "新", "location": None}])
            out = os.path.join(d, "o.html")
            render_html.render(src, out, home="Lund")  # 不得因 location=None 抛错
            self.assertTrue(os.path.exists(out))


if __name__ == "__main__":
    unittest.main()
