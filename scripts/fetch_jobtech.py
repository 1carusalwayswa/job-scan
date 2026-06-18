#!/usr/bin/env python3
"""Fetch from JobTech JobSearch API and normalize into unified job dicts.

Never search by English company name — Platsbanken uses Swedish legal names,
so company-name queries miss results. Always query via occupation-field +
bilingual keywords + municipality.
"""
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

API_URL = "https://jobsearch.api.jobtechdev.se/search"


def build_queries(config):
    """Generate query parameter dicts from search_config.json (one per keyword).

    Each returned dict maps to /search query params; never includes company name.
    Never concatenate multiple keywords into one q — JobTech does full-phrase
    relevance matching, so 6 concatenated words yield ~33 hits vs ~671 for a
    single keyword like 'systemutvecklare'.
    """
    queries = []
    municipalities = config.get("municipality_ids", [])
    for lane in config["lanes"]:
        for keyword in lane["keywords"]:
            params = {
                "occupation-field": config["occupation_field"],
                "limit": config.get("limit", 100),
                "q": keyword,
            }
            if municipalities:
                params["municipality"] = municipalities
            queries.append(params)
    return queries


def normalize_hit(hit):
    """Normalize one JobTech /search hit into a unified job dict.

    Uses stable webpage_url as link (falls back to id-based URL) for
    language-independent dedup. Preserves two structured fields for
    deterministic pre-filtering (pre_gate/lang_gate):
    occupation_group (employer-reported SSYK, more reliable than title regex),
    must_have_languages (employer-declared hard language requirements, ~13%
    coverage but zero guessing).
    """
    job_id = hit.get("id", "")
    link = hit.get("webpage_url") or f"https://arbetsformedlingen.se/ad/{job_id}"
    employer = hit.get("employer") or {}
    workplace = hit.get("workplace_address") or {}
    description = hit.get("description") or {}
    must_have = hit.get("must_have") or {}
    return {
        "link": link,
        "company": employer.get("name", ""),
        "title": hit.get("headline", ""),
        "location": workplace.get("municipality", ""),
        "summary": description.get("text", ""),
        "source": "jobtech",
        "occupation_group": (hit.get("occupation_group") or {}).get("label", ""),
        "must_have_languages": [
            l.get("label", "") for l in (must_have.get("languages") or [])
        ],
    }


def _http_get_json(url, retries=3, backoff=2.0):
    """GET JSON with exponential backoff retry on rate-limit/5xx/network errors."""
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"accept": "application/json"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                time.sleep(backoff * (attempt + 1))
                continue
            raise
        except urllib.error.URLError:
            if attempt < retries - 1:
                time.sleep(backoff * (attempt + 1))
                continue
            raise


# API constraint: offset+limit must not exceed 2000; hits beyond that are dropped
MAX_OFFSET = 1900


def fetch(config, http_get=_http_get_json):
    """执行所有查询并分页翻完全部命中，返回按 link 去重的标准化岗位列表。

    不分页只取前 100 时，总命中 >100 的关键词（如 systemutvecklare ~670 条）
    会按相关性截断尾部，正是历史漏抓的主因之一。http_get 可注入以便测试。
    """
    seen = {}
    for params in build_queries(config):
        offset = 0
        while offset <= MAX_OFFSET:
            # municipality 是多值参数，doseq 展开
            page_params = dict(params, offset=offset)
            url = API_URL + "?" + urllib.parse.urlencode(page_params, doseq=True)
            data = http_get(url)
            hits = data.get("hits", [])
            for hit in hits:
                job = normalize_hit(hit)
                if job["link"]:
                    seen[job["link"]] = job
            total = (data.get("total") or {}).get("value", 0)
            offset += len(hits)
            if not hits or offset >= total:
                break
    return list(seen.values())


def main(argv=None):
    import argparse
    argv = sys.argv[1:] if argv is None else argv
    parser = argparse.ArgumentParser(description="Fetch + normalize JobTech jobs")
    parser.add_argument("--config", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    with open(args.config, encoding="utf-8") as f:
        config = json.load(f)
    jobs = fetch(config)
    with open(args.out, "w", encoding="utf-8") as f:
        for job in jobs:
            f.write(json.dumps(job, ensure_ascii=False) + "\n")
    print(f"fetched {len(jobs)} jobs -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
