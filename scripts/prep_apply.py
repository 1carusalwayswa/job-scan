#!/usr/bin/env python3
"""prep_apply.py — 把候选岗整理成可投递的目录 + JD 原料文件。

用法:
  prep_apply.py --list [--min-score N]      列出候选岗
  prep_apply.py --prep LINK [LINK ...]      对选中岗建目录 + 写 job_summary.md
"""
import argparse
import json
import os
import re
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
from config import RESULTS, REPO_ROOT

SKIP_STATUS = {"已忽略", "已转apply"}
DEFAULT_MIN_SCORE = 70


def load_rows(path=RESULTS):
    rows = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def slugify(s):
    s = (s or "").lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return re.sub(r"-+", "-", s).strip("-")


def dir_name(row):
    company = slugify(row.get("company", ""))[:30].strip("-")
    title = slugify(row.get("title", ""))[:50].strip("-")
    name = "-".join(x for x in (company, title) if x) or "untitled"
    return name


def candidates(rows, min_score):
    out = []
    for o in rows:
        s = o.get("score")
        if not isinstance(s, (int, float)):
            continue
        if s < min_score:
            continue
        if o.get("status") in SKIP_STATUS:
            continue
        if o.get("maybe_applied") is True:
            continue
        out.append(o)
    out.sort(key=lambda o: -o.get("score", 0))
    return out


def cmd_list(args):
    rows = load_rows()
    cands = candidates(rows, args.min_score)
    if not cands:
        print(f"(no candidates: score>={args.min_score}, not applied/ignored)")
        return
    print(f"{len(cands)} candidates (score>={args.min_score}, descending):\n")
    for i, o in enumerate(cands, 1):
        print(f"{i:>2}. [{o.get('score')}] {o.get('lane','?')} | "
              f"{(o.get('title') or '?')[:55]} @ {(o.get('company') or '?')[:30]}")
        print(f"    {o.get('link','')}")
        reason = (o.get("reason") or "").replace("\n", " ")
        if reason:
            print(f"    -> {reason[:120]}")
        print()


JOB_SUMMARY_TMPL = """# {company} - {title}

## Job Info
- **Link:** {link}
- **Company:** {company}
- **Title:** {title}
- **Location:** {location}
- **Source:** {source}

## Scoring
- **Score:** {score}
- **Lane:** {lane}
- **Reason:** {reason}

## Job Description (full JD)

{summary}
"""


def cmd_prep(args):
    rows = load_rows()
    by_link = {o.get("link"): o for o in rows}
    output_dir = os.path.join(REPO_ROOT, "applications")
    os.makedirs(output_dir, exist_ok=True)
    made, skipped = [], []
    for link in args.links:
        o = by_link.get(link)
        if o is None:
            print(f"warning: link not found: {link}", file=sys.stderr)
            skipped.append(link)
            continue
        d = os.path.join(output_dir, dir_name(o))
        os.makedirs(d, exist_ok=True)
        summary_path = os.path.join(d, "job_summary.md")
        if os.path.exists(summary_path) and not args.force:
            print(f"skip (exists, use --force): {summary_path}", file=sys.stderr)
            skipped.append(link)
            continue
        with open(summary_path, "w") as f:
            f.write(JOB_SUMMARY_TMPL.format(
                company=o.get("company", ""), title=o.get("title", ""),
                link=o.get("link", ""), location=o.get("location", ""),
                source=o.get("source", ""), score=o.get("score", ""),
                lane=o.get("lane", ""), reason=o.get("reason", ""),
                summary=o.get("summary", "")))
        made.append((d, o))
        print(f"created: {summary_path}")
    if made:
        print(f"\n{len(made)} job directories ready.")
    if skipped:
        print(f"{len(skipped)} skipped.", file=sys.stderr)


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--list", action="store_true")
    g.add_argument("--prep", nargs="+", metavar="LINK", dest="links")
    p.add_argument("--min-score", type=int, default=DEFAULT_MIN_SCORE)
    p.add_argument("--force", action="store_true")
    args = p.parse_args()

    if args.list:
        cmd_list(args)
    elif args.links:
        cmd_prep(args)


if __name__ == "__main__":
    main()
