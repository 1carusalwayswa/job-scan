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
    """从 search_config.json 配置生成查询参数列表（每个关键词一组）。

    每个返回 dict 是 /search 的 query 参数，绝不包含公司名字段。
    铁律：绝不把多个关键词拼成一个 q——JobTech 对多词 q 做整串相关性匹配
    而非任一词命中，实测 6 词拼接命中 33 条 vs 单词 systemutvecklare 671 条。
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
    """把一条 JobTech /search 命中标准化为统一岗位字典。

    link 取稳定的 webpage_url（缺失时用 id 构造），作为跨语言一致的去重主键。
    保留两个结构化字段供确定性预过滤（pre_gate/lang_gate）使用：
    occupation_group（雇主自报 SSYK 职业组，比标题正则可靠）、
    must_have_languages（雇主结构化声明的语言硬要求，覆盖率 ~13% 但零猜测）。
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
    """GET JSON，对限流/5xx/网络抖动指数退避重试。"""
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


# API 约束：offset+limit 不得超过 2000，超出部分只能放弃（命中数极少到这个量级）
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
