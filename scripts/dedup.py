#!/usr/bin/env python3
"""对照 applications-tracker.md 给岗位打「疑似已投」软标记（模糊兜底）。

历史投递行没有链接，只能按品牌名 + 岗位标题模糊匹配。这是软提示，不硬删。
硬去重由 results_io 按 link 主键合并完成。
"""
import json
import sys
from difflib import SequenceMatcher


def _col_index(cells, *labels):
    """在表头单元格里找出某列下标（大小写无关），找不到返回 None。"""
    lowered = [c.lower() for c in cells]
    for label in labels:
        if label in lowered:
            return lowered.index(label)
    return None


def parse_tracker(text):
    """从 applications-tracker.md 表格里提取 {company, title} 行。

    按表头定位「公司」「岗位」两列的下标，再据此取数据行——既兼容真实的
    date-first 表（投递日|公司|岗位|…），也兼容仅有 公司|岗位 的简表。
    """
    rows = []
    company_idx = title_idx = None
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 2:
            continue
        if set("".join(cells)) <= set("-: "):  # 分隔行 ---
            continue
        if company_idx is None:  # 尚未定位表头：本行须是表头
            company_idx = _col_index(cells, "公司", "company")
            title_idx = _col_index(cells, "岗位", "title")
            continue  # 表头行不作数据
        if title_idx is None or max(company_idx, title_idx) >= len(cells):
            continue
        rows.append({"company": cells[company_idx], "title": cells[title_idx]})
    return rows


def similar(a, b):
    """大小写无关的相似度 [0,1]。"""
    return SequenceMatcher(None, (a or "").lower(), (b or "").lower()).ratio()


def is_likely_applied(job, tracker_rows, threshold=0.8):
    """岗位是否疑似已投。

    「已投」语义是同公司同岗位，故标题与公司须同时相似才判疑似：
    标题相似度达阈值（默认 0.8）且公司略有重叠（>=0.5）。
    公司用 >=0.5 的宽松线吸收品牌名 vs 瑞典法人名的差异
    （如 "Acme" vs "Acme Sweden AB"），同时挡掉「不同公司、
    相同通用标题」（如各家的 "Software Engineer"）的误报。
    """
    for row in tracker_rows:
        title_sim = similar(job.get("title", ""), row["title"])
        company_sim = similar(job.get("company", ""), row["company"])
        if title_sim >= threshold and company_sim >= 0.5:
            return True
    return False


def flag(jobs, tracker_text, threshold=0.8):
    """给每个岗位加 maybe_applied 布尔标记，返回同一列表。"""
    rows = parse_tracker(tracker_text)
    for job in jobs:
        job["maybe_applied"] = is_likely_applied(job, rows, threshold)
    return jobs


def main(argv=None):
    import argparse
    argv = sys.argv[1:] if argv is None else argv
    parser = argparse.ArgumentParser(description="Flag jobs likely already applied")
    parser.add_argument("--in", dest="inp", required=True)
    parser.add_argument("--tracker", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--threshold", type=float, default=0.8)
    args = parser.parse_args(argv)

    jobs = []
    with open(args.inp, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                jobs.append(json.loads(line))
    try:
        with open(args.tracker, encoding="utf-8") as f:
            tracker_text = f.read()
    except FileNotFoundError:
        tracker_text = ""

    flag(jobs, tracker_text, args.threshold)
    with open(args.out, "w", encoding="utf-8") as f:
        for job in jobs:
            f.write(json.dumps(job, ensure_ascii=False) + "\n")
    n = sum(1 for j in jobs if j["maybe_applied"])
    print(f"flagged {n}/{len(jobs)} as maybe_applied -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
