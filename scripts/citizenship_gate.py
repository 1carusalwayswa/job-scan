#!/usr/bin/env python3
"""Deterministic citizenship / security clearance pre-filter (pre-LLM, zero tokens).

Gates two categories of jobs that are inaccessible to non-EU citizens:

1. Restricted employer blocklist (assets/restricted_employers.json): SAAB and
   confirmed defense/central-security agencies (FRA, FMV, Forsvarsmakten,
   SAPO, Statskontoret, FOI, etc.) that inherently require Swedish citizenship.

2. Signal words: JD text contains terms like sakerhetsklassad, svenskt
   medborgarskap, Swedish citizenship, security clearance, etc.

Unconditional check (ignores existing score) so it can retroactively gate
previously scored jobs. Only matches personnel security / citizenship-specific
terms; does not trigger on generic infosec terms like cybersakerhet.
"""
import argparse
import json
import os
import re
import sys

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESTRICTED_CONFIG = os.path.join(SKILL_DIR, "assets", "restricted_employers.json")

SIGNAL_PATTERNS = [
    r"säkerhetspröv",
    r"säkerhetsskydd",
    r"säkerhetsklass",
    r"svenskt\s+medborgar(skap|e)",
    r"krav\s+på\s+(svenskt\s+)?medborgarskap",
    r"swedish\s+citizen(ship)?",
    r"security\s+(clearance|vetting)",
]
SIGNAL_RE = re.compile("|".join(SIGNAL_PATTERNS), re.IGNORECASE)

_MERIT_HEADER = re.compile(
    r"(additional\s+)?merits?\b|meriterande|nice\s+to\s+have|önskvärd|bonus\s+(if|qualif)|"
    r"preferred\s+(qualif|skill)|desired\s+(qualif|skill)|fördel|plus\s+if\s+you",
    re.IGNORECASE,
)
_REQ_HEADER = re.compile(
    r"\b(krav|requirements?|qualifications?|your\s+background|what\s+we\s+(expect|need)|"
    r"vad\s+vi\s+söker|vi\s+söker\s+dig|befattningen\s+kräver|annat\b|"
    r"what\s+you\s+bring|who\s+you\s+are|övrigt|vi\s+erbjuder|what\s+we\s+offer|"
    r"ansökan|om\s+(tjänsten|rollen|uppdraget)|about\s+the\s+(role|position)|"
    r"uppdragsinformation|startdatum)\b",
    re.IGNORECASE,
)
_EXEMPT_SAME_LINE = re.compile(
    r"meriterande|is\s+a\s+plus|är\s+ett\s+plus|önskvärt|nice\s+to\s+have|(additional\s+)?merits?\b",
    re.IGNORECASE,
)

GATE_SCORE = 8


def load_restricted(path=RESTRICTED_CONFIG):
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)
    pats = cfg.get("company_patterns", [])
    pattern = re.compile(
        r"\b(" + "|".join(re.escape(p) for p in pats) + r")\b", re.IGNORECASE
    )
    return pattern, cfg.get("gate_score", GATE_SCORE)


def _is_in_merit_context(summary: str, match_start: int, match_end: int) -> bool:
    """Check if the signal word falls within a merit/nice-to-have section.

    Scans backward 400 chars for a merit section header. If found and not
    interrupted by a requirement section header, the signal is exempted.
    Same-line exemption words also trigger exemption.
    """
    nl_before = summary.rfind("\n", max(0, match_start - 80), match_start)
    line_start = nl_before + 1 if nl_before != -1 else max(0, match_start - 80)
    nl_after = summary.find("\n", match_end, min(len(summary), match_end + 80))
    line_end = nl_after if nl_after != -1 else min(len(summary), match_end + 80)
    if _EXEMPT_SAME_LINE.search(summary[line_start:line_end]):
        return True
    window_start = max(0, match_start - 400)
    before_text = summary[window_start:match_start]
    last_merit_pos = -1
    last_req_pos = -1
    offset = window_start
    merit_line_start = re.compile(
        r"^\s*(?:meriterande|(?:additional\s+)?merits?|nice\s+to\s+have|"
        r"preferred\s+(?:qualif|skill)|desired\s+(?:qualif|skill)|"
        r"bonus\s+(?:if|qualif)|plus\s+if\s+you|önskvärd)",
        re.IGNORECASE,
    )
    for line in before_text.split("\n"):
        stripped = line.strip()
        if stripped and len(stripped) < 60 and merit_line_start.match(stripped):
            last_merit_pos = offset
        if _REQ_HEADER.search(line):
            last_req_pos = offset
        offset += len(line) + 1
    if last_merit_pos == -1:
        return False
    if last_req_pos > last_merit_pos:
        return False
    return True


def classify(company: str, summary: str, company_re):
    """Return (hit, reason_fragment). Employer blocklist checked first, then signal words."""
    m = company_re.search(company or "")
    if m:
        return True, f"restricted employer: \"{m.group(0)}\""
    for m in SIGNAL_RE.finditer(summary or ""):
        if not _is_in_merit_context(summary, m.start(), m.end()):
            return True, f"security clearance signal: \"{m.group(0)}\""
    return False, ""


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--in", dest="inp", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)

    company_re, gate_score = load_restricted()
    rows, gated = [], []
    with open(args.inp, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            hit, frag = classify(d.get("company", ""), d.get("summary", ""), company_re)
            if hit:
                d["citizenship_gate"] = True
                d["score"] = gate_score
                d["lane"] = ""
                d["reason"] = f"Citizenship/security gate: {frag}"
                gated.append((d.get("company", ""), frag))
            rows.append(d)

    for c, frag in gated:
        print(f"  GATED  {c}  | {frag}", file=sys.stderr)
    print(f"{len(gated)}/{len(rows)} gated by citizenship/security requirement", file=sys.stderr)

    if not args.dry_run:
        with open(args.out, "w", encoding="utf-8") as f:
            for d in rows:
                f.write(json.dumps(d, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
