# job-scan — 瑞典 IT 岗位发现 + 精筛 Claude Code 技能

发现并精筛瑞典 IT/软件岗位：从 JobTech（Arbetsförmedlingen）API + 公司 career 公开页拉取，按你的画像与自定义赛道用 LLM 打分，按稳定链接去重，维护一个 jsonl 事实源并渲染 md/html 清单，高匹配标「待确认」等你拍板。

> **本文件面向部署者/部署 agent**（怎么从 clone 到跑起来）。技能本身的用法在 `SKILL.md`。

## 范围 / 限制
- 数据源是**瑞典 JobTech**，只覆盖瑞典岗位；`occupation_field` 是瑞典职业分类码。
- 这是一个可改造的**模板**：语言门槛、赛道、画像都来自配置；改 `local_language`/`lanes` 可适配你的情况，但数据源仍是瑞典。
- LLM 打分在交互式会话里进行（用你的 Claude 订阅/额度）；每日 `daily_scan.sh` 只做零 token 的确定性流水线。

## 依赖
- Python 3（仅标准库，无第三方包）。
- Claude Code（作为技能加载）。
- 网络可达 `jobsearch.api.jobtechdev.se`（无需 API key）。

## 安装

> 标注 **[agent 自动]** 的步骤部署 agent 可直接做；**[问用户]** 的须先向用户取信息。

1. **[agent 自动]** 把本仓放进 Claude Code 技能目录（或在仓内直接当技能用）。确认 `SKILL.md` 能被发现。
2. **[agent 自动]** 建配置真实文件：
   ```bash
   cp assets/profile.example.md         assets/profile.md
   cp assets/search_config.example.json assets/search_config.json
   cp assets/target_companies.example.json assets/target_companies.json
   ```
   （这三个真实文件已在 `.gitignore`，不会被提交。）
3. **[问用户]** 填 `assets/profile.md`：目标级别、所在地、**当地语言能力**（决定语言门槛是否排除）、核心技能、各赛道权重。
4. **[问用户]** 改 `assets/search_config.json`：赛道 `lanes` 与阈值 `thresholds`、`local_language`（默认 Swedish）、可选 `municipality_ids`（城市码，留空=全国）。
5. **[问用户，可选]** 改 `assets/target_companies.json` 为你想盯的公司 career 页。
6. **[agent 可做，路径需用户确认]** 部署每日定时（可选）：见 `deploy/README.md`（macOS launchd / Linux systemd）。

## 冒烟测试

```bash
# 主源拉取（写 /tmp/raw.jsonl）
python3 scripts/fetch_jobtech.py --config assets/search_config.json --out /tmp/raw.jsonl
# 并入事实源并渲染（首次 RESULTS 不存在会自动创建）
JOBDIR=${JOB_SCAN_DIR:-$HOME/job-scan}; mkdir -p "$JOBDIR"
python3 scripts/results_io.py --mode merge --scored /dev/null --seen /tmp/raw.jsonl \
  --results "$JOBDIR/job-scan-results.jsonl" --md "$JOBDIR/job-scan-results.md" --today "$(date +%F)"
python3 scripts/render_html.py --results "$JOBDIR/job-scan-results.jsonl" --out "$JOBDIR/job-scan-results.html"
# 跑测试
python3 -m pytest tests/ -v
```
预期：`$JOBDIR` 下生成 jsonl/md/html，pytest 全绿。

## 隐私守卫
- 真实 `profile.md`/`search_config.json`/`target_companies.json`、台账输出、调度实例文件都已 `.gitignore`——**别强行 `git add` 它们**。
- **别把含你台账/画像的副本推到公开仓**。要发布改动只发引擎与 `*.example.*`。
- 投递历史 `applications-tracker.md`（若用）含个人数据，已忽略。
