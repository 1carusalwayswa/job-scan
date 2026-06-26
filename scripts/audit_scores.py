#!/usr/bin/env python3
"""Post-scoring audit: detect LLM scores that violate deterministic rules.

Run after LLM scoring to catch common errors:
  1. Staffing company scored above cap
  2. Control-systems stack flag ignored
  3. ML training keywords with high score
  4. Swedish JD without penalty applied
  5. Senior/lead title above level cap
  6. Cross-source score inconsistency
"""
import argparse
import json
import os
import re
import sys
from collections import defaultdict

SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, SCRIPT_DIR)
from config import RESULTS, STAFFING_COMPANIES

SENIOR_RE = re.compile(
    r"\b(senior|staff|lead\b|principal|head\b|manager|director)\b", re.IGNORECASE
)

ML_TRAINING_RE = re.compile(
    r"train(ing|ed)?\s.{0,20}model|"
    r"develop(ing|ed|ment)?\s.{0,20}model|"
    r"design(ing|ed)?\s.{0,20}model|"
    r"ML\s*lifecycle|"
    r"\bMLOps\b|"
    r"model\s+development|"
    r"refin(ing|e)\s.{0,20}(model|method)|"
    r"build(ing)?\s.{0,20}ML",
    re.IGNORECASE,
)

SWEDISH_PENALTY_MENTIONED_RE = re.compile(r"瑞典语|Swedish|svenska", re.IGNORECASE)


def load_staffing(path):
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)
    pattern = re.compile(
        r"\b(" + "|".join(re.escape(p) for p in cfg["patterns"]) + r")\b",
        re.IGNORECASE,
    )
    return pattern


def swedish_ratio(text):
    """Fraction of characters that are non-ASCII (heuristic for Swedish text)."""
    if not text:
        return 0.0
    non_ascii = sum(1 for c in text if ord(c) > 127)
    return non_ascii / len(text)


def has_swedish_markers(text):
    """Check for common Swedish words/patterns beyond just non-ASCII ratio."""
    markers = re.compile(
        r"\b(tjänsten|uppdraget|erfarenhet|arbetsuppgifter|kvalifikationer|"
        r"kompetens|utvecklare|systemutvecklare|ansökan|meriterande|"
        r"vi\s+söker|du\s+har|anställning|heltid)\b",
        re.IGNORECASE,
    )
    hits = len(markers.findall(text or ""))
    return hits >= 4


def main(argv=None):
    p = argparse.ArgumentParser(description="Audit scored jobs for rule violations")
    p.add_argument("--results", default=RESULTS)
    p.add_argument("--staffing", default=STAFFING_COMPANIES)
    p.add_argument("--fix", action="store_true", help="Auto-correct violations in-place")
    p.add_argument("--min-score", type=int, default=55, help="Only audit jobs scored >= N")
    args = p.parse_args(argv)

    staffing_re = load_staffing(args.staffing)

    with open(args.results, encoding="utf-8") as f:
        jobs = [json.loads(l) for l in f if l.strip()]

    warnings = []
    fixes = []

    title_company_scores = defaultdict(list)
    for i, j in enumerate(jobs):
        score = j.get("score")
        if score is None or score < args.min_score:
            continue
        status = j.get("status", "新")
        if status in ("已忽略", "ignored", "已转apply", "applied"):
            continue

        company = j.get("company", "")
        title = j.get("title", "")
        summary = j.get("summary", "")
        reason = j.get("reason", "")
        label = f"{company} — {title}"

        # Rule 1: Staffing company above cap
        if score > 58 and staffing_re.search(company) and not j.get("staffing_gate"):
            warnings.append(f"WARN [staffing_above_cap] [{score}] {label} | matched staffing list, suggest ≤55")
            if args.fix:
                j["score"] = 55
                j["audit_fix"] = True
                j["reason"] = f"[audit fix: staffing cap] {reason}"
                fixes.append(i)

        # Rule 2: Control stack flag ignored
        if score > 55 and j.get("control_stack_gate"):
            warnings.append(f"WARN [control_stack_ignored] [{score}] {label} | control_stack_gate=true, suggest ≤50")
            if args.fix:
                j["score"] = 50
                j["audit_fix"] = True
                j["reason"] = f"[audit fix: control stack cap] {reason}"
                fixes.append(i)

        # Rule 3: ML training keywords + high score
        if score > 60 and ML_TRAINING_RE.search(summary):
            warnings.append(f"WARN [ml_training_check] [{score}] {label} | JD mentions ML model training/development, verify ML calibration rule")

        # Rule 4: Swedish JD + high score without penalty
        if score > 55 and has_swedish_markers(summary) and not SWEDISH_PENALTY_MENTIONED_RE.search(reason):
            warnings.append(f"WARN [swedish_jd_penalty] [{score}] {label} | JD appears Swedish, reason doesn't mention language penalty")

        # Rule 5: Senior/lead title + high score (skip already staffing-gated)
        if score > 50 and SENIOR_RE.search(title) and not j.get("staffing_gate"):
            warnings.append(f"WARN [senior_level_cap] [{score}] {label} | title suggests senior/lead level, verify ≤50 cap applies")

        # Rule 6: Collect for cross-source consistency
        norm_key = (title.strip().lower(), company.strip().lower())
        title_company_scores[norm_key].append((i, score, j.get("link", "")))

    # Rule 6: Cross-source score inconsistency
    for key, entries in title_company_scores.items():
        if len(entries) < 2:
            continue
        scores = [e[1] for e in entries]
        gap = max(scores) - min(scores)
        if gap > 5:
            title_str, company_str = key
            links = ", ".join(e[2][-30:] for e in entries)
            score_str = "/".join(str(s) for s in scores)
            warnings.append(
                f"WARN [cross_source_inconsistency] [{score_str}] {company_str} — {title_str} | "
                f"{gap}pt gap across {len(entries)} sources"
            )

    for w in warnings:
        print(w, file=sys.stderr)

    n_warn = len(warnings)
    n_fix = len(fixes)
    print(f"{n_warn} warnings, {n_fix} auto-fixed", file=sys.stderr)

    if args.fix and fixes:
        with open(args.results, "w", encoding="utf-8") as f:
            for j in jobs:
                f.write(json.dumps(j, ensure_ascii=False) + "\n")

    return 1 if n_warn > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
