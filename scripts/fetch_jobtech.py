#!/usr/bin/env python3
"""拉取 JobTech JobSearch API 并标准化为统一岗位字典。

铁律：绝不按英文公司名搜索。Platsbanken 用瑞典法人名，按公司名搜会漏。
查询一律走 occupation-field + 双语关键词 + municipality。
"""
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

API_URL = "https://jobsearch.api.jobtechdev.se/search"


def build_queries(config):
    """从 search_config.json 配置生成查询参数列表（每赛道一组）。

    每个返回 dict 是 /search 的 query 参数，绝不包含公司名字段。
    """
    queries = []
    municipalities = config.get("municipality_ids", [])
    for lane in config["lanes"]:
        params = {
            "occupation-field": config["occupation_field"],
            "limit": config.get("limit", 100),
            "q": " ".join(lane["keywords"]),
        }
        if municipalities:
            params["municipality"] = municipalities
        queries.append(params)
    return queries


def normalize_hit(hit):
    """把一条 JobTech /search 命中标准化为统一岗位字典。

    link 取稳定的 webpage_url（缺失时用 id 构造），作为跨语言一致的去重主键。
    """
    job_id = hit.get("id", "")
    link = hit.get("webpage_url") or f"https://arbetsformedlingen.se/ad/{job_id}"
    employer = hit.get("employer") or {}
    workplace = hit.get("workplace_address") or {}
    description = hit.get("description") or {}
    return {
        "link": link,
        "company": employer.get("name", ""),
        "title": hit.get("headline", ""),
        "location": workplace.get("municipality", ""),
        "summary": description.get("text", ""),
        "source": "jobtech",
    }


def _http_get_json(url, retries=3, backoff=2.0):
    """GET JSON，对限流/5xx/网络抖动指数退避重试（spec §9）。"""
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


def fetch(config, http_get=_http_get_json):
    """执行所有查询，返回按 link 去重的标准化岗位列表。http_get 可注入以便测试。"""
    seen = {}
    for params in build_queries(config):
        # municipality 是多值参数，doseq 展开
        url = API_URL + "?" + urllib.parse.urlencode(params, doseq=True)
        data = http_get(url)
        for hit in data.get("hits", []):
            job = normalize_hit(hit)
            if job["link"]:
                seen[job["link"]] = job
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
