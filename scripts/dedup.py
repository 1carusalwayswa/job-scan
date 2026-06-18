#!/usr/bin/env python3
"""Soft-flag jobs as 'maybe_applied' by fuzzy-matching against applications-tracker.md.

Historical applications lack links, so matching is by company name + job title.
This is a soft hint, not a hard filter. Hard dedup is done by results_io via link key.
"""
import json
import sys
from difflib import SequenceMatcher


def _col_index(cells, *labels):
    """Find column index in header cells (case-insensitive). Returns None if not found."""
    lowered = [c.lower() for c in cells]
    for label in labels:
        if label in lowered:
            return lowered.index(label)
    return None


def parse_tracker(text):
    """Parse {company, title} rows from applications-tracker.md table.

    Locates company/title columns by header labels, supporting both
    date-first tables (date|company|title|...) and simple company|title tables.
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
        if set("".join(cells)) <= set("-: "):  # separator row ---
            continue
        if company_idx is None:  # header not found yet: this line must be it
            company_idx = _col_index(cells, "company")
            title_idx = _col_index(cells, "title")
            continue  # header row, not data
        if title_idx is None or max(company_idx, title_idx) >= len(cells):
            continue
        rows.append({"company": cells[company_idx], "title": cells[title_idx]})
    return rows


def similar(a, b):
    """Case-insensitive similarity ratio [0,1]."""
    return SequenceMatcher(None, (a or "").lower(), (b or "").lower()).ratio()


def is_likely_applied(job, tracker_rows, threshold=0.8):
    """Check if a job was likely already applied to.

    Requires both title and company to match: title similarity >= threshold
    (default 0.8) and company similarity >= 0.5. The loose company threshold
    absorbs brand-name vs Swedish legal-name differences (e.g. "Coretura" vs
    "Coretura Sweden AB") while blocking false positives from different
    companies with identical generic titles (e.g. "Software Engineer").
    """
    for row in tracker_rows:
        title_sim = similar(job.get("title", ""), row["title"])
        company_sim = similar(job.get("company", ""), row["company"])
        if title_sim >= threshold and company_sim >= 0.5:
            return True
    return False


def flag(jobs, tracker_text, threshold=0.8):
    """Add maybe_applied boolean flag to each job, return same list."""
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
