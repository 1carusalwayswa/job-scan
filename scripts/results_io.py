#!/usr/bin/env python3
"""job-scan-results.jsonl fact-source read/write, keyed merge, and .md rendering.

Fact source stores status/score/dates keyed by link; .md is rendered read-only.
Merge never downgrades a user-set status back to 'new' (prevents ignored jobs
from resurfacing).
"""
import json
import sys

# Statuses set by the user — machine must never downgrade these
USER_STATUSES = {"reviewed", "shortlisted", "applied", "ignored"}

MD_COLUMNS = ["First Seen", "Company", "Title", "Location", "Lane", "Score", "Link", "Summary", "Status"]


def load_jsonl(path):
    """Read jsonl into {link: job}. Returns empty dict if file missing."""
    jobs = {}
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    job = json.loads(line)
                    jobs[job["link"]] = job
    except FileNotFoundError:
        pass
    return jobs


def save_jsonl(path, jobs):
    """Write jsonl sorted by score descending. jobs is {link: job}."""
    ordered = sorted(jobs.values(), key=lambda j: j.get("score", 0), reverse=True)
    with open(path, "w", encoding="utf-8") as f:
        for job in ordered:
            f.write(json.dumps(job, ensure_ascii=False) + "\n")


def filter_unscored(existing, raw):
    """Return jobs from raw whose link is not yet in the fact source (need scoring)."""
    return [job for job in raw if job["link"] not in existing]


def filter_pending(existing):
    """Return jobs pending scoring: no score and status still 'new'.

    The daily unattended script inserts new jobs with status='new' and no score.
    Interactive scoring pulls this backlog. Jobs already triaged by the user
    (reviewed/shortlisted/applied/ignored) are skipped even if unscored.
    """
    return [
        job for job in existing.values()
        if "score" not in job and job.get("status") not in USER_STATUSES
    ]


def merge(existing, scored, seen_links, today):
    """Merge scored jobs into fact source by link.

    - New link -> insert with status='new', first_seen=last_seen=today.
    - Existing link in scored -> update score/lane/reason/summary/last_seen,
      preserve status and first_seen.
    - Existing link only in seen_links -> refresh last_seen only.
    - Existing link in neither -> keep as-is (never delete).
    Never downgrade status back to 'new'.
    """
    merged = {link: dict(job) for link, job in existing.items()}

    # 1) Existing jobs still present in this fetch: refresh last_seen
    for link in seen_links:
        if link in merged:
            merged[link]["last_seen"] = today

    # 2) Scored jobs: insert or update (always preserve status/first_seen)
    for job in scored:
        link = job["link"]
        if link in merged:
            cur = merged[link]
            cur["score"] = job.get("score", cur.get("score", 0))
            cur["lane"] = job.get("lane", cur.get("lane", ""))
            cur["reason"] = job.get("reason", cur.get("reason", ""))
            cur["summary"] = job.get("summary", cur.get("summary", ""))
            cur["last_seen"] = today
        else:
            new_job = dict(job)
            new_job["first_seen"] = today
            new_job["last_seen"] = today
            new_job["status"] = "new"
            merged[link] = new_job
    return merged


def sanitize(text):
    """Sanitize free text for .md tables: newlines to spaces, escape pipes."""
    if not text:
        return ""
    return text.replace("\r", " ").replace("\n", " ").replace("|", "\\|").strip()


def render_md(jobs):
    """Render fact source as a Markdown table sorted by score descending."""
    ordered = sorted(jobs.values(), key=lambda j: j.get("score", 0), reverse=True)
    lines = [
        "# job-scan Results",
        "",
        "> Auto-rendered from job-scan-results.jsonl. Do not edit manually; change status via Claude conversation.",
        "",
        "| " + " | ".join(MD_COLUMNS) + " |",
        "|" + "|".join(["---"] * len(MD_COLUMNS)) + "|",
    ]
    for job in ordered:
        flag = " (maybe applied)" if job.get("maybe_applied") else ""
        row = [
            job.get("first_seen", ""),
            sanitize(job.get("company", "")),
            sanitize(job.get("title", "")),
            sanitize(job.get("location", "")),
            job.get("lane", ""),
            str(job.get("score", "")),
            job.get("link", ""),
            sanitize(job.get("summary", "")),
            job.get("status", "") + flag,
        ]
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines) + "\n"


def set_status(jobs, link, status):
    """Set status by link; raises KeyError if link not found."""
    if link not in jobs:
        raise KeyError(link)
    jobs[link]["status"] = status
    return jobs


def _write_jsonl_list(path, items):
    with open(path, "w", encoding="utf-8") as f:
        for item in items:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")


def main(argv=None):
    import argparse
    argv = sys.argv[1:] if argv is None else argv
    parser = argparse.ArgumentParser(description="job-scan results IO")
    parser.add_argument("--mode", required=True, choices=["diff", "merge", "status", "pending"])
    parser.add_argument("--results", required=True)
    parser.add_argument("--raw")
    parser.add_argument("--scored")
    parser.add_argument("--seen")
    parser.add_argument("--md")
    parser.add_argument("--out")
    parser.add_argument("--today")
    parser.add_argument("--link", nargs="+")
    parser.add_argument("--status")
    parser.add_argument("--include-pending", action="store_true",
                        help="In diff mode, also include unscored backlog from fact source")
    args = parser.parse_args(argv)

    existing = load_jsonl(args.results)

    if args.mode == "diff":
        raw = list(load_jsonl(args.raw).values())
        todo = filter_unscored(existing, raw)
        if args.include_pending:
            new_links = {job["link"] for job in todo}
            todo += [job for job in filter_pending(existing) if job["link"] not in new_links]
        _write_jsonl_list(args.out, todo)
        print(f"{len(todo)} new jobs need scoring -> {args.out}")
    elif args.mode == "pending":
        todo = filter_pending(existing)
        _write_jsonl_list(args.out, todo)
        print(f"{len(todo)} pending jobs need scoring -> {args.out}")
    elif args.mode == "merge":
        scored = list(load_jsonl(args.scored).values())
        seen_links = set(load_jsonl(args.seen).keys()) if args.seen else set()
        merged = merge(existing, scored, seen_links, args.today)
        save_jsonl(args.results, merged)
        if args.md:
            with open(args.md, "w", encoding="utf-8") as f:
                f.write(render_md(merged))
        print(f"merged -> {args.results} ({len(merged)} total)")
    elif args.mode == "status":
        for link in args.link:
            set_status(existing, link, args.status)
        save_jsonl(args.results, existing)
        if args.md:
            with open(args.md, "w", encoding="utf-8") as f:
                f.write(render_md(existing))
        for link in args.link:
            print(f"{link} -> {args.status}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
