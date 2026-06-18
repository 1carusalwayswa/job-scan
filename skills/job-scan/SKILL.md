---
name: job-scan
description: 瑞典 IT 岗位自动扫描 + 精筛工具。自动抓取 JobTech API + 目标公司 career page，按用户 profile 打分，支持 review server 手动查看。首次使用请跑 `/job-scan setup`。
---

# job-scan

瑞典 IT 岗位自动扫描 + LLM 精筛。

- 事实源：`output/job-scan-results.jsonl`（`link` 主键）
- 可读清单：`output/job-scan-results.md` + `output/job-scan-results.html`
- 用户配置：`profile.md`、`preferences.toml`、`search_config.json`、`target_companies.json`
- 校准数据：`calibration.jsonl`

所有路径相对于插件根目录（`PLUGIN_ROOT`，即包含 `.claude-plugin/` 的目录）。

## 路径约定

```
PLUGIN_ROOT = 插件根目录（含 .claude-plugin/、scripts/、assets/）
SCRIPTS     = PLUGIN_ROOT/scripts
RESULTS     = PLUGIN_ROOT/output/job-scan-results.jsonl
MD          = PLUGIN_ROOT/output/job-scan-results.md
HTML        = PLUGIN_ROOT/output/job-scan-results.html
TRACKER     = PLUGIN_ROOT/output/applications-tracker.md
PROFILE     = PLUGIN_ROOT/profile.md
PREFS       = PLUGIN_ROOT/preferences.toml
CONFIG      = PLUGIN_ROOT/search_config.json
COMPANIES   = PLUGIN_ROOT/target_companies.json
CALIBRATION = PLUGIN_ROOT/calibration.jsonl
TODAY       = 今天日期，ISO YYYY-MM-DD
```

## 入口分流

| 用户说的 | 跑什么 |
|---|---|
| `/job-scan setup` | Setup 流程 |
| "精筛新岗 / 评分 / 看今天新增" | Phase 2 backlog 模式 |
| "立刻全新扫描" | Phase 1 + Phase 2 全新模式 |
| `/job-scan score-backlog` | Phase 2 backlog（unattended 模式，由 daily_scan.sh 调用） |
| "确认/忽略/已看 第 N 个" | 状态变更 |
| "投第 N 个 / 转 apply" | Phase 5 转 apply |

## Setup 流程（首次使用）

检查 `PLUGIN_ROOT/profile.md` 是否存在。如果不存在，进入 setup：

1. **采集 profile**：交互式引导用户描述背景，生成 `profile.md`。需要涵盖：
   - 基本信息（所在城市、学历、工作年限）
   - 核心技术栈（experienced level）
   - 了解但非专长的技术（working knowledge）
   - 工作经历（每段：公司、职位、时间、关键成果）
   - 教育亮点（论文、高分课程）
   - 差异化信号（竞赛、开源、演讲等）
   - 求职方向（目标角色类型、级别偏好、地点偏好）

   参考 `templates/profile.example.md` 的结构。

2. **生成 preferences.toml**：根据用户回答生成。需要问：
   - 瑞典语水平（fluent/basic/none）→ `language.swedish`
   - 国籍/工作许可状况 → `eligibility.citizenship`、`eligibility.exclude_security_cleared`
   - 每日扫描时间偏好 → `schedule.fetch_time`
   - 是否开启自动打分 → `schedule.auto_score`

   参考 `templates/preferences.example.toml` 的结构。

3. **生成 search_config.json**：根据 profile 中的求职方向，帮用户定义搜索赛道。格式：
   ```json
   {
     "occupation_field": "apaJ_2ja_LuF",
     "municipality_ids": [],
     "limit": 100,
     "lanes": [
       {"name": "赛道名", "keywords": ["keyword1", "keyword2"]},
       ...
     ],
     "thresholds": {"赛道名": 65, ...}
   }
   ```
   `occupation_field` 固定为 IT 领域 ID `apaJ_2ja_LuF`（JobTech taxonomy）。
   每个 lane 对应用户的一个求职方向，keywords 用于 JobTech API 搜索。

4. **生成 target_companies.json**（可选）：用户感兴趣的公司列表，格式：
   ```json
   {"companies": [{"name": "...", "careers_url": "...", "note": "..."}]}
   ```
   用户可以跳过此步，后续手动添加。

5. **安装调度器**：
   ```bash
   bash PLUGIN_ROOT/scripts/setup_scheduler.sh
   ```

6. Setup 完成后提示用户：
   - "配置已生成。每日 {fetch_time} 自动抓取新岗位。"
   - "现在可以跑 `/job-scan` 开始第一次扫描和评分。"

## Phase 1 — 拉取

1. JobTech 主源：
   ```bash
   python3 SCRIPTS/fetch_jobtech.py --config CONFIG --out /tmp/job-scan-raw.jsonl
   ```
2. career 补源：读 `COMPANIES`（target_companies.json），对每个 `careers_url` 用 **WebFetch** 抓公开页，解析岗位追加到 `/tmp/job-scan-raw.jsonl`。格式：
   - `link`：岗位详情页绝对 URL（稳定唯一）
   - `company`/`title`/`location`/`summary`，`source` = `"career"`
   - 某公司页抓取失败 → 跳过并记录，不中断。

## Phase 2 — 精筛打分

**找出待打分岗位，二选一：**

- **(A) backlog 模式（默认）**——每日 launchd/cron 已 fetch+去重+并入事实源，这里只捞未评分的：
  ```bash
  python3 SCRIPTS/results_io.py --mode pending --results RESULTS --out /tmp/job-scan-flagged.jsonl
  ```

- **(B) 全新模式**——先跑 Phase 1，再 diff+去重：
  ```bash
  python3 SCRIPTS/results_io.py --mode diff --include-pending \
    --raw /tmp/job-scan-raw.jsonl --results RESULTS --out /tmp/job-scan-to-score.jsonl
  python3 SCRIPTS/dedup.py --in /tmp/job-scan-to-score.jsonl --tracker TRACKER --out /tmp/job-scan-flagged.jsonl
  ```

**硬门槛（确定性，先于 LLM）**——根据 `preferences.toml` 的 gates 开关决定是否跑：

```bash
python3 SCRIPTS/lang_gate.py --in /tmp/job-scan-flagged.jsonl --out /tmp/job-scan-flagged.jsonl
python3 SCRIPTS/citizenship_gate.py --in /tmp/job-scan-flagged.jsonl --out /tmp/job-scan-flagged.jsonl
python3 SCRIPTS/pre_gate.py --in /tmp/job-scan-flagged.jsonl --out /tmp/job-scan-flagged.jsonl
```

**LLM 打分**：读 `PROFILE`，对 `/tmp/job-scan-flagged.jsonl` 中 **score 为空** 的岗位打分，写出 `/tmp/job-scan-scored.jsonl`。

### 评分方法论

**打分流程（对每个待评岗位）：**

1. **读 profile.md**，推断：
   - 用户的核心栈及深度分层（experienced vs working knowledge）
   - 工业经验年限和级别定位
   - 差异化信号（竞赛、论文、特殊项目等）
   - 各赛道的匹配强度

2. **读 calibration.jsonl**（如存在），作为 few-shot 参考：每条含一个岗位的 link、原始打分、用户反馈、修正后分数。

3. **门控→封顶→分档**：

   **缺口闸门（命中即封顶，取最低）：**
   | 缺口 | 封顶 |
   |---|---|
   | JD 要 senior/lead/principal/staff 级别，或经验年限远超 profile | **≤50** |
   | 缺 JD 的 must-have 核心栈（profile 无对应深度） | **≤55** |
   | 中介泛投 / 咨询中介海量贴岗 | **≤58** |

   **证据层级校验**：「用过/跑在其上」≠「实现/调试过」。JD 要求某栈的实现/集成排障深度时，profile 中应用层使用经验不算覆盖。

   **分档锚点（封顶后对照）：**
   - **80–90**：级别契合 + 核心栈覆盖 + 正中主力赛道 + 有差异化信号。四缺一即 <80。
   - **70–79**：在赛道 + 核心栈覆盖较好，级别略偏或差异化一般。
   - **60–69**：在赛道但有实质缺口。
   - **<60**：多处缺口、中介泛投、或核心栈基本不符。

4. **输出字段契约：**
   - `score`：整数 0–100
   - `lane`：必须是 `search_config.json` 的 `lanes[].name` 之一，或空串 `""`。不可自创变体。
   - `reason`：一句话，**必须同时写命中与缺口**。

5. **JD 语言信号**：JD 正文整篇用瑞典语写（即便没命中 lang_gate 的硬短语）→ 不排除但降 ~10 分，reason 注明。

6. **maybe_applied 信号**：`maybe_applied=true` 的岗位适当降分并在 reason 注明。

### Unattended 模式（score-backlog）

当由 `claude -p "/job-scan score-backlog"` 调用时：

1. 走 backlog 模式 (A)，拿 pending 岗位
2. 跑硬门槛 + LLM 打分
3. merge + 渲染
4. 高匹配岗直接标"待确认"
5. **不启动 review server，不等待用户确认，不输出交互式摘要**
6. 完成后静默退出

## Phase 3+4 — 合并 + 渲染

```bash
python3 SCRIPTS/results_io.py --mode merge \
  --scored /tmp/job-scan-scored.jsonl \
  --seen /tmp/job-scan-raw.jsonl \
  --results RESULTS --md MD --today TODAY
```

backlog 模式省去 `--seen`。合并按 `link` 主键：新岗插入标「新」；已有岗保留用户状态、刷新 `last_seen`。

**渲染：**

```bash
python3 SCRIPTS/render_html.py
```

**交互式会话（非 unattended）：后台启动 review server：**

```bash
python3 SCRIPTS/review_server.py   # 自动开 http://localhost:8765
```

然后列出本次新增的高匹配（score ≥ 各赛道 thresholds）摘要 + 链接 + 理由，等用户确认。把高匹配标"待确认"：

```bash
python3 SCRIPTS/results_io.py --mode status \
  --results RESULTS --md MD --link "<链接>" --status "待确认"
```

## 状态变更

用户说"确认/忽略/已看 第 N 个"时映射到 link：

```bash
python3 SCRIPTS/results_io.py --mode status \
  --results RESULTS --md MD --link "<link>" --status "<待确认|已看|已忽略>"
```

渲染后重新生成 HTML：`python3 SCRIPTS/render_html.py`

## Phase 5 — 转 apply

```bash
python3 SCRIPTS/prep_apply.py --list [--min-score N]
python3 SCRIPTS/prep_apply.py --prep "<link1>" "<link2>" ...
```

投递后置状态：

```bash
python3 SCRIPTS/results_io.py --mode status \
  --results RESULTS --md MD --link "<link>" --status "已转apply"
```

## 反馈回路（校准）

用户对某个打分说"这个给高了/低了"时，追加到 `CALIBRATION`：

```json
{"link": "...", "original_score": 78, "corrected_score": 55, "feedback": "核心栈不匹配，应触发 ≤55 封顶", "date": "2026-06-18"}
```

下次 LLM 打分时读 `calibration.jsonl` 作为 few-shot 参考，持续提高打分精度。

## 定时（自动配置）

`/job-scan setup` 会调用 `scripts/setup_scheduler.sh` 自动安装：
- macOS: launchd plist (`~/Library/LaunchAgents/com.job-scan.daily.plist`)
- Linux: crontab entry

每日按 `preferences.toml` 的 `schedule.fetch_time` 执行 `scripts/daily_scan.sh`。
若 `schedule.auto_score = true`，fetch 后自动调 `claude -p` 打分 pending 岗位。
打分失败不影响 fetch 结果，pending 积累到下次。
