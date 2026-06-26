#!/usr/bin/env python3
"""Fetch jobs from target company career pages.

Supports multiple platforms: Teamtailor, Jobylon (embed), SuccessFactors,
Workday JSON API. Falls back to generic HTML link extraction.

Usage: python3 fetch_careers.py --config TARGET_COMPANIES --out OUTPUT.jsonl
Exit code 0 = all ok, 1 = some companies failed (partial results written).
Failed companies are printed to stderr.
"""
import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, SCRIPT_DIR)
from config import TARGET_COMPANIES

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"


def _get(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _post_json(url, payload, timeout=30):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=data,
        headers={"User-Agent": UA, "Content-Type": "application/json", "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _detect_platform(url, note=""):
    u = url.lower()
    hint = note.lower()
    if "jobylon" in hint or "jobylon" in u:
        return "jobylon"
    if "teamtailor" in hint or "teamtailor" in u:
        return "teamtailor"
    if ".myworkdayjobs.com" in u:
        return "workday"
    if "successfactors" in hint or "jobs.volvogroup.com" in u or "jobs.volvocars.com" in u:
        return "successfactors"
    return "generic"


def _make_job(link, company, title, location="", summary=""):
    return {
        "link": link,
        "company": company,
        "title": title,
        "location": location,
        "summary": summary,
        "source": "career",
    }


def fetch_jobylon_embed(company_name, url):
    html = _get(url)
    m = re.search(r"jbl_company_id\s*=\s*(\d+)", html)
    if not m:
        raise ValueError("No jbl_company_id found on page")
    cid = m.group(1)
    embed_url = f"https://cdn.jobylon.com/jobs/companies/{cid}/embed/v2/"
    embed_html = _get(embed_url)
    jobs_match = re.search(r"JBL\.embed_v2\['jobs'\]\s*=\s*(\[.*?\]);\s*\n", embed_html, re.S)
    if not jobs_match:
        raise ValueError("No jobs data in Jobylon embed page")
    raw = jobs_match.group(1)
    titles = re.findall(r"title:\s*'([^']+)'", raw)
    urls = re.findall(r"url:\s*'([^']+)'", raw)
    results = []
    for t, u in zip(titles, urls):
        t = t.replace("\\u002D", "-").replace("\\u0026", "&")
        full = f"https://emp.jobylon.com{u}" if u.startswith("/") else u
        results.append(_make_job(full, company_name, t))
    return results


def fetch_jobylon_static(company_name, url):
    html = _get(url)
    links = re.findall(r"https://emp\.jobylon\.com/jobs/(\d+-[^\"'<\s]+)", html)
    if not links:
        return fetch_jobylon_embed(company_name, url)
    seen = {}
    for slug in links:
        full = f"https://emp.jobylon.com/jobs/{slug}"
        if full not in seen:
            title = slug.split("-", 1)[1].replace("-", " ").rstrip("/") if "-" in slug else slug
            parts = title.rsplit(company_name.lower().replace(" ", "-"), 1)
            if len(parts) > 1:
                title = parts[-1].strip("-").replace("-", " ")
            seen[full] = _make_job(full, company_name, title.title())
    return list(seen.values())


def fetch_teamtailor(company_name, url):
    html = _get(url)
    base = re.match(r"(https?://[^/]+)", url).group(1)
    entries = re.findall(r"(/jobs/\d+-[^\"'<\s]+)", html)
    seen = {}
    for path in entries:
        full = base + path
        if full not in seen:
            slug = path.split("-", 1)[1] if "-" in path else path
            title = slug.replace("-", " ").title()
            seen[full] = _make_job(full, company_name, title)
    return list(seen.values())


def fetch_workday(company_name, url):
    m = re.match(r"(https://([^.]+)\.wd\d+\.myworkdayjobs\.com)/([^/?]+)", url)
    if not m:
        raise ValueError(f"Cannot parse Workday URL: {url}")
    base, tenant, site = m.group(1), m.group(2), m.group(3)
    api_url = f"{base}/wday/cxs/{tenant}/{site}/jobs"
    results = []
    offset = 0
    while True:
        data = _post_json(api_url, {
            "appliedFacets": {}, "limit": 20, "offset": offset, "searchText": "",
        })
        postings = data.get("jobPostings", [])
        for p in postings:
            path = p.get("externalPath", "")
            link = base + path if path else ""
            results.append(_make_job(
                link, company_name, p.get("title", ""),
                location=p.get("locationsText", ""),
            ))
        total = data.get("total", 0)
        offset += len(postings)
        if not postings or offset >= total:
            break
    return results


def fetch_successfactors(company_name, url):
    html = _get(url)
    base = re.match(r"(https?://[^/]+)", url).group(1)
    entries = re.findall(r'href="(/job/[^"]+)"', html)
    seen = {}
    for path in entries:
        full = base + urllib.parse.unquote(path).replace("&amp;", "&")
        if full not in seen:
            parts = path.split("/")
            title = ""
            for p in parts:
                if p and p not in ("job",) and not p.isdigit() and len(p) > 5:
                    title = urllib.parse.unquote(p).replace("-", " ")
                    break
            seen[full] = _make_job(full, company_name, title)
    return list(seen.values())


def fetch_generic(company_name, url):
    html = _get(url)
    base = re.match(r"(https?://[^/]+)", url).group(1)
    entries = re.findall(r'href="([^"]*(?:job|position|career|opening)[^"]*)"', html, re.I)
    seen = {}
    for href in entries:
        full = href if href.startswith("http") else base + href
        if full not in seen:
            seen[full] = _make_job(full, company_name, "")
    return list(seen.values())


FETCHERS = {
    "jobylon": fetch_jobylon_static,
    "teamtailor": fetch_teamtailor,
    "workday": fetch_workday,
    "successfactors": fetch_successfactors,
    "generic": fetch_generic,
}


def fetch_all(companies):
    all_jobs = []
    failures = []
    for c in companies:
        name = c["name"]
        url = c.get("careers_url", "")
        if not url:
            continue
        note = c.get("note", "")
        platform = _detect_platform(url, note)
        fetcher = FETCHERS.get(platform, fetch_generic)
        try:
            jobs = fetcher(name, url)
            all_jobs.extend(jobs)
            print(f"  {name}: {len(jobs)} jobs ({platform})", file=sys.stderr)
        except Exception as e:
            failures.append((name, url, str(e)))
            print(f"  {name}: FAILED ({platform}) - {e}", file=sys.stderr)
    return all_jobs, failures


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    p = argparse.ArgumentParser(description="Fetch jobs from target company career pages")
    p.add_argument("--config", default=TARGET_COMPANIES)
    p.add_argument("--out", required=True)
    args = p.parse_args(argv)

    with open(args.config, encoding="utf-8") as f:
        data = json.load(f)
    companies = data.get("companies", [])

    print(f"Fetching career pages for {len(companies)} companies...", file=sys.stderr)
    jobs, failures = fetch_all(companies)

    with open(args.out, "w", encoding="utf-8") as f:
        for job in jobs:
            f.write(json.dumps(job, ensure_ascii=False) + "\n")

    print(f"career pages: {len(jobs)} jobs total -> {args.out}", file=sys.stderr)

    if failures:
        print(f"\nFAILED ({len(failures)}):", file=sys.stderr)
        for name, url, err in failures:
            print(f"  {name} ({url}): {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
