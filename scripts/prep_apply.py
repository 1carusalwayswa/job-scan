#!/usr/bin/env python3
"""prep_apply.py -- Prepare application directories with JD summaries.

Usage:
  prep_apply.py --list [--min-score N]      List candidate jobs
  prep_apply.py --prep LINK [LINK ...]      Create directories + write job_summary.md
  prep_apply.py --top N [--min-score N]     Same as --prep for the N highest-scored candidates
    --cv [--variant V]                      Also copy the base CV (picked by lane) to cv.tex
  prep_apply.py --build DIR [DIR ...]       Write changes.diff + overleaf.zip, compile the CV
                                           (and cover letter) PDFs with Tectonic
"""
import argparse
import difflib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, SCRIPT_DIR)
from config import (RESULTS, APPLICATIONS_DIR, CV_BASE_DIR, CV_TEMPLATE_DIR,
                    CV_VARIANTS, CV_PDF, LETTER_PDF)

SKIP_STATUS = {"ignored", "applied"}
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


def pick_variant(row, override=None):
    with open(CV_VARIANTS) as f:
        cfg = json.load(f)
    v = override or cfg["lanes"].get(row.get("lane") or "", cfg["default"])
    if v not in cfg["variants"]:
        raise SystemExit(f"unknown CV variant {v!r}; choose from: {', '.join(cfg['variants'])}")
    return v


def copy_cv(d, row, variant, force):
    """Copy the base CV into the job dir as cv.tex (edited) + cv_base.tex (diff baseline)."""
    v = pick_variant(row, variant)
    dst = os.path.join(d, "cv.tex")
    if os.path.exists(dst) and not force:
        print(f"skip cv (exists, use --force): {dst}", file=sys.stderr)
        return
    src = os.path.join(CV_BASE_DIR, f"{v}.tex")
    shutil.copyfile(src, dst)
    shutil.copyfile(src, os.path.join(d, "cv_base.tex"))
    print(f"cv:      {dst}  (base variant: {v})")


def cmd_prep(args):
    rows = load_rows()
    by_link = {o.get("link"): o for o in rows}
    if args.top:
        args.links = [o["link"] for o in candidates(rows, args.min_score)[:args.top]]
    os.makedirs(APPLICATIONS_DIR, exist_ok=True)
    made, skipped = [], []
    for link in args.links:
        o = by_link.get(link)
        if o is None:
            print(f"warning: link not found: {link}", file=sys.stderr)
            skipped.append(link)
            continue
        d = os.path.join(APPLICATIONS_DIR, dir_name(o))
        os.makedirs(d, exist_ok=True)
        summary_path = os.path.join(d, "job_summary.md")
        if os.path.exists(summary_path) and not args.force:
            print(f"skip summary (exists, use --force): {summary_path}", file=sys.stderr)
        else:
            with open(summary_path, "w") as f:
                f.write(JOB_SUMMARY_TMPL.format(
                    company=o.get("company", ""), title=o.get("title", ""),
                    link=o.get("link", ""), location=o.get("location", ""),
                    source=o.get("source", ""), score=o.get("score", ""),
                    lane=o.get("lane", ""), reason=o.get("reason", ""),
                    summary=o.get("summary", "")))
            print(f"created: {summary_path}")
        if args.cv:
            copy_cv(d, o, args.variant, args.force)
        made.append((d, o))
    if made:
        print(f"\n{len(made)} job directories ready.")
    if skipped:
        print(f"{len(skipped)} skipped.", file=sys.stderr)


def tex_words(path):
    """Rough visible-word count of a .tex file (comments and commands stripped)."""
    with open(path, encoding="utf-8") as f:
        text = re.sub(r"(?<!\\)%.*", "", f.read())
    text = re.sub(r"\\[a-zA-Z]+\*?(\[[^\]]*\])?", " ", text)
    return len(re.findall(r"[A-Za-z0-9]{2,}", text))


def template_files():
    out = []
    if os.path.isdir(CV_TEMPLATE_DIR):
        for root, _, files in os.walk(CV_TEMPLATE_DIR):
            out += [os.path.join(root, f) for f in files if f != ".DS_Store"]
    return out


def compile_tex(tex, pdf_out):
    """Compile tex with Tectonic next to the template files. Returns (pages, error_excerpt)."""
    exe = shutil.which("tectonic") or "/opt/homebrew/bin/tectonic"
    if not os.path.exists(exe):
        return None, "tectonic not installed (brew install tectonic)"
    with tempfile.TemporaryDirectory() as tmp:
        for f in template_files():
            dst = os.path.join(tmp, os.path.relpath(f, CV_TEMPLATE_DIR))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copyfile(f, dst)
        shutil.copyfile(tex, os.path.join(tmp, "doc.tex"))
        proc = subprocess.run([exe, "-X", "compile", "--keep-logs", "doc.tex"],
                              cwd=tmp, capture_output=True, text=True)
        log_path = os.path.join(tmp, "doc.log")
        log = open(log_path, encoding="utf-8", errors="replace").read() if os.path.exists(log_path) else ""
        pdf = os.path.join(tmp, "doc.pdf")
        if proc.returncode != 0 or not os.path.exists(pdf):
            lines = log.splitlines()
            errs = [" | ".join(lines[i:i + 3]) for i, l in enumerate(lines) if l.startswith("!")]
            return None, "\n".join(errs[:5]) or proc.stderr.strip()[-1500:]
        shutil.copyfile(pdf, pdf_out)
        m = re.search(r"Output written on \S+ \((\d+) pages?", log)
        return (int(m.group(1)) if m else None), None


def build_cv(d, tfiles, errors):
    """changes.diff + overleaf.zip + CV PDF for one job dir; LaTeX errors go to errors."""
    cv, base = os.path.join(d, "cv.tex"), os.path.join(d, "cv_base.tex")
    if os.path.exists(base):
        with open(base, encoding="utf-8") as f1, open(cv, encoding="utf-8") as f2:
            diff = difflib.unified_diff(f1.readlines(), f2.readlines(), "cv_base.tex", "cv.tex")
            with open(os.path.join(d, "changes.diff"), "w", encoding="utf-8") as out:
                out.writelines(diff)
        b, t = tex_words(base), tex_words(cv)
        print(f"{os.path.basename(d)}: {b} -> {t} words ({(t - b) * 100 / b:+.0f}%)")
    zpath = os.path.join(d, "overleaf.zip")
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(cv, "main.tex")
        letter = os.path.join(d, "cover_letter.tex")
        if os.path.exists(letter):
            z.write(letter, "cover_letter.tex")
        for f in tfiles:
            z.write(f, os.path.relpath(f, CV_TEMPLATE_DIR))
    print(f"  zip: {zpath}")
    pages, err = compile_tex(cv, os.path.join(d, CV_PDF))
    if err:
        errors.append(f"cv.tex:\n{err}")
        return
    note = ""
    if os.path.exists(base):
        with tempfile.TemporaryDirectory() as tmp:
            base_pages, _ = compile_tex(base, os.path.join(tmp, "base.pdf"))
        if base_pages and pages and pages > base_pages:
            note = f"  <- more pages than the base ({base_pages}), trim"
    print(f"  pdf: {os.path.join(d, CV_PDF)} ({pages} pages){note}")


def cmd_build(args):
    tfiles = template_files()
    if not any(f.endswith(".cls") for f in tfiles):
        print(f"warning: no .cls in {CV_TEMPLATE_DIR} — the CV will not compile "
              "until developercv.cls is added there", file=sys.stderr)
    failed = False
    for d in args.dirs:
        errors = []
        if os.path.exists(os.path.join(d, "cv.tex")):
            build_cv(d, tfiles, errors)
        letter = os.path.join(d, "cover_letter.tex")
        if os.path.exists(letter):
            pages, err = compile_tex(letter, os.path.join(d, LETTER_PDF))
            if err:
                errors.append(f"cover_letter.tex:\n{err}")
            else:
                note = "  <- longer than one page, trim" if pages and pages > 1 else ""
                print(f"  pdf: {os.path.join(d, LETTER_PDF)} ({pages} pages){note}")
        if not os.path.exists(os.path.join(d, "cv.tex")) and not os.path.exists(letter):
            print(f"skip (no cv.tex or cover_letter.tex): {d}", file=sys.stderr)
            continue
        err_path = os.path.join(d, "build_errors.txt")
        if errors:
            failed = True
            with open(err_path, "w", encoding="utf-8") as f:
                f.write("\n\n".join(errors) + "\n")
            print(f"  LaTeX errors -> {err_path}", file=sys.stderr)
        elif os.path.exists(err_path):
            os.remove(err_path)
    if failed:
        sys.exit(1)


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--list", action="store_true")
    g.add_argument("--prep", nargs="+", metavar="LINK", dest="links")
    g.add_argument("--top", type=int, metavar="N")
    g.add_argument("--build", nargs="+", metavar="DIR", dest="dirs")
    p.add_argument("--min-score", type=int, default=DEFAULT_MIN_SCORE)
    p.add_argument("--cv", action="store_true", help="also copy the base CV into each job dir")
    p.add_argument("--variant", help="override the lane-based CV variant (see cv/variants.json)")
    p.add_argument("--force", action="store_true")
    args = p.parse_args()

    if args.list:
        cmd_list(args)
    elif args.links or args.top:
        cmd_prep(args)
    elif args.dirs:
        cmd_build(args)


if __name__ == "__main__":
    main()
