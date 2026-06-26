#!/bin/bash
# Daily unattended job scan: fetch → diff → dedup → gates → merge → render.
# If auto_score is enabled in preferences.toml and there are pending jobs,
# invokes claude -p to score them.
set -euo pipefail
export LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8

SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPTS_DIR")"

PYTHON="$(command -v python3 || true)"
[ -x "$PYTHON" ] || PYTHON=/usr/bin/python3

CONFIG="$REPO_DIR/search_config.json"
RESULTS="$REPO_DIR/output/job-scan-results.jsonl"
MD="$REPO_DIR/output/job-scan-results.md"
TRACKER="$REPO_DIR/output/applications-tracker.md"
mkdir -p "$REPO_DIR/output" 2>/dev/null || true

LOGDIR="$HOME/Library/Logs"
[ -d "$LOGDIR" ] || LOGDIR="/tmp"
RUNLOG="$LOGDIR/job-scan.log"

RAW=/tmp/job-scan-raw.jsonl
TOSCORE=/tmp/job-scan-to-score.jsonl
FLAGGED=/tmp/job-scan-flagged.jsonl
PENDING=/tmp/job-scan-pending.jsonl
TODAY="$(date +%Y-%m-%d)"
STAMP="$(date '+%Y-%m-%d %H:%M:%S')"

log() { printf '%s %s\n' "$STAMP" "$1" >> "$RUNLOG" 2>/dev/null || true; }

notify() {
    if command -v osascript >/dev/null 2>&1; then
        osascript -e "display notification \"$1\" with title \"job-scan\"" 2>/dev/null || true
    elif command -v notify-send >/dev/null 2>&1; then
        notify-send "job-scan" "$1" 2>/dev/null || true
    fi
}

trap 'log "ERROR scan failed"; notify "job-scan daily scan failed — see $RUNLOG"' ERR

# Helper: read a value from preferences.toml (fallback on error)
read_pref() {
    local key="$1" default="$2"
    "$PYTHON" -c "
import tomllib, os, functools, operator
p = os.path.join('$REPO_DIR', 'preferences.toml')
try:
    with open(p, 'rb') as f: c = tomllib.load(f)
    keys = '$key'.split('.')
    val = functools.reduce(operator.getitem, keys, c)
    print(str(val).lower() if isinstance(val, bool) else val)
except: print('$default')
" 2>/dev/null
}

# --- Phase 1: Fetch ---
"$PYTHON" "$SCRIPTS_DIR/fetch_jobtech.py" --config "$CONFIG" --out "$RAW"

# Career pages (append to RAW; failures are non-fatal but reported)
CAREERS_TMP=/tmp/job-scan-careers.jsonl
COMPANIES="$REPO_DIR/target_companies.json"
if [ -f "$COMPANIES" ]; then
    if "$PYTHON" "$SCRIPTS_DIR/fetch_careers.py" --config "$COMPANIES" --out "$CAREERS_TMP" 2>>"$RUNLOG"; then
        cat "$CAREERS_TMP" >> "$RAW"
        log "career pages OK"
    else
        # Partial results are still written on failure (some companies may have succeeded)
        if [ -s "$CAREERS_TMP" ]; then
            cat "$CAREERS_TMP" >> "$RAW"
        fi
        log "career pages: some companies failed (see log above)"
        notify "job-scan: some career page fetches failed — check $RUNLOG"
    fi
fi

# --- Phase 2: Diff + dedup + gates ---
"$PYTHON" "$SCRIPTS_DIR/results_io.py" --mode diff --raw "$RAW" --results "$RESULTS" --out "$TOSCORE"
"$PYTHON" "$SCRIPTS_DIR/dedup.py" --in "$TOSCORE" --tracker "$TRACKER" --out "$FLAGGED"

[ "$(read_pref gates.lang_gate true)" = "true" ] && \
    "$PYTHON" "$SCRIPTS_DIR/lang_gate.py" --in "$FLAGGED" --out "$FLAGGED" 2>>"$RUNLOG"
[ "$(read_pref gates.citizenship_gate true)" = "true" ] && \
    "$PYTHON" "$SCRIPTS_DIR/citizenship_gate.py" --in "$FLAGGED" --out "$FLAGGED" 2>>"$RUNLOG"
[ "$(read_pref gates.staffing_gate true)" = "true" ] && \
    "$PYTHON" "$SCRIPTS_DIR/pre_gate.py" --in "$FLAGGED" --out "$FLAGGED" 2>>"$RUNLOG"
"$PYTHON" "$SCRIPTS_DIR/profile_gap_gate.py" --in "$FLAGGED" --out "$FLAGGED" 2>>"$RUNLOG"

# --- Phase 3: Merge + render ---
"$PYTHON" "$SCRIPTS_DIR/results_io.py" --mode merge --scored "$FLAGGED" --seen "$RAW" \
  --results "$RESULTS" --md "$MD" --today "$TODAY"
"$PYTHON" "$SCRIPTS_DIR/render_html.py"

NEW_COUNT="$("$PYTHON" -c "import sys;print(sum(1 for l in open(sys.argv[1],encoding='utf-8') if l.strip()))" "$TOSCORE")"
"$PYTHON" "$SCRIPTS_DIR/results_io.py" --mode pending --results "$RESULTS" --out "$PENDING" >/dev/null
PENDING_COUNT="$("$PYTHON" -c "import sys;print(sum(1 for l in open(sys.argv[1],encoding='utf-8') if l.strip()))" "$PENDING")"

log "OK new=$NEW_COUNT pending=$PENDING_COUNT"

# --- Phase 4: Auto-score with claude -p (if enabled and pending > 0) ---
AUTO_SCORE="$(read_pref schedule.auto_score true)"
MAX_BUDGET="$(read_pref schedule.max_budget_usd 1.0)"

if [ "$AUTO_SCORE" = "true" ] && [ "$PENDING_COUNT" -gt 0 ] && command -v claude >/dev/null 2>&1; then
    log "auto-scoring $PENDING_COUNT pending jobs (budget: \$$MAX_BUDGET)"
    SCORE_PROMPT="$(cat <<PROMPT
/job-scan score-backlog

IMPORTANT — all paths are pre-resolved and verified by the shell:
- PLUGIN_ROOT=$REPO_DIR
- PROFILE=$REPO_DIR/profile.md
- RESULTS=$RESULTS
- PENDING=$PENDING ($PENDING_COUNT jobs)
- CALIBRATION=$REPO_DIR/calibration.jsonl
- CONFIG=$CONFIG
- SCRIPTS=$SCRIPTS_DIR

Do NOT check whether profile.md or scripts/ exist — they do. Proceed directly to scoring.
PROMPT
)"
    if claude -p "$SCORE_PROMPT" \
        --plugin-dir "$REPO_DIR" \
        --add-dir "$REPO_DIR" \
        --allowedTools "Bash,Read,Write,Skill" \
        --max-budget-usd "$MAX_BUDGET" \
        >>"$RUNLOG" 2>&1; then
        log "auto-scoring completed"
        "$PYTHON" "$SCRIPTS_DIR/results_io.py" --mode pending --results "$RESULTS" --out "$PENDING" >/dev/null
        PENDING_COUNT="$("$PYTHON" -c "import sys;print(sum(1 for l in open(sys.argv[1],encoding='utf-8') if l.strip()))" "$PENDING")"
    else
        log "auto-scoring FAILED (non-fatal), $PENDING_COUNT still pending"
    fi
fi

notify "new=$NEW_COUNT pending=$PENDING_COUNT"
