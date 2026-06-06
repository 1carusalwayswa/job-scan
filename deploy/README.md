# 部署每日定时（可选）

`daily_scan.sh` 是纯 Python 流水线（fetch→diff→dedup→merge→渲 md/html），零 token、无需 LLM。下面把它挂成每天 07:00 自动跑。

占位符：`{{SKILL_DIR}}`=技能根绝对路径，`{{JOBDIR}}`=台账输出目录（须与运行时 `JOB_SCAN_DIR` 一致），`{{LABEL}}`=launchd 标签如 `com.yourname.job-scan`，`{{LOG_DIR}}`=日志目录。

## macOS（launchd）

> **TCC 坑（重要）**：launchd 的 `StandardOutPath/StandardErrorPath` 若指向 `~/Documents` 会因 TCC 启动即失败（EX_CONFIG 78、无输出）。日志务必放 `~/Library/Logs`。脚本内部对台账用截断写（非 append）以规避 `~/Documents` 下 `>>` 的 EPERM。

```bash
SKILL_DIR=/abs/path/to/job-scan
JOBDIR=$HOME/job-scan
LABEL=com.yourname.job-scan
LOG_DIR=$HOME/Library/Logs
PLIST=$HOME/Library/LaunchAgents/$LABEL.plist

mkdir -p "$LOG_DIR" "$(dirname "$PLIST")"
sed -e "s#{{SKILL_DIR}}#$SKILL_DIR#g" -e "s#{{JOBDIR}}#$JOBDIR#g" \
    -e "s#{{LABEL}}#$LABEL#g" -e "s#{{LOG_DIR}}#$LOG_DIR#g" \
    deploy/launchd.plist.example > "$PLIST"

launchctl bootstrap gui/$(id -u) "$PLIST"
launchctl kickstart -k gui/$(id -u)/$LABEL   # 立刻试跑一次
```
卸载/改时间：`launchctl bootout gui/$(id -u)/$LABEL`，编辑 plist 后再 `bootstrap`。

## Linux（systemd user timer）

```bash
SKILL_DIR=/abs/path/to/job-scan
JOBDIR=$HOME/job-scan
UNIT=$HOME/.config/systemd/user
mkdir -p "$UNIT"
sed -e "s#{{SKILL_DIR}}#$SKILL_DIR#g" -e "s#{{JOBDIR}}#$JOBDIR#g" \
    deploy/systemd/job-scan.service.example > "$UNIT/job-scan.service"
cp deploy/systemd/job-scan.timer.example "$UNIT/job-scan.timer"

systemctl --user daemon-reload
systemctl --user enable --now job-scan.timer
systemctl --user start job-scan.service   # 立刻试跑一次
journalctl --user -u job-scan.service     # 看日志
```

## 验证

跑一次后检查 `$JOBDIR/job-scan-results.jsonl` 是否增长、`job-scan-results.html` 是否更新、日志是否有 `OK 今日新增 …`。
