#!/bin/bash
# Install daily job-scan scheduler (macOS launchd / Linux cron).
# Run once after cloning: bash scripts/install_scheduler.sh
set -euo pipefail

SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPTS_DIR")"
PYTHON="$(command -v python3 || true)"
[ -x "$PYTHON" ] || PYTHON=/usr/bin/python3

# Read fetch_time from preferences.toml (default 07:00)
FETCH_TIME="$("$PYTHON" -c "
import tomllib, os
p = os.path.join('$REPO_DIR', 'preferences.toml')
try:
    with open(p, 'rb') as f: c = tomllib.load(f)
    print(c.get('schedule', {}).get('fetch_time', '07:00'))
except: print('07:00')
" 2>/dev/null)"

HOUR="${FETCH_TIME%%:*}"
MINUTE="${FETCH_TIME##*:}"
# Strip leading zeros for launchd (08 → 8)
HOUR=$((10#$HOUR))
MINUTE=$((10#$MINUTE))

LABEL="com.job-scan.daily"

if [[ "$OSTYPE" == darwin* ]]; then
    PLIST="$HOME/Library/LaunchAgents/${LABEL}.plist"

    # Unload old versions if present
    launchctl unload "$PLIST" 2>/dev/null || true
    launchctl unload "$HOME/Library/LaunchAgents/com.job-scan.daily.plist" 2>/dev/null || true

    cat > "$PLIST" << PLISTEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>${REPO_DIR}/scripts/daily_scan.sh</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>${HOUR}</integer>
        <key>Minute</key>
        <integer>${MINUTE}</integer>
    </dict>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
        <key>LANG</key>
        <string>en_US.UTF-8</string>
        <key>LC_ALL</key>
        <string>en_US.UTF-8</string>
    </dict>
    <key>StandardOutPath</key>
    <string>${HOME}/Library/Logs/job-scan.launchd.log</string>
    <key>StandardErrorPath</key>
    <string>${HOME}/Library/Logs/job-scan.launchd.log</string>
</dict>
</plist>
PLISTEOF

    launchctl load "$PLIST"
    echo "Installed: $PLIST"
    echo "Schedule: daily at ${HOUR}:$(printf '%02d' $MINUTE)"
    echo "Logs: ~/Library/Logs/job-scan.launchd.log"

elif [[ "$OSTYPE" == linux* ]]; then
    CRON_CMD="$MINUTE $HOUR * * * /bin/bash ${REPO_DIR}/scripts/daily_scan.sh >> \$HOME/.local/log/job-scan.log 2>&1"
    # Remove old entry, add new
    (crontab -l 2>/dev/null | grep -v 'job-scan' || true; echo "$CRON_CMD") | crontab -
    echo "Installed cron: $CRON_CMD"
else
    echo "Unsupported OS: $OSTYPE" >&2
    exit 1
fi

echo "Done. Verify with: launchctl list | grep job-scan  (macOS) or crontab -l (Linux)"
