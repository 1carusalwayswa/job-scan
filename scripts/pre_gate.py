#!/usr/bin/env python3
"""Deterministic company/occupation-group pre-filter (pre-LLM, zero tokens).

Two gates, same pattern as lang_gate.py (writes score in-place, skips already-scored):

1. Staffing agency gate: company name matches assets/staffing_companies.json
   -> score capped / staffing_gate=true.

2. Occupation group gate: JobTech occupation_group matches user-configured exclusion list
   -> score=18 / occupation_gate=true.
"""
import argparse
import json
import os
import re
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
from config import STAFFING_COMPANIES, load_preferences

OCCUPATION_GATE_SCORE = 18

DEFAULT_OCCUPATION_BLACKLIST = [
    "drifttekniker",
    "supporttekniker",
    "webbmaster",
    "nätverks- och systemtekniker",
    "chefer inom it",
    "it-chefer",
]


def load_staffing(path=STAFFING_COMPANIES):
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)
    pattern = re.compile(
        r"\b(" + "|".join(re.escape(p) for p in cfg["patterns"]) + r")\b",
        re.IGNORECASE,
    )
    return pattern, cfg.get("gate_score", 55)


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--in", dest="inp", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)

    prefs = load_preferences()
    staffing_score_cap = prefs.get("gates", {}).get("staffing_score_cap", 55)
    occupation_blacklist = prefs.get("gates", {}).get(
        "exclude_occupation_groups", DEFAULT_OCCUPATION_BLACKLIST
    )
    occ_lower = [b.lower() for b in occupation_blacklist]

    staffing_re, _ = load_staffing()
    rows, n_staff, n_occ = [], 0, 0
    with open(args.inp, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            rows.append(d)
            if d.get("score") is not None:
                continue
            company = d.get("company") or ""
            group = (d.get("occupation_group") or "").lower()
            if staffing_re.search(company):
                d["staffing_gate"] = True
                d["score"] = staffing_score_cap
                d["lane"] = ""
                d["reason"] = f"Staffing agency gate: \"{company.strip()}\" matched bemanning list"
                n_staff += 1
            elif group and any(b in group for b in occ_lower):
                d["occupation_gate"] = True
                d["score"] = OCCUPATION_GATE_SCORE
                d["lane"] = ""
                d["reason"] = f"Occupation group gate: \"{d['occupation_group']}\" is in exclusion list"
                n_occ += 1

    print(f"{n_staff} staffing-gated, {n_occ} occupation-gated (of {len(rows)})", file=sys.stderr)
    if not args.dry_run:
        with open(args.out, "w", encoding="utf-8") as f:
            for d in rows:
                f.write(json.dumps(d, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
