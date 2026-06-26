# Job-Scan Lessons Learned

Operational pitfalls discovered during use. Read before troubleshooting.

## Daily scan has two log streams

`daily_scan.sh` splits output across two logs:

- **launchd stdout log**: captures script's own stdout/stderr — fetch, diff, dedup, gate, merge, render.
- **Run log** (`$RUNLOG`): captures timestamped `log()` entries AND `claude -p` auto-scoring output, which is redirected via `>>"$RUNLOG" 2>&1`.

When verifying whether auto-scoring ran, always check the run log. The launchd stdout log will show no trace of the scoring step because its output is redirected elsewhere.

Both log paths are defined in `daily_scan.sh` and the launchd plist — grep for `RUNLOG` and `StandardOutPath` to find current locations.

## 数据文件路径：以 ~/Projects/job-scan/output/ 为准

daily_scan.sh 的实际输出目录是 `~/Projects/job-scan/output/`，包括：

- `job-scan-results.jsonl`（主数据）
- `job-scan-results.md`
- `job-scan-results.html`

`~/Documents/job/job-scan-output/` 是早期手动使用时的旧路径，已不再由 daily_scan 更新。交互式评分/查询时务必读 `~/Projects/job-scan/output/job-scan-results.jsonl`，否则会漏掉最新扫描结果。

SKILL.md 中的 `PLUGIN_ROOT` = `~/Projects/job-scan/`（即 `scripts/`、`output/`、`profile.md` 等均在此目录下）。

## CERN LD positions have nationality restrictions

CERN Limited Duration (LD) contracts are restricted to citizens of CERN Member States or Associate Member States. Check whether the user's nationality is on the list. If not, cap at ≤15. CERN Fellow/Student programs may not have this restriction — check each posting individually.
