#!/usr/bin/env python3
"""Deterministic Swedish language hard-requirement pre-filter.

Runs before LLM scoring: detects high-confidence phrases requiring fluent Swedish.
Match -> writes score=8 / lang_gate=true / reason; LLM scoring skips these.

Why deterministic: pure prompt instructions failed 3 times in a row (LLM wrote
"exclude" in reason but scored 76-82). Phrase matching enforces the gate reliably.

Only matches high-confidence hard phrases + allowlist exemptions; prefers false
negatives (left to LLM soft judgment) over false positives.
"""
import argparse
import json
import re
import sys

# High-confidence hard-requirement phrases (match = fluent Swedish required). Case-insensitive.
HARD_PATTERNS = [
    r"flytande\s+(i\s+|på\s+)?svenska",
    r"svenska\s+(flytande|i\s+tal\s+och\s+skrift|i\s+både\s+tal\s+och\s+skrift)",
    r"god\s+kommunikativ\s+förmåga\s+på\s+svenska",
    r"goda\s+kunskaper\s+i\s+svenska\s+(i\s+)?(tal\s+och\s+skrift|både)",
    # svenska ... tal och skrift with intervening words (och engelska / både / i)
    # common phrasing where svenska doesn't immediately precede tal och skrift
    r"\bsvenska\b[^.\n]{0,35}\btal\s+och\s+skrift\b",
    r"obehindrat\s+på\s+svenska",
    r"(fluent|fluency)\s+in\s+swedish",
    r"(professional|native|excellent)\s+(level\s+of\s+)?swedish",
    r"swedish[^.]{0,45}(in\s+speech\s+and\s+writing|verbally\s+and\s+in\s+writing|"
    r"in\s+writing\s+and\s+speech|spoken\s+and\s+written|both\s+spoken\s+and\s+written)",
    r"(speak|write|communicate)[^.]{0,30}fluently\s+in\s+swedish",
    # "converse/communicate in Swedish" — spoken hard requirement even without "fluent"
    r"\b(converse|communicate|conversational|proficiency)\s+(in\s+)?swedish\b",
    r"ability\s+to\s+converse[^.]{0,20}swedish",
]

# Exemption context: nearby words indicating merit/employment terms/org names, not hard requirements.
EXEMPT_NEAR = re.compile(
    r"meriterande|är\s+ett\s+plus|is\s+a\s+plus|önskvärt|fördel|nice\s+to\s+have|"
    r"collective\s+agreement|kollektivavtal|or\s+english|eller\s+engelska|swedish\s+(university|company|market)|"
    r"(additional\s+)?merits?\b",
    re.IGNORECASE,
)

# Section-header exemption: search 400-char window for merit header, confirm no requirement header intervenes.
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

WINDOW = 60  # chars before/after match for same-line exemption check

GATE_SCORE = 8


_MERIT_LINE_START = re.compile(
    r"^\s*(?:meriterande|(?:additional\s+)?merits?|nice\s+to\s+have|"
    r"preferred\s+(?:qualif|skill)|desired\s+(?:qualif|skill)|"
    r"bonus\s+(?:if|qualif)|plus\s+if\s+you|önskvärd)",
    re.IGNORECASE,
)


def _line_is_merit_header(line: str) -> bool:
    """Check if a line is a merit section header. Keyword must appear at line start."""
    stripped = line.strip()
    if not stripped or len(stripped) > 60:
        return False
    return bool(_MERIT_LINE_START.match(stripped))


def _is_in_merit_section(summary: str, pos: int) -> bool:
    """Check if pos falls within a merit/nice-to-have section.

    Scans 400-char window backward for the nearest merit section header.
    Header must be short (<50 chars) and contain merit keywords.
    Returns True if found with no requirement header intervening.
    """
    window_start = max(0, pos - 400)
    before_text = summary[window_start:pos]
    last_merit_pos = -1
    last_req_pos = -1
    offset = window_start
    for line in before_text.split("\n"):
        if _line_is_merit_header(line):
            last_merit_pos = offset
        if _REQ_HEADER.search(line):
            last_req_pos = offset
        offset += len(line) + 1
    return last_merit_pos != -1 and last_merit_pos > last_req_pos


def is_swedish_hard_required(summary: str):
    """Return (matched?, matched_phrase). Exempted if nearby context is merit/bonus.

    Three-layer exemption:
    1. Same-line: line contains meriterande/plus/nice-to-have
    2. Section: 400-char backward window has merit header with no requirement header intervening
    """
    if not summary:
        return False, ""
    low = summary.lower()
    for pat in HARD_PATTERNS:
        for m in re.finditer(pat, low):
            start, end = m.start(), m.end()
            ctx_start = max(0, start - WINDOW)
            ctx_end = min(len(summary), end + WINDOW)
            nl_before = summary.rfind("\n", ctx_start, start)
            if nl_before != -1:
                ctx_start = nl_before + 1
            nl_after = summary.find("\n", end, ctx_end)
            if nl_after != -1:
                ctx_end = nl_after
            if EXEMPT_NEAR.search(summary[ctx_start:ctx_end]):
                continue
            if _is_in_merit_section(summary, start):
                continue
            return True, summary[start:end]
    return False, ""


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--in", dest="inp", required=True, help="Input JSONL (jobs to gate)")
    p.add_argument("--out", required=True, help="Output JSONL (gated in-place)")
    p.add_argument("--dry-run", action="store_true", help="Report matches only, don't write")
    args = p.parse_args(argv)

    rows, gated = [], []
    with open(args.inp, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            hit, frag = is_swedish_hard_required(d.get("summary", "") or "")
            # JobTech structured field: employer-declared language requirements
            # (zero guessing, low coverage but high precision). Missing field silently skipped.
            if not hit:
                for lang in d.get("must_have_languages") or []:
                    if "svensk" in lang.lower():
                        hit, frag = True, f"must_have.languages: {lang}"
                        break
            if hit:
                d["lang_gate"] = True
                d["score"] = GATE_SCORE
                # lane is a scoring dimension, not polluted with status values; gated jobs keep lane empty
                d["reason"] = f"Swedish language gate: hard requirement detected (\"{frag}\")"
                gated.append((d.get("company", ""), frag))
            rows.append(d)

    for c, frag in gated:
        print(f"  GATED  {c}  | {frag}", file=sys.stderr)
    print(f"{len(gated)}/{len(rows)} gated by Swedish language requirement", file=sys.stderr)

    if not args.dry_run:
        with open(args.out, "w", encoding="utf-8") as f:
            for d in rows:
                f.write(json.dumps(d, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
