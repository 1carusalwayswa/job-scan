#!/usr/bin/env python3
"""确定性国籍/安全审查硬门槛预过滤（LLM 之前，零 token）。

对非 EU 公民不可投的两类岗，机械降到 score=8 / citizenship_gate=true：

1. 机构黑名单（assets/restricted_employers.json）：SAAB 及明确涉密的
   国防机关 / 中央安全机构（FRA、FMV、Försvarsmakten、SÄPO、Statskontoret、
   FOI…）。这些即便 JD 正文没写国籍/安审信号，按机构属性也默认有国籍要求。
   依据：用户领域知识——「SAAB / 这种政府机关默认要求安全审查资格」。

2. 信号词：JD 正文写明 säkerhetsprövning / säkerhetsskydd / säkerhetsklass /
   svenskt medborgarskap / Swedish citizenship / security clearance 等
   人员安全审查或公民权硬要求 → 非 EU 公民铁定过不了。

与 lang_gate.py 同构：**无条件检测**（不看现有 score，故可全量回溯既有岗）。
只匹配人员安审/公民权的特指术语，不碰 cybersäkerhet / informationssäkerhet
这类信息安全泛指词。
"""
import argparse
import json
import os
import re
import sys

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESTRICTED_CONFIG = os.path.join(SKILL_DIR, "assets", "restricted_employers.json")

# 人员安全审查 / 公民权硬要求的特指术语。小写匹配。
# 注意 -prövning/-skydd/-klass 后缀是「人员安审」专用，不会误命中 cybersäkerhet。
SIGNAL_PATTERNS = [
    r"säkerhetspröv",                       # säkerhetsprövning/-as/-ad
    r"säkerhetsskydd",                      # säkerhetsskyddslag(en)
    r"säkerhetsklass",                      # placeras i säkerhetsklass / säkerhetsklassad
    r"svenskt\s+medborgar(skap|e)",
    r"krav\s+på\s+(svenskt\s+)?medborgarskap",
    r"swedish\s+citizen(ship)?",
    r"security\s+(clearance|vetting)",
]
SIGNAL_RE = re.compile("|".join(SIGNAL_PATTERNS), re.IGNORECASE)

# 段标题豁免：信号出现在 merit/加分项段落下时，不算硬门槛。
# 向后 400 字符内搜索 merit 段标题，同时确认中间无 requirement 段标题打断。
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
    """检查信号词是否在 merit/加分项上下文中。

    策略：向后 400 字符窗口内逐行搜索 merit 段标题。
    若找到且中间无 requirement 段标题打断，判定为 merit 上下文。
    同行出现豁免词也判定为 merit 上下文。
    """
    # 同行豁免
    nl_before = summary.rfind("\n", max(0, match_start - 80), match_start)
    line_start = nl_before + 1 if nl_before != -1 else max(0, match_start - 80)
    nl_after = summary.find("\n", match_end, min(len(summary), match_end + 80))
    line_end = nl_after if nl_after != -1 else min(len(summary), match_end + 80)
    if _EXEMPT_SAME_LINE.search(summary[line_start:line_end]):
        return True
    # 向后窗口逐行扫描：找最近的 merit 段标题，确认中间无 requirement 段标题
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
    """返回 (命中?, 原因片段)。机构黑名单优先，其次信号词（merit 上下文豁免）。"""
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
