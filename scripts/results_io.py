#!/usr/bin/env python3
"""job-scan-results.jsonl 事实源读写 + keyed merge + 渲染 .md。

事实源按 link 主键存状态/分数/日期；.md 仅从事实源渲染供阅读。
合并绝不把用户已设的状态降级回「新」（根治已忽略岗位重新冒头）。
"""
import json
import sys

# 用户设过、机器不得擅自降级的状态
USER_STATUSES = {"已看", "待确认", "已转apply", "已忽略"}

MD_COLUMNS = ["发现日", "公司", "岗位", "地点", "赛道", "匹配分", "链接", "JD摘要", "状态"]


def load_jsonl(path):
    """读 jsonl 为 {link: job}。文件不存在返回空 dict。"""
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
    """按匹配分降序写 jsonl。jobs 是 {link: job}。"""
    ordered = sorted(jobs.values(), key=lambda j: j.get("score", 0), reverse=True)
    with open(path, "w", encoding="utf-8") as f:
        for job in ordered:
            f.write(json.dumps(job, ensure_ascii=False) + "\n")


def filter_unscored(existing, raw):
    """返回 raw 中 link 尚不在事实源里的岗位（仅这些需要 LLM 打分）。"""
    return [job for job in raw if job["link"] not in existing]


def filter_pending(existing):
    """返回台账里待精筛的岗位：无 score 且状态仍是「新」（未被用户处理）。

    每日无人值守脚本把新岗位以 status=新、无 score 并入台账；交互式精筛
    据此捞出 backlog 打分。已被用户三选（已看/待确认/已转apply/已忽略）的
    岗位即便无 score 也不再打扰。
    """
    return [
        job for job in existing.values()
        if "score" not in job and job.get("status") not in USER_STATUSES
    ]


def merge(existing, scored, seen_links, today):
    """把本批打分岗位按 link 合并进事实源。

    - 新 link → 插入，status=新，first_seen=last_seen=today。
    - 已有 link 在 scored 里 → 更新 score/lane/reason/summary/last_seen，保留 status 与 first_seen。
    - 已有 link 仅在 seen_links 里（本次源仍在但未重打分）→ 只刷新 last_seen。
    - 已有 link 两处都不在 → 原样保留（不删，留痕）。
    绝不把状态降级回「新」。
    """
    merged = {link: dict(job) for link, job in existing.items()}

    # 1) 本次源里仍出现的旧岗位：刷新 last_seen
    for link in seen_links:
        if link in merged:
            merged[link]["last_seen"] = today

    # 2) 本批打分岗位：插入或更新（status/first_seen 一律保留，不降级）
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
            new_job["status"] = "新"
            merged[link] = new_job
    return merged


def sanitize(text):
    """清洗自由文本，避免破坏 .md 表格：换行转空格、竖线转义。"""
    if not text:
        return ""
    return text.replace("\r", " ").replace("\n", " ").replace("|", "\\|").strip()


def render_md(jobs):
    """从事实源渲染按匹配分降序的 Markdown 表格。jobs 是 {link: job}。"""
    ordered = sorted(jobs.values(), key=lambda j: j.get("score", 0), reverse=True)
    lines = [
        "# job-scan 候选清单",
        "",
        "> 由 job-scan-results.jsonl 自动渲染，请勿手改；改状态请在对话里告诉 Claude。",
        "",
        "| " + " | ".join(MD_COLUMNS) + " |",
        "|" + "|".join(["---"] * len(MD_COLUMNS)) + "|",
    ]
    for job in ordered:
        flag = " (疑似已投)" if job.get("maybe_applied") else ""
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
    """按 link 改状态；link 不存在抛 KeyError。"""
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
    parser.add_argument("--link")
    parser.add_argument("--status")
    args = parser.parse_args(argv)

    existing = load_jsonl(args.results)

    if args.mode == "diff":
        raw = list(load_jsonl(args.raw).values())
        todo = filter_unscored(existing, raw)
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
        set_status(existing, args.link, args.status)
        save_jsonl(args.results, existing)
        if args.md:
            with open(args.md, "w", encoding="utf-8") as f:
                f.write(render_md(existing))
        print(f"{args.link} -> {args.status}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
