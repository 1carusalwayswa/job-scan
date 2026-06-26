#!/usr/bin/env python3
"""Configurable profile-gap detector (pre-LLM, zero tokens).

Reads tool-stack gap groups from preferences.toml [gates.profile_gaps].
Flags jobs whose JD text matches patterns the user's profile lacks,
so the LLM scorer can apply the appropriate cap.

Trigger logic per group: ≥2 patterns from any single group
OR patterns from ≥2 groups → flag with group's gate key.

Config example in preferences.toml:

    [[gates.profile_gaps.groups]]
    name = "control_systems"
    gate_key = "control_stack_gate"
    cap = 50
    patterns = ["matlab", "simulink", "targetlink", "canoe", "capl", "dspace", "hil", "sil"]

    [[gates.profile_gaps.groups]]
    name = "jvm_stack"
    gate_key = "jvm_gate"
    cap = 55
    patterns = ["\\bjava\\b", "spring boot", "kotlin", "\\bjvm\\b"]

Patterns are compiled as case-insensitive regexes. Use \\b for word boundaries.
"""
import argparse
import json
import os
import re
import sys

SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, SCRIPT_DIR)
from config import load_preferences


def load_gap_groups(prefs=None):
    """Return list of gap group dicts from preferences."""
    if prefs is None:
        prefs = load_preferences()
    raw = prefs.get("gates", {}).get("profile_gaps", {}).get("groups", [])
    groups = []
    for g in raw:
        compiled = []
        for p in g.get("patterns", []):
            try:
                compiled.append(re.compile(p, re.IGNORECASE))
            except re.error:
                compiled.append(re.compile(re.escape(p), re.IGNORECASE))
        groups.append({
            "name": g.get("name", "unnamed"),
            "gate_key": g.get("gate_key", f"{g.get('name', 'gap')}_gate"),
            "cap": g.get("cap", 55),
            "patterns": compiled,
            "raw_patterns": g.get("patterns", []),
        })
    return groups


def detect(summary: str, groups: list):
    """Check all gap groups against a JD summary.

    Returns list of (gate_key, cap, matched_signals) for each triggered group.
    """
    results = []
    sub_group_hits = {}
    for g in groups:
        hits = []
        for i, pat in enumerate(g["patterns"]):
            if pat.search(summary):
                hits.append(g["raw_patterns"][i])
        if hits:
            sub_group_hits[g["name"]] = (g, hits)

    for name, (g, hits) in sub_group_hits.items():
        if len(hits) >= 2:
            results.append((g["gate_key"], g["cap"], hits))

    if not results and len(sub_group_hits) >= 2:
        all_signals = []
        min_cap = 100
        gate_keys = []
        for name, (g, hits) in sub_group_hits.items():
            all_signals.extend(hits)
            min_cap = min(min_cap, g["cap"])
            gate_keys.append(g["gate_key"])
        results.append((gate_keys[0], min_cap, all_signals))

    return results


def main(argv=None):
    p = argparse.ArgumentParser(
        description="Flag jobs matching user-defined profile gap patterns"
    )
    p.add_argument("--in", dest="inp", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)

    groups = load_gap_groups()
    if not groups:
        print("No profile_gaps groups configured in preferences.toml, skipping", file=sys.stderr)
        if not args.dry_run and args.inp != args.out:
            import shutil
            shutil.copy2(args.inp, args.out)
        return

    rows, n_flagged = [], 0
    with open(args.inp, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            rows.append(d)
            if d.get("score") is not None:
                continue
            summary = d.get("summary") or ""
            triggered = detect(summary, groups)
            if triggered:
                for gate_key, cap, signals in triggered:
                    d[gate_key] = True
                    d[f"{gate_key}_signals"] = signals
                    d[f"{gate_key}_cap"] = cap
                n_flagged += 1

    group_names = ", ".join(g["name"] for g in groups)
    print(
        f"{n_flagged}/{len(rows)} flagged by profile-gap signals ({group_names})",
        file=sys.stderr,
    )
    if not args.dry_run:
        with open(args.out, "w", encoding="utf-8") as f:
            for d in rows:
                f.write(json.dumps(d, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
