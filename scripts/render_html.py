#!/usr/bin/env python3
"""Render a readable HTML dashboard from job-scan-results.jsonl.

Usage: python3 render_html.py [--src PATH] [--out PATH]
Defaults to paths from config.py.
"""
import argparse
import datetime
import html
import json
import os
import sys
from urllib.parse import urlsplit

SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, SCRIPT_DIR)
from config import RESULTS, HTML
import apply_docs

PALETTE = [
    "#2563eb", "#7c3aed", "#059669", "#c2410c", "#0891b2",
    "#d946ef", "#ea580c", "#0284c7", "#65a30d", "#dc2626",
]

STATUS_BADGE = {
    "shortlisted": ("#b45309", "#fef3c7"), "reviewed": ("#374151", "#e5e7eb"),
    "applied": ("#065f46", "#d1fae5"), "rejected": ("#7f1d1d", "#fecaca"),
    "ignored": ("#991b1b", "#fee2e2"), "new": ("#1e40af", "#dbeafe"),
}


def esc(s):
    return html.escape(str(s or ""))


def safe_href(link):
    """Only allow http(s) links to be rendered as clickable — scraped career
    pages are untrusted and could contain a javascript: URI."""
    if not isinstance(link, str):
        return ""
    try:
        parsed = urlsplit(link)
    except ValueError:
        return ""
    if parsed.scheme.lower() not in ("http", "https"):
        return ""
    if not parsed.hostname:
        return ""
    return link


def score_color(s):
    s = s or 0
    if s >= 80: return "#dc2626"
    if s >= 70: return "#ea580c"
    if s >= 60: return "#ca8a04"
    return "#9ca3af"


def build_lane_colors(rows):
    lanes = []
    for r in rows:
        l = r.get("lane", "")
        if l and l not in lanes:
            lanes.append(l)
    return {lane: PALETTE[i % len(PALETTE)] for i, lane in enumerate(lanes)}


def risk_flags(r):
    sl = (r.get("summary") or "").lower()
    flags = []
    if any(k in sl for k in (
        "swedish citizenship", "swedish citizen", "must be a swedish citizen",
        "swedish work permit", "valid work permit", "right to work in sweden",
        "work permit in sweden", "eu/eea citizenship", "eu / eea citizenship",
    )):
        flags.append("Citizenship/permit required")
    if any(k in sl for k in (
        "security clearance", "security vetting", "säkerhetsprövning",
        "säkerhetsklass",
    )):
        flags.append("Security clearance")
    if r.get("lang_gate") is True:
        flags.append("Swedish required")
    return flags


def _is_gated(r):
    return any(r.get(g) for g in ("lang_gate", "citizenship_gate", "staffing_gate", "occupation_gate"))


DOC_LABELS = (("cv", "CV"), ("cover_letter", "Cover letter"))


def docs_html(st):
    """Download links + generation state for one job (mirrors docLinks() in the page JS)."""
    base = "/files/" + esc(st["dir"]) + "/"
    parts = [f'<a href="{base}{f}" target="_blank">{f}</a>' for f in st["files"]]
    for kind, label in DOC_LABELS:
        state = st[kind].get("state")
        if state == "running":
            parts.append(f'<span class="gen">{label} generating…</span>')
        elif state == "failed":
            parts.append(f'<span class="genfail">{label} failed (see {kind}.log)</span>')
    return " · ".join(parts)


def render(src, out):
    all_rows = [json.loads(l) for l in open(src, encoding="utf-8") if l.strip()]
    n_ignored = sum(1 for r in all_rows if r.get("status") == "ignored")
    n_gated = sum(1 for r in all_rows if _is_gated(r))
    rows = [r for r in all_rows if r.get("status") != "ignored" and not _is_gated(r)]
    rows.sort(key=lambda r: r.get("score", 0) or 0, reverse=True)

    lane_colors = build_lane_colors(rows)
    n_total = len(rows)
    n_pend = sum(1 for r in rows if r.get("status") == "shortlisted")
    n_unprocessed = sum(1 for r in rows if r.get("status", "") in ("", "new"))
    n_scored = sum(1 for r in rows if r.get("score"))
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    trs = []
    for i, r in enumerate(rows, 1):
        lane = r.get("lane", "")
        lc = lane_colors.get(lane, "#6b7280")
        sc = r.get("score", "")
        status = r.get("status", "")
        sfg, sbg = STATUS_BADGE.get(status, ("#374151", "#e5e7eb"))
        loc = r.get("location") or ""
        applied = ' <span class="flag">maybe applied</span>' if r.get("maybe_applied") else ""
        link = r.get("link", "")
        href = safe_href(link)
        risks = risk_flags(r)
        risk_html = f'<div class="risk">⚠ {esc(" · ".join(risks))}</div>' if risks else ""
        btns = "".join(
            f'<button class="act" onclick="mark(this,\'{s}\')"{" disabled" if status == s else ""}>{label}</button>'
            for s, label in (("applied", "Applied"), ("rejected", "Rejected"), ("reviewed", "Reviewed"), ("ignored", "Ignore"))
        )
        btns += ('<br><button class="doc" onclick="genDoc(this,\'cv\')">Tailor CV</button>'
                 '<button class="doc" onclick="genDoc(this,\'cover_letter\')">Cover letter</button>')
        st = apply_docs.status_for_row(r)
        running = any(st[k].get("state") == "running" for k, _ in DOC_LABELS)
        has_cv = "1" if "cv.tex" in st["files"] else "0"
        btns += f'<div class="docs" data-hascv="{has_cv}">{docs_html(st)}</div>'
        trs.append(f"""<tr data-link="{esc(link)}" data-running="{int(running)}">
<td class="num">{i}</td>
<td class="score" style="color:{score_color(sc)}">{esc(sc)}</td>
<td><span class="lane" style="background:{lc}1a;color:{lc}">{esc(lane)}</span></td>
<td class="company">{esc(r.get('company',''))}</td>
<td class="title">{esc(r.get('title',''))}</td>
<td class="loc">{esc(loc)}</td>
<td class="reason">{risk_html}{esc(r.get('reason',''))}</td>
<td><span class="status" style="color:{sfg};background:{sbg}">{esc(status)}</span>{applied}</td>
<td>{f'<a href="{esc(href)}" target="_blank">↗</a>' if href else ''}</td>
<td class="acts">{btns}</td>
</tr>""")

    status_color_json = json.dumps(
        {k: list(v) for k, v in STATUS_BADGE.items() if k != "ignored"},
        ensure_ascii=False,
    )

    doc = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>job-scan Results</title>
<style>
:root {{ font-family: -apple-system, "Segoe UI", sans-serif; }}
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
.risk {{ display:inline-block; margin-bottom:5px; padding:2px 8px; border-radius:6px; background:#fee2e2; color:#991b1b; font-size:12px; font-weight:600; }}
.status {{ padding:2px 8px; border-radius:6px; font-size:12px; font-weight:600; white-space:nowrap; }}
.flag {{ font-size:11px; color:#b91c1c; }}
a {{ color:#2563eb; text-decoration:none; font-size:16px; }}
.acts {{ white-space:nowrap; }}
.act {{ border:1px solid #cbd5e1; background:#fff; border-radius:6px; padding:3px 8px; font-size:12px; cursor:pointer; margin-right:4px; }}
.act:hover:not(:disabled) {{ background:#f1f5f9; }}
.act:disabled {{ opacity:.35; cursor:default; }}
.doc {{ border:1px solid #6366f1; color:#4338ca; background:#eef2ff; border-radius:6px; padding:3px 8px; font-size:12px; cursor:pointer; margin:4px 4px 0 0; }}
.doc:disabled {{ opacity:.4; cursor:default; }}
.docs {{ font-size:11px; margin-top:4px; white-space:normal; max-width:260px; }}
.gen {{ color:#4338ca; }} .genfail {{ color:#b91c1c; }}
#toast {{ position:fixed; bottom:20px; left:50%; transform:translateX(-50%); background:#0f172a; color:#fff; padding:8px 16px; border-radius:8px; font-size:13px; display:none; z-index:99; }}
</style></head>
<body>
<header>
<h1>job-scan Results</h1>
<div class="meta">Generated {now} · Use review server for one-click status updates</div>
<div class="stats">
<span class="stat"><b>{n_total}</b> visible</span>
<span class="stat"><b>{n_scored}</b> scored</span>
<span class="stat"><b>{n_pend}</b> shortlisted</span>
<span class="stat"><b>{n_unprocessed}</b> unprocessed</span>
<span class="stat" style="color:#94a3b8"><b style="color:#94a3b8">{n_gated}</b> gated</span>
<span class="stat" style="color:#94a3b8"><b style="color:#94a3b8">{n_ignored}</b> ignored</span>
</div>
<div class="controls">
<button data-f="all" class="active" onclick="flt(this)">All</button>
<button data-f="shortlisted" onclick="flt(this)">Shortlisted</button>
<button data-f="unprocessed" onclick="flt(this)">Unprocessed</button>
<button data-f="hi" onclick="flt(this)">≥70 pts</button>
</div>
</header>
<div class="wrap">
<table id="t">
<thead><tr><th>#</th><th>Score</th><th>Lane</th><th>Company</th><th>Title</th><th>Location</th><th>Reason</th><th>Status</th><th>Link</th><th>Actions</th></tr></thead>
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
    let show=true;
    if(f==='shortlisted') show=status.includes('shortlisted');
    else if(f==='unprocessed') show=!status||status==='new';
    else if(f==='hi') show=score>=70;
    tr.style.display=show?'':'none';
  }});
}}
const STATUS_COLOR={status_color_json};
function toast(msg){{
  const t=document.getElementById('toast');
  t.textContent=msg; t.style.display='block';
  clearTimeout(t._h); t._h=setTimeout(()=>t.style.display='none',2500);
}}
async function mark(btn,status){{
  const tr=btn.closest('tr'), link=tr.dataset.link;
  if(location.protocol==='file:'){{
    toast('file:// mode cannot write — open via review server instead');
    return;
  }}
  btn.disabled=true;
  try{{
    const res=await fetch('/api/status',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{link,status}})}});
    if(!res.ok) throw new Error(await res.text());
    if(status==='ignored'){{ tr.style.opacity='.3'; setTimeout(()=>tr.remove(),300); toast('Ignored'); return; }}
    const badge=tr.querySelector('.status');
    badge.textContent=status;
    const [fg,bg]=STATUS_COLOR[status]||["#374151","#e5e7eb"];
    badge.style.color=fg; badge.style.background=bg;
    tr.querySelectorAll('.act').forEach(b=>b.disabled=(b.textContent.toLowerCase()===status));
    toast('Marked: '+status);
  }}catch(e){{ btn.disabled=false; toast('Failed: '+e.message); }}
}}
const DOC_LABELS=[['cv','CV'],['cover_letter','Cover letter']];
function docLinks(st){{
  const base='/files/'+encodeURIComponent(st.dir)+'/';
  const parts=st.files.map(f=>'<a href="'+base+f+'" target="_blank">'+f+'</a>');
  for(const [k,label] of DOC_LABELS){{
    if(st[k].state==='running') parts.push('<span class="gen">'+label+' generating…</span>');
    else if(st[k].state==='failed') parts.push('<span class="genfail">'+label+' failed (see '+k+'.log)</span>');
  }}
  return parts.join(' · ');
}}
async function pollDoc(tr){{
  const box=tr.querySelector('.docs');
  const res=await fetch('/api/doc-status?link='+encodeURIComponent(tr.dataset.link));
  if(!res.ok) return;
  const st=await res.json();
  box.innerHTML=docLinks(st);
  box.dataset.hascv=st.files.includes('cv.tex')?'1':'0';
  const running=DOC_LABELS.some(([k])=>st[k].state==='running');
  tr.querySelectorAll('.doc').forEach(b=>b.disabled=running);
  if(running) setTimeout(()=>pollDoc(tr),5000);
  else if(tr.dataset.running==='1') toast('Finished: '+(tr.querySelector('.company').textContent));
  tr.dataset.running=running?'1':'0';
}}
async function genDoc(btn,kind){{
  const tr=btn.closest('tr'), link=tr.dataset.link, box=tr.querySelector('.docs');
  if(location.protocol==='file:'){{ toast('file:// mode cannot generate — open via review server instead'); return; }}
  let force=false;
  if(kind==='cv'&&box.dataset.hascv==='1'){{
    if(!confirm('This job already has a cv.tex. Regenerating starts again from the base CV and overwrites any manual edits. Continue?')) return;
    force=true;
  }}
  tr.querySelectorAll('.doc').forEach(b=>b.disabled=true);
  try{{
    const res=await fetch('/api/doc',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{link,kind,force}})}});
    const st=await res.json();
    if(!res.ok) throw new Error(st.error||res.status);
    box.innerHTML=docLinks(st);
    tr.dataset.running='1';
    toast('Generating… about 1–3 minutes');
    setTimeout(()=>pollDoc(tr),5000);
  }}catch(e){{ tr.querySelectorAll('.doc').forEach(b=>b.disabled=false); toast('Failed: '+e.message); }}
}}
if(location.protocol!=='file:') document.querySelectorAll('tr[data-running="1"]').forEach(pollDoc);
</script>
<div id="toast"></div>
</body></html>"""

    with open(out, "w", encoding="utf-8") as f:
        f.write(doc)
    print(f"wrote {out} ({n_total} visible, {n_gated} gated, {n_ignored} ignored)")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--src", default=RESULTS)
    p.add_argument("--out", default=HTML)
    args = p.parse_args()
    render(args.src, args.out)


if __name__ == "__main__":
    main()
