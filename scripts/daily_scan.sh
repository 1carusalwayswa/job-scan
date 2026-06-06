#!/bin/bash
# 每日无人值守岗位扫描（纯 Python，零 token / 零 API）。
# 流水线：fetch → diff → dedup 软标记 → merge（未评分并入台账）→ 渲 md + html。
# LLM 精筛留给交互式会话（用户说「精筛今天的新岗位」时跑 results_io pending）。
set -euo pipefail
export LANG=${LANG:-en_US.UTF-8} LC_ALL=${LC_ALL:-en_US.UTF-8}

# 自定位：脚本所在目录即技能根/scripts
SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(dirname "$SCRIPTS_DIR")"

PYTHON="$(command -v python3 || true)"
[ -x "$PYTHON" ] || PYTHON=/usr/bin/python3

# 可被环境变量覆盖；默认放用户家目录下 job-scan/
JOBDIR="${JOB_SCAN_DIR:-$HOME/job-scan}"
mkdir -p "$JOBDIR" 2>/dev/null || true

CONFIG="$SKILL_DIR/assets/search_config.json"
RESULTS="$JOBDIR/job-scan-results.jsonl"
MD="$JOBDIR/job-scan-results.md"
HTML="$JOBDIR/job-scan-results.html"
TRACKER="$JOBDIR/applications-tracker.md"

# 可选：给某地点加 📍（环境变量，无则不加）
HOME_LOC="${JOB_SCAN_HOME:-}"

# 日志目录：macOS 因 TCC 必须避开 ~/Documents，用 ~/Library/Logs；Linux 用 XDG_STATE_HOME
case "$(uname -s)" in
  Darwin) LOGDIR="$HOME/Library/Logs" ;;
  *)      LOGDIR="${XDG_STATE_HOME:-$HOME/.local/state}/job-scan" ;;
esac
mkdir -p "$LOGDIR" 2>/dev/null || true
RUNLOG="$LOGDIR/job-scan.log"

RAW=/tmp/job-scan-raw.jsonl
TOSCORE=/tmp/job-scan-to-score.jsonl
FLAGGED=/tmp/job-scan-flagged.jsonl
PENDING=/tmp/job-scan-pending.jsonl
TODAY="$(date +%Y-%m-%d)"
STAMP="$(date '+%Y-%m-%d %H:%M:%S')"

log() { printf '%s %s\n' "$STAMP" "$1" >> "$RUNLOG" 2>/dev/null || true; }

# 跨平台桌面通知：macOS osascript → Linux notify-send → 都没有则只记日志
notify() {
  local msg="$1"
  if command -v osascript >/dev/null 2>&1; then
    osascript -e "display notification \"$msg\" with title \"job-scan\"" 2>/dev/null || true
  elif command -v notify-send >/dev/null 2>&1; then
    notify-send "job-scan" "$msg" 2>/dev/null || true
  fi
}

trap 'log "ERROR 扫描失败（见 $RUNLOG）"; notify "今日扫描失败，见日志"' ERR

"$PYTHON" "$SCRIPTS_DIR/fetch_jobtech.py" --config "$CONFIG" --out "$RAW"
"$PYTHON" "$SCRIPTS_DIR/results_io.py" --mode diff --raw "$RAW" --results "$RESULTS" --out "$TOSCORE"
"$PYTHON" "$SCRIPTS_DIR/dedup.py" --in "$TOSCORE" --tracker "$TRACKER" --out "$FLAGGED"
"$PYTHON" "$SCRIPTS_DIR/results_io.py" --mode merge --scored "$FLAGGED" --seen "$RAW" \
  --results "$RESULTS" --md "$MD" --today "$TODAY"

# 渲染人类可读 HTML（带 home 标记若设置）
if [ -n "$HOME_LOC" ]; then
  "$PYTHON" "$SCRIPTS_DIR/render_html.py" --results "$RESULTS" --out "$HTML" --home "$HOME_LOC" >/dev/null
else
  "$PYTHON" "$SCRIPTS_DIR/render_html.py" --results "$RESULTS" --out "$HTML" >/dev/null
fi

NEW_COUNT="$("$PYTHON" -c "import sys;print(sum(1 for l in open(sys.argv[1],encoding='utf-8') if l.strip()))" "$TOSCORE")"
"$PYTHON" "$SCRIPTS_DIR/results_io.py" --mode pending --results "$RESULTS" --out "$PENDING" >/dev/null
PENDING_COUNT="$("$PYTHON" -c "import sys;print(sum(1 for l in open(sys.argv[1],encoding='utf-8') if l.strip()))" "$PENDING")"

log "OK 今日新增 ${NEW_COUNT}，累计待精筛 ${PENDING_COUNT}"
notify "今日新增 ${NEW_COUNT}，累计待精筛 ${PENDING_COUNT}"
