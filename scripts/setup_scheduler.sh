#!/bin/bash
# Install a daily scheduler for job-scan.
# macOS: launchd plist  |  Linux: crontab entry
set -euo pipefail

SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPTS_DIR")"
SCAN_SCRIPT="$SCRIPTS_DIR/daily_scan.sh"

PYTHON="$(command -v python3 || true)"
[ -x "$PYTHON" ] || PYTHON=/usr/bin/python3

# Read fetch_time from preferences.toml (default 07:00)
FETCH_TIME="$("$PYTHON" -c "
import tomllib, os
p = os.path.join('$REPO_DIR', 'preferences.toml')
try:
    with open(p, 'rb') as f: c = tomllib.load(f)
    print(c.get('schedule',{}).get('fetch_time', '07:00'))
except: print('07:00')
" 2>/dev/null)"

HOUR="${FETCH_TIME%%:*}"
MINUTE="${FETCH_TIME##*:}"

LABEL="com.job-scan.daily"

install_launchd() {
    local plist_dir="$HOME/Library/LaunchAgents"
    local plist="$plist_dir/$LABEL.plist"
    local log_stdout="$HOME/Library/Logs/job-scan.launchd.log"
    mkdir -p "$plist_dir" 2>/dev/null || true

    cat > "$plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$LABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>$SCAN_SCRIPT</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>$HOUR</integer>
        <key>Minute</key>
        <integer>$MINUTE</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>$log_stdout</string>
    <key>StandardErrorPath</key>
    <string>$log_stdout</string>
    <key>RunAtLoad</key>
    <false/>
</dict>
</plist>
PLIST

    # Unload if already loaded, then load
    launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
    launchctl bootstrap "gui/$(id -u)" "$plist"

    echo "installed launchd agent: $plist"
    echo "  schedule: daily at $FETCH_TIME"
    echo "  logs: $log_stdout"
    echo "  manual run: launchctl kickstart gui/$(id -u)/$LABEL"
    echo "  uninstall:  launchctl bootout gui/$(id -u)/$LABEL && rm $plist"
}

install_cron() {
    local cron_line="$MINUTE $HOUR * * * /bin/bash $SCAN_SCRIPT >> /tmp/job-scan.log 2>&1"
    # Remove existing entry if present, then add
    ( crontab -l 2>/dev/null | grep -v "$SCAN_SCRIPT" ; echo "$cron_line" ) | crontab -

    echo "installed cron job:"
    echo "  $cron_line"
    echo "  logs: /tmp/job-scan.log"
    echo "  remove: crontab -e and delete the job-scan line"
}

case "$(uname -s)" in
    Darwin)
        install_launchd
        ;;
    Linux)
        install_cron
        ;;
    *)
        echo "unsupported platform: $(uname -s)"
        echo "please manually schedule: bash $SCAN_SCRIPT"
        exit 1
        ;;
esac
