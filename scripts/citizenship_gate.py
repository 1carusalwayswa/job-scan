#!/usr/bin/env python3
"""确定性国籍/安全审查硬门槛预过滤（LLM 之前，零 token）。

对中国公民不可投的两类岗，机械降到 score=8 / citizenship_gate=true：

1. 机构黑名单（assets/restricted_employers.json）：SAAB 及明确涉密的
   国防机关 / 中央安全机构（FRA、FMV、Försvarsmakten、SÄPO、Statskontoret、
   FOI…）。这些即便 JD 正文没写国籍/安审信号，按机构属性也默认有国籍要求。
   依据：用户领域知识——「SAAB / 这种政府机关明确不招中国人」。

2. 信号词：JD 正文写明 säkerhetsprövning / säkerhetsskydd / säkerhetsklass /
   svenskt medborgarskap / Swedish citizenship / security clearance 等
   人员安全审查或公民权硬要求 → 中国公民铁定过不了。

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

GATE_SCORE = 8


def load_restricted(path=RESTRICTED_CONFIG):
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)
    pats = cfg.get("company_patterns", [])
    pattern = re.compile(
        r"\b(" + "|".join(re.escape(p) for p in pats) + r")\b", re.IGNORECASE
    )
    return pattern, cfg.get("gate_score", GATE_SCORE)


def classify(company: str, summary: str, company_re):
    """返回 (命中?, 原因片段)。机构黑名单优先，其次信号词。"""
    m = company_re.search(company or "")
    if m:
        return True, f"机构黑名单:「{m.group(0)}」"
    m = SIGNAL_RE.search(summary or "")
    if m:
        return True, f"安审/国籍信号:「{m.group(0)}」"
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
                d["reason"] = (
                    f"国籍/安全审查硬门槛(机械门控:{frag})，"
                    "排除——非瑞典/EU 公民无法通过安审"
                )
                gated.append((d.get("company", ""), frag))
            rows.append(d)

    for c, frag in gated:
        print(f"  GATED  {c}  | {frag}", file=sys.stderr)
    print(f"{len(gated)}/{len(rows)} 个被国籍/安审硬门槛拦截", file=sys.stderr)

    if not args.dry_run:
        with open(args.out, "w", encoding="utf-8") as f:
            for d in rows:
                f.write(json.dumps(d, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
