#!/usr/bin/env python3
"""从 job-scan-results.jsonl 事实源渲染人类可读 HTML 清单。

赛道配色按出现顺序从调色板动态分配（不写死赛道名）。
可选 --home 给指定地点加 📍 标记 + 一个就地筛选按钮；不传则不显示。
"""
import argparse
import datetime
import html
import json
import sys

# 中性调色板，按赛道出现顺序循环取用
PALETTE = ["#2563eb", "#7c3aed", "#0891b2", "#059669", "#d97706", "#db2777", "#65a30d"]

STATUS_BADGE = {
    "待确认": ("#b45309", "#fef3c7"), "已看": ("#374151", "#e5e7eb"),
    "已转apply": ("#065f46", "#d1fae5"), "已忽略": ("#991b1b", "#fee2e2"),
    "新": ("#1e40af", "#dbeafe"),
}


def esc(s):
    return html.escape(str(s or ""))


def score_color(s):
    s = s or 0
    if s >= 80:
        return "#dc2626"
    if s >= 70:
        return "#ea580c"
    if s >= 60:
        return "#ca8a04"
    return "#9ca3af"


def _lane_colors(rows):
    """按赛道首次出现顺序映射到调色板颜色。"""
    colors = {}
    for r in rows:
        lane = r.get("lane") or ""
        if lane and lane not in colors:
            colors[lane] = PALETTE[len(colors) % len(PALETTE)]
    return colors


def build_html(rows, home=None):
    rows = sorted(rows, key=lambda r: r.get("score", 0) or 0, reverse=True)
    lane_colors = _lane_colors(rows)
    n_total = len(rows)
    n_pend = sum(1 for r in rows if r.get("status") == "待确认")
    n_scored = sum(1 for r in rows if r.get("score"))
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    trs = []
    for i, r in enumerate(rows, 1):
        lane = r.get("lane") or ""
        lc = lane_colors.get(lane, "#6b7280")
        sc = r.get("score", "")
        status = r.get("status", "")
        sfg, sbg = STATUS_BADGE.get(status, ("#374151", "#e5e7eb"))
        loc = r.get("location") or ""
        local = "📍" if home and home in loc else ""
        applied = ' <span class="flag">疑似已投</span>' if r.get("maybe_applied") else ""
        link = r.get("link", "")
        trs.append(f"""<tr>
<td class="num">{i}</td>
<td class="score" style="color:{score_color(sc)}">{esc(sc)}</td>
<td><span class="lane" style="background:{lc}1a;color:{lc}">{esc(lane)}</span></td>
<td class="company">{esc(r.get('company',''))}</td>
<td class="title">{esc(r.get('title',''))}</td>
<td class="loc">{local} {esc(loc)}</td>
<td class="reason">{esc(r.get('reason',''))}</td>
<td><span class="status" style="color:{sfg};background:{sbg}">{esc(status)}</span>{applied}</td>
<td><a href="{esc(link)}" target="_blank">↗</a></td>
</tr>""")

    local_btn = (f'<button data-f="local" onclick="flt(this)">📍 {esc(home)}</button>'
                 if home else "")

    return f"""<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>job-scan 候选清单</title>
<style>
:root {{ font-family: -apple-system, "PingFang SC", "Segoe UI", sans-serif; }}
body {{ margin:0; background:#f8fafc; color:#1e293b; }}
header {{ padding:24px 32px 12px; background:#fff; border-bottom:1px solid #e2e8f0; position:sticky; top:0; z-index:10; }}
h1 {{ margin:0 0 6px; font-size:24px; }}
.meta {{ color:#64748b; font-size:13px; }}
.stats {{ margin-top:10px; display:flex; gap:16px; flex-wrap:wrap; }}
.stat {{ font-size:13px; }} .stat b {{ font-size:18px; color:#0f172a; }}
.controls {{ margin-top:12px; display:flex; gap:8px; flex-wrap:wrap; }}
.controls button {{ border:1px solid #cbd5e1; background:#fff; border-radius:6px; padding:5px 12px; font-size:13px; cursor:pointer; }}
.controls button.active {{ background:#0f172a; color:#fff; border-color:#0f172a; }}
.wrap {{ padding:16px 32px 60px; }}
table {{ border-collapse:collapse; width:100%; background:#fff; border-radius:10px; overflow:hidden; box-shadow:0 1px 3px rgba(0,0,0,.06); }}
th {{ background:#f1f5f9; text-align:left; padding:10px 12px; font-size:12px; color:#475569; text-transform:uppercase; letter-spacing:.03em; position:sticky; top:0; }}
td {{ padding:10px 12px; border-top:1px solid #f1f5f9; font-size:14px; vertical-align:top; }}
tr:hover td {{ background:#f8fafc; }}
.num {{ color:#94a3b8; font-variant-numeric:tabular-nums; }}
.score {{ font-weight:700; font-size:16px; font-variant-numeric:tabular-nums; }}
.lane {{ padding:2px 8px; border-radius:999px; font-size:12px; font-weight:600; white-space:nowrap; }}
.company {{ font-weight:600; }}
.title {{ max-width:240px; }}
.loc {{ white-space:nowrap; color:#475569; }}
.reason {{ max-width:380px; color:#475569; font-size:13px; line-height:1.5; }}
.status {{ padding:2px 8px; border-radius:6px; font-size:12px; font-weight:600; white-space:nowrap; }}
.flag {{ font-size:11px; color:#b91c1c; }}
a {{ color:#2563eb; text-decoration:none; font-size:16px; }}
</style></head>
<body>
<header>
<h1>job-scan 候选清单</h1>
<div class="meta">生成于 {now} · 数据源 job-scan-results.jsonl（请勿手改，改状态在对话里告诉 Claude）</div>
<div class="stats">
<span class="stat"><b>{n_total}</b> 总岗位</span>
<span class="stat"><b>{n_scored}</b> 已评分</span>
<span class="stat"><b>{n_pend}</b> 待确认</span>
</div>
<div class="controls">
<button data-f="all" class="active" onclick="flt(this)">全部</button>
<button data-f="待确认" onclick="flt(this)">待确认</button>
{local_btn}
<button data-f="hi" onclick="flt(this)">≥70 分</button>
</div>
</header>
<div class="wrap">
<table id="t">
<thead><tr><th>#</th><th>分</th><th>赛道</th><th>公司</th><th>岗位</th><th>地点</th><th>理由</th><th>状态</th><th>链</th></tr></thead>
<tbody>
{''.join(trs)}
</tbody>
</table>
</div>
<script>
function flt(btn){{
  document.querySelectorAll('.controls button').forEach(b=>b.classList.remove('active'));
  btn.classList.add('active');
  const f=btn.dataset.f;
  document.querySelectorAll('#t tbody tr').forEach(tr=>{{
    const score=parseInt(tr.children[1].textContent)||0;
    const status=tr.children[7].textContent;
    const loc=tr.children[5].textContent;
    let show=true;
    if(f==='待确认') show=status.includes('待确认');
    else if(f==='local') show=loc.includes('📍');
    else if(f==='hi') show=score>=70;
    tr.style.display=show?'':'none';
  }});
}}
</script>
</body></html>"""


def render(src, out, home=None):
    rows = [json.loads(l) for l in open(src, encoding="utf-8") if l.strip()]
    doc = build_html(rows, home=home)
    with open(out, "w", encoding="utf-8") as f:
        f.write(doc)
    n_pend = sum(1 for r in rows if r.get("status") == "待确认")
    print(f"wrote {out} ({len(rows)} rows, {n_pend} 待确认)")


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    p = argparse.ArgumentParser(description="Render job-scan results to HTML")
    p.add_argument("--results", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--home", default=None, help="给该地点加 📍 标记与筛选按钮（可选）")
    args = p.parse_args(argv)
    render(args.results, args.out, home=args.home)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
