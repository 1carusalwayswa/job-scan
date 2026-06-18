#!/usr/bin/env python3
"""确定性瑞典语硬门槛预过滤。

在 LLM 打分之前跑：对每个岗位的 summary 检测"要求精通/流利瑞典语"的高置信短语。
命中 → 就地写 score=8 / lang_gate=true / reason 前缀「瑞典语硬要求(机械门控)」，
LLM 打分阶段须跳过这些（已带 score 且 lang_gate=true）。

为什么机械化：纯 prompt 指令曾连续 3 次失败（LLM 在 reason 写「排除」却给 76-82 分）。
散文绑不住分数，确定性短语匹配才绑得住。

只匹配高置信硬短语 + 白名单豁免，宁可漏（留给 LLM 软判断）也不误杀。
"""
import argparse
import json
import re
import sys

# 高置信硬门槛短语（命中即要求精通瑞典语）。小写匹配。
HARD_PATTERNS = [
    r"flytande\s+(i\s+|på\s+)?svenska",
    r"svenska\s+(flytande|i\s+tal\s+och\s+skrift|i\s+både\s+tal\s+och\s+skrift)",
    r"god\s+kommunikativ\s+förmåga\s+på\s+svenska",
    r"goda\s+kunskaper\s+i\s+svenska\s+(i\s+)?(tal\s+och\s+skrift|både)",
    # svenska 与 "tal och skrift" 之间夹着 "och engelska / både / i" 等间隔
    # （瑞典语+英语并列、口笔都要的最常见写法，旧 pattern 因 svenska 后非紧跟而漏网）
    r"\bsvenska\b[^.\n]{0,35}\btal\s+och\s+skrift\b",
    r"obehindrat\s+på\s+svenska",
    r"(fluent|fluency)\s+in\s+swedish",
    r"(professional|native|excellent)\s+(level\s+of\s+)?swedish",
    r"swedish[^.]{0,45}(in\s+speech\s+and\s+writing|verbally\s+and\s+in\s+writing|"
    r"in\s+writing\s+and\s+speech|spoken\s+and\s+written|both\s+spoken\s+and\s+written)",
    r"(speak|write|communicate)[^.]{0,30}fluently\s+in\s+swedish",
    # 「能用瑞典语交谈/沟通」——口语硬要求（即便不带 fluent），Ascom 类漏网
    r"\b(converse|communicate|conversational|proficiency)\s+(in\s+)?swedish\b",
    r"ability\s+to\s+converse[^.]{0,20}swedish",
]

# 豁免语境：硬短语命中处附近若含这些词，视为「加分项/雇佣条款/机构名」，不算硬门槛。
EXEMPT_NEAR = re.compile(
    r"meriterande|är\s+ett\s+plus|is\s+a\s+plus|önskvärt|fördel|nice\s+to\s+have|"
    r"collective\s+agreement|kollektivavtal|or\s+english|eller\s+engelska|swedish\s+(university|company|market)|"
    r"(additional\s+)?merits?\b",
    re.IGNORECASE,
)

# 段标题级豁免：bullet point 上方的 section header 若含这些词，该 section 下的硬短语不算门槛。
_MERIT_HEADER = re.compile(
    r"(additional\s+)?merits?\b|meriterande|nice\s+to\s+have|önskvärd|bonus\s+(if|qualif)|"
    r"preferred\s+(qualif|skill)|desired\s+(qualif|skill)|fördel|plus\s+if\s+you",
    re.IGNORECASE,
)

_BULLET_PREFIX = re.compile(r"^\s*[·\-\*•–]\s")

WINDOW = 60  # 豁免词检测窗口（硬短语命中位置前后字符数）

GATE_SCORE = 8


def _find_section_header(summary: str, pos: int) -> str:
    """从 pos 往上扫，跳过 bullet 和空行，返回最近的段标题行（非 bullet 非空行）。"""
    line_start = summary.rfind("\n", 0, pos)
    cursor = line_start if line_start != -1 else 0
    while cursor > 0:
        prev_nl = summary.rfind("\n", 0, cursor)
        seg_start = prev_nl + 1 if prev_nl != -1 else 0
        line = summary[seg_start:cursor].strip()
        cursor = seg_start
        if not line:
            continue
        if _BULLET_PREFIX.match(line):
            continue
        return line
    return ""


def is_swedish_hard_required(summary: str):
    """返回 (命中?, 命中的短语片段) 。命中处附近有豁免词则不算。

    豁免上下文截断在换行处：豁免词须与硬短语同行（bullet 列表）才生效，
    否则下一行的「Meriterande:」段落标题会落进窗口、把上一行的硬要求误豁免。

    额外检查：向上扫描最近的段标题（跳过 bullet 和空行），若段标题含
    merit/meriterande/nice-to-have 等词，视为加分项段落，不算硬门槛。
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
            header = _find_section_header(summary, start)
            if header and _MERIT_HEADER.search(header):
                continue
            return True, summary[start:end]
    return False, ""


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--in", dest="inp", required=True, help="flagged.jsonl 待打分岗位")
    p.add_argument("--out", required=True, help="输出（就地标记后）")
    p.add_argument("--dry-run", action="store_true", help="只报告命中，不写文件")
    args = p.parse_args(argv)

    rows, gated = [], []
    with open(args.inp, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            hit, frag = is_swedish_hard_required(d.get("summary", "") or "")
            # JobTech 结构化字段：雇主自报的语言硬要求（零猜测，覆盖率低但精度高，
            # 兜住正文无固定短语的边角）。字段缺失（career 源/旧数据）静默跳过。
            if not hit:
                for lang in d.get("must_have_languages") or []:
                    if "svensk" in lang.lower():
                        hit, frag = True, f"must_have.languages: {lang}"
                        break
            if hit:
                d["lang_gate"] = True
                d["score"] = GATE_SCORE
                # lane 是赛道维度，不用「已忽略」这类状态值污染；门控岗 lane 保持原样/留空
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
