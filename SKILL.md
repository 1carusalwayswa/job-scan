---
name: job-scan
description: 发现并精筛瑞典 IT/软件岗位。当用户想"找工作 / 看有什么新岗 / 跑一次岗位扫描 / 刷新候选清单 / 每日岗位扫描"时使用。从 JobTech API + 公司 career 公开页拉取岗位，按用户画像与自定义赛道打分，按稳定链接去重，维护 job-scan-results.jsonl 事实源并渲染 md/html 清单，高匹配标「待确认」等用户确认后接投递。
---

# job-scan

发现 + 精筛瑞典 IT 岗位。机器事实源 `job-scan-results.jsonl` 按 `link` 主键存状态/分数/日期；`.md`/`.html` 仅从它渲染。脚本在技能根 `scripts/`，配置在 `assets/`。

> **首次使用先看 README.md 完成安装**（复制 `*.example.*` 为真实配置、填画像）。真实 `profile.md`/`search_config.json`/`target_companies.json` 已被 .gitignore。

**范围：** 数据源是瑞典 JobTech（Arbetsförmedlingen），仅覆盖瑞典岗位。语言门槛由 `search_config.json` 的 `local_language`（默认 `Swedish`）驱动。

**每日自动扫描**（可选，见 README 调度）用纯 Python 把新岗位以 `status=新`、无 `score` 累积进事实源（零 token，不调用 LLM 打分）。所以日常最常见的是对这批 **backlog** 精筛：捞未评分岗位 → LLM 打分。

## 路径约定

```
SKILL_DIR = 本技能根目录（含 scripts/、assets/）
JOBDIR    = 台账与输出目录（默认 ~/job-scan，可用环境变量 JOB_SCAN_DIR 覆盖；与 daily_scan.sh 一致）
RESULTS   = $JOBDIR/job-scan-results.jsonl
MD        = $JOBDIR/job-scan-results.md
HTML      = $JOBDIR/job-scan-results.html
TRACKER   = $JOBDIR/applications-tracker.md
PROFILE   = $SKILL_DIR/assets/profile.md
CONFIG    = $SKILL_DIR/assets/search_config.json
TODAY     = 今天日期，ISO 格式 YYYY-MM-DD
```

## 何时跑哪段

- 用户说"精筛新岗 / 看今天新增 / 评分" → **Phase 2 (A) backlog 模式**（拿 `pending`）→ 打分 → merge → 列「待确认」。无需重新 fetch。
- 用户要"立刻全新扫描/刷新" → Phase 1 + **Phase 2 (B) 全新模式**（fetch→diff）。
- 用户说"确认第 N 个 / 忽略第 N 个 / 第 N 个已看" → 「状态变更」。
- 用户说"投第 N 个" → 「转投递」。

## Phase 1 — 拉取

1. JobTech 主源：
   ```bash
   python3 "$SKILL_DIR/scripts/fetch_jobtech.py" --config "$CONFIG" --out /tmp/job-scan-raw.jsonl
   ```
2. career 补源：读 `$SKILL_DIR/assets/target_companies.json`，对每个 `careers_url` 用 **WebFetch** 抓公开页解析岗位，构造统一字典**追加**到 `/tmp/job-scan-raw.jsonl`（每行一个 JSON，UTF-8，`ensure_ascii=false`）：
   - `link`：岗位详情页绝对 URL（须稳定唯一）。
   - `company`/`title`/`location`/`summary`，`source="career"`。
   - 某公司页抓取失败 → 跳过并记一句，不中断其他源。

## Phase 2 — 精筛打分

**找出待打分岗位，二选一：**

- **(A) backlog 模式（默认）**——捞出事实源里未评分的：
  ```bash
  python3 "$SKILL_DIR/scripts/results_io.py" --mode pending --results "$RESULTS" --out /tmp/job-scan-flagged.jsonl
  ```
- **(B) 全新模式（先跑 Phase 1）**——diff 出新岗再补软标记：
  ```bash
  python3 "$SKILL_DIR/scripts/results_io.py" --mode diff --raw /tmp/job-scan-raw.jsonl --results "$RESULTS" --out /tmp/job-scan-to-score.jsonl
  python3 "$SKILL_DIR/scripts/dedup.py" --in /tmp/job-scan-to-score.jsonl --tracker "$TRACKER" --out /tmp/job-scan-flagged.jsonl
  ```

3. 读 `PROFILE` 与 `CONFIG`，对 `/tmp/job-scan-flagged.jsonl` 每个岗位读 `summary` 打分，写出 `/tmp/job-scan-scored.jsonl`（在每行原 JSON 上补 `score`/`lane`/`reason` 三字段，保留所有原字段）。

   **语言门槛（打分前先过这一刀）：** 设 `L = config.local_language`（默认 Swedish）。若用户画像声明**不具备 `L` 的工作能力**，且 JD 明确**要求精通/流利 `L`**、或**以 `L` 为日常工作沟通语言** → 直接排除（打极低分、`reason` 注明「{L} 硬要求」、归类标 `已忽略`），无论技能多匹配。
   - **算硬要求（排除）**：JD 写明 `fluent {L}` / `{L} verbally and in writing` / 正文整体用 `L` 写且要求母语级。
   - **不算（保留，别误杀）**：`{L} University/company`（机构名）、`{L} collective agreements`（雇佣条款）、`apply in {L} or English`（投递语言可选英文）、只「is a plus / meriterande」的语言加分项。

   **软信号：JD 正文整篇用 `L` 写**（即便没写明要求）→ **不排除，但降优先级**（扣 ~10 分、`reason` 注明「JD 为 {L}，隐含语言倾向」）。判定靠 `L` 高频功能词或重音字符密度占主导。

   **赛道与打分：** 赛道来自 `CONFIG.lanes`，阈值来自 `CONFIG.thresholds`。结合用户 `PROFILE` 里写的各赛道权重/适配说明打分（0–100）：技能匹配 + 赛道权重 + 级别契合（按画像目标级别，避开明显超纲的资深岗）+ 差异化。`reason` 用一句话说清"为什么这分、归哪条赛道"。`maybe_applied=true` 的岗位适当降分并在 reason 注明。

## Phase 3+4 — 去重合并 + 渲染清单

```bash
python3 "$SKILL_DIR/scripts/results_io.py" --mode merge \
  --scored /tmp/job-scan-scored.jsonl --seen /tmp/job-scan-raw.jsonl \
  --results "$RESULTS" --md "$MD" --today <TODAY>
```
（backlog 模式没有新 fetch，**省去 `--seen`**——这些岗已在事实源里，merge 会按 `link` 更新 `score`/`lane`/`reason` 并保留状态。）

合并按 `link` 主键：新岗插入标「新」；已有岗保留用户状态（不降级回「新」）、刷新 `last_seen`。然后从事实源渲染 `.md`。

**渲染后必跑：生成人类可读 HTML**（`.md` 表格行多了对人难读）。每次写完 `.md`（merge 或状态变更后）紧接着重生成 HTML：
```bash
python3 "$SKILL_DIR/scripts/render_html.py" --results "$RESULTS" --out "$HTML"
```
（若画像有所在地，可加 `--home "<城市>"` 给该地点加 📍 标记与就地筛选按钮。）

完成后：用系统打开命令打开 `$HTML`（给人看的版本），在对话里列出本次**新增高匹配**（`score ≥` 各赛道 `thresholds`）摘要 + 链接 + 一句理由，等用户确认。**不自动生成投递材料、不自动改成「待确认」以外的状态**。把这些高匹配逐个跑「状态变更」设为 `待确认`。

## 状态变更（对话驱动）

用户说"确认/忽略/已看第 N 个"时，把展示序号映射到该岗 `link`，跑：
```bash
python3 "$SKILL_DIR/scripts/results_io.py" --mode status \
  --results "$RESULTS" --md "$MD" --link "<该岗 link>" --status "<待确认|已看|已忽略>"
```
然后重渲 HTML（同上）。状态值：`待确认`（高匹配待拍板）、`已看`、`已忽略`。**绝不手改 .md/.html**——只通过命令改事实源再自动重渲染。

## 转投递（用户确认要投某岗）

1. 用该岗 `title`/`company`/`summary`/`link` 生成投递材料（若装了投递类技能则调用它；否则手工）。
2. 置状态 `已转apply`：
   ```bash
   python3 "$SKILL_DIR/scripts/results_io.py" --mode status \
     --results "$RESULTS" --md "$MD" --link "<该岗 link>" --status "已转apply"
   ```
3. 把岗位 `link` 补写进 `$TRACKER` 对应行，使后续去重可精确按链接匹配。

## 定时（可选）

每日自动扫描由 `scripts/daily_scan.sh`（纯 Python，零 token）跑 fetch+去重+把新岗以未评分并入事实源 + 渲 md/html。部署方式见 README 与 `deploy/`（macOS launchd / Linux systemd）。脚本不含 career WebFetch 与 LLM 打分——那两步需工具/判断力，留给交互式会话。
