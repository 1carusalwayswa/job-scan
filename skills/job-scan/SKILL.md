---
name: job-scan
description: Automated IT job scanning + scoring tool for Sweden. Fetches from JobTech API + company career pages, scores against user profile, supports review server for manual review. First-time users run `/job-scan setup`.
---

# job-scan

Automated IT job scanning + LLM-powered scoring for Sweden.

- Fact source: `output/job-scan-results.jsonl` (primary key: `link`)
- Human-readable: `output/job-scan-results.md` + `output/job-scan-results.html`
- User config: `profile.md`, `preferences.toml`, `search_config.json`, `target_companies.json`
- Calibration data: `calibration.jsonl`

All paths are relative to the plugin root directory (`PLUGIN_ROOT`).  
This SKILL.md is located at `PLUGIN_ROOT/skills/job-scan/`, so `PLUGIN_ROOT` = grandparent of this file.

## Path Conventions

```
PLUGIN_ROOT = Two levels above this SKILL.md (contains scripts/, assets/)
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
TODAY       = Today's date, ISO YYYY-MM-DD
```

## Entry Point Routing

| User says | Action |
|---|---|
| `/job-scan setup` | Setup flow |
| "Score new jobs / review backlog" | Phase 2 backlog mode |
| "Run a full scan now" | Phase 1 + Phase 2 full mode |
| `/job-scan score-backlog` | Phase 2 backlog (unattended mode, called by daily_scan.sh) |
| "Confirm / ignore / mark #N" | Status change |
| "Apply to #N" | Phase 5 — prepare application |

## Setup Flow (First-Time Use)

Check if `PLUGIN_ROOT/profile.md` exists. If not, enter setup:

1. **Collect profile**: Interactively guide the user to describe their background, generating `profile.md`. Should cover:
   - Basic info (location, education, years of experience)
   - Core tech stack (experienced level)
   - Technologies known but not expert in (working knowledge)
   - Work experience (each: company, role, dates, key achievements)
   - Education highlights (thesis, high-scoring courses)
   - Differentiators (competitions, open source, talks, etc.)
   - Job search direction (target role types, level preference, location preference)

   Reference `templates/profile.example.md` for structure.

2. **Generate preferences.toml**: Based on user answers. Ask about:
   - Swedish proficiency (fluent/basic/none) → `language.swedish`
   - Citizenship/work permit status → `eligibility.citizenship`, `eligibility.exclude_security_cleared`
   - Preferred daily scan time → `schedule.fetch_time`
   - Whether to enable auto-scoring → `schedule.auto_score`

   Reference `templates/preferences.example.toml` for structure.

3. **Generate search_config.json**: Based on career goals from profile, help define search lanes. Format:
   ```json
   {
     "occupation_field": "apaJ_2ja_LuF",
     "municipality_ids": [],
     "limit": 100,
     "lanes": [
       {"name": "Lane Name", "keywords": ["keyword1", "keyword2"]},
       ...
     ],
     "thresholds": {"Lane Name": 65, ...}
   }
   ```
   `occupation_field` is fixed to IT sector ID `apaJ_2ja_LuF` (JobTech taxonomy).
   Each lane corresponds to one of the user's career directions; keywords are used for JobTech API searches.

4. **Generate target_companies.json** (optional): List of companies the user is interested in. Format:
   ```json
   {"companies": [{"name": "...", "careers_url": "...", "note": "..."}]}
   ```
   User can skip this step and add companies later.

5. **Install scheduler**:
   ```bash
   bash PLUGIN_ROOT/scripts/install_scheduler.sh
   ```

6. After setup, prompt user:
   - "Configuration complete. Daily auto-fetch set for {fetch_time}."
   - "You can now run `/job-scan` to start your first scan and scoring."

## Phase 1 — Fetch

1. JobTech main source:
   ```bash
   python3 SCRIPTS/fetch_jobtech.py --config CONFIG --out /tmp/job-scan-raw.jsonl
   ```
2. Career page supplement: Read `COMPANIES` (target_companies.json), use **WebFetch** on each `careers_url` to scrape public pages, append jobs to `/tmp/job-scan-raw.jsonl`. Format:
   - `link`: Absolute URL to job detail page (stable, unique)
   - `company`/`title`/`location`/`summary`, `source` = `"career"`
   - If a company page fetch fails → skip and log, don't abort.

## Phase 2 — Scoring

**Find jobs to score (choose one):**

- **(A) Backlog mode (default)** — daily launchd/cron already fetched + deduped + merged into fact source. Just get unscored jobs:
  ```bash
  python3 SCRIPTS/results_io.py --mode pending --results RESULTS --out /tmp/job-scan-flagged.jsonl
  ```

- **(B) Full mode** — run Phase 1 first, then diff + dedup:
  ```bash
  python3 SCRIPTS/results_io.py --mode diff --include-pending \
    --raw /tmp/job-scan-raw.jsonl --results RESULTS --out /tmp/job-scan-to-score.jsonl
  python3 SCRIPTS/dedup.py --in /tmp/job-scan-to-score.jsonl --tracker TRACKER --out /tmp/job-scan-flagged.jsonl
  ```

**Deterministic gates (pre-LLM)** — controlled by gate toggles in `preferences.toml`:

```bash
python3 SCRIPTS/lang_gate.py --in /tmp/job-scan-flagged.jsonl --out /tmp/job-scan-flagged.jsonl
python3 SCRIPTS/citizenship_gate.py --in /tmp/job-scan-flagged.jsonl --out /tmp/job-scan-flagged.jsonl
python3 SCRIPTS/pre_gate.py --in /tmp/job-scan-flagged.jsonl --out /tmp/job-scan-flagged.jsonl
python3 SCRIPTS/profile_gap_gate.py --in /tmp/job-scan-flagged.jsonl --out /tmp/job-scan-flagged.jsonl
```

**LLM scoring**: Read `PROFILE`, score all jobs in `/tmp/job-scan-flagged.jsonl` that have **no score**, write `/tmp/job-scan-scored.jsonl`.

### Scoring Methodology

**Scoring flow (for each job to be scored):**

1. **Read profile.md** and infer:
   - User's core stack and depth tiers (experienced vs working knowledge)
   - Years of industrial experience and target seniority level
   - Differentiating signals (competitions, thesis, special projects, etc.)
   - Match strength per lane

2. **Read calibration.jsonl** (if exists) as few-shot reference: each entry contains a job's link, original score, user feedback, and corrected score.

3. **Pre-scoring checklist (answer each before assigning score):**
   - [ ] Is the company a staffing/consulting intermediary? → cap ≤58
   - [ ] Does the JD require tool stacks the profile completely lacks? → check profile_gap_gate flags
   - [ ] Does the JD require deep expertise the profile only touches superficially? → cap ≤55
   - [ ] Is the JD title Senior/Staff/Lead/Principal or does JD expect lead-level ownership? → cap ≤50
   - [ ] Is the JD entirely in Swedish? → deduct ~10 points
   - [ ] Does the job have any `*_gate=true` flags from deterministic gates? → respect their caps

4. **Gate → Cap → Tier**:

   **Gap caps (hit = hard ceiling, take the lowest):**
   | Gap | Cap |
   |---|---|
   | JD requires senior/lead/principal/staff level, or experience years far exceed profile | **≤50** |
   | Profile gap gate triggered (JD requires tool stack profile completely lacks) | **≤ cap from gate flag** |
   | Missing JD's must-have core stack (profile lacks corresponding depth) | **≤55** |
   | Staffing agency / mass-posted consulting intermediary | **≤58** |

   **Evidence-level verification**: "used it / ran on it" ≠ "built / debugged it". When JD requires implementation/integration/troubleshooting depth for a stack, application-layer usage experience in the profile does not count as coverage.

   **Tier anchors (apply after capping):**
   - **80–90**: Level fit + core stack coverage + direct lane match + differentiating signal. Missing any one → <80.
   - **70–79**: In-lane + good core stack coverage, slight level mismatch or average differentiation.
   - **60–69**: In-lane but material gaps.
   - **<60**: Multiple gaps, staffing intermediary, or core stack fundamentally mismatched.

### Calibration Rules

The LLM scorer should always read `calibration.jsonl` before scoring. It contains user-specific feedback and corrected scores as few-shot examples. The following are **generic scoring principles** (not user-specific):

- **Senior cap scope**: Senior cap ≤50 applies to role-level expectations (senior/lead title, team ownership), not to years-of-experience requirements for a specific technology.
- **ML training vs deployment**: JD requiring ML method development (designing/refining models, training on datasets) is a different skill from ML deployment/inference optimization. If profile only covers one side, treat the other as a core stack gap. → ≤55
- **Swedish JD**: JD written entirely in Swedish without matching lang_gate hard phrases: do not exclude, but deduct ~10 points and note in reason.
- **Profile gap gate flags**: If `profile_gap_gate.py` has set gate flags (e.g. `control_stack_gate=true`), the JD requires tool stacks the user's profile lacks. Respect the cap specified in the flag unless you have strong evidence the flag is wrong.

5. **Output field contract:**
   - `score`: Integer 0–100
   - `lane`: Must be one of `search_config.json`'s `lanes[].name`, or empty string `""`. Do not invent variants.
   - `reason`: One sentence, **must include both hits AND gaps**.
   - If job has `control_stack_gate=true` or `staffing_gate=true`, these flags were set by deterministic pre-filters. Respect the implied caps (≤50 and ≤55 respectively) unless you have strong evidence the flag is wrong.

6. **JD language signal**: If JD is written entirely in Swedish (even without matching lang_gate hard phrases) → do not exclude, but deduct ~10 points and note in reason.

7. **maybe_applied signal**: If `maybe_applied=true`, deduct slightly and note in reason.

### Unattended Mode (score-backlog)

When invoked in unattended/headless mode (e.g., from `daily_scan.sh`):

1. Use backlog mode (A) to get pending jobs
2. Run deterministic gates + LLM scoring
3. Merge + render
4. Mark high-match jobs for review
5. **Do not start review server, do not wait for user confirmation, do not output interactive summary**
6. Exit silently when done

## Phase 3+4 — Merge + Render

```bash
python3 SCRIPTS/results_io.py --mode merge \
  --scored /tmp/job-scan-scored.jsonl \
  --seen /tmp/job-scan-raw.jsonl \
  --results RESULTS --md MD --today TODAY
```

Backlog mode omits `--seen`. Merge uses `link` as primary key: new jobs are inserted; existing jobs retain user status, refresh `last_seen`.

**Render:**

```bash
python3 SCRIPTS/render_html.py
```

**Interactive session (not unattended): start review server in background:**

```bash
python3 SCRIPTS/review_server.py   # opens http://localhost:8765
```

Then list high-match jobs (score ≥ lane thresholds) with summary + link + reason, and wait for user confirmation. Mark high-match jobs for review:

```bash
python3 SCRIPTS/results_io.py --mode status \
  --results RESULTS --md MD --link "<link>" --status "shortlisted"
```

## Status Changes

When user says "confirm / ignore / mark #N", map to link:

```bash
python3 SCRIPTS/results_io.py --mode status \
  --results RESULTS --md MD --link "<link>" --status "<shortlisted|reviewed|ignored>"
```

Re-render HTML after status change: `python3 SCRIPTS/render_html.py`

## Phase 5 — Prepare Application

```bash
python3 SCRIPTS/prep_apply.py --list [--min-score N]
python3 SCRIPTS/prep_apply.py --prep "<link1>" "<link2>" ...
```

After applying, set status:

```bash
python3 SCRIPTS/results_io.py --mode status \
  --results RESULTS --md MD --link "<link>" --status "applied"
```

## Feedback Loop (Calibration)

When a user says a score is too high or too low, append to `CALIBRATION`:

```json
{"link": "...", "original_score": 78, "corrected_score": 55, "feedback": "Core stack mismatch, should trigger ≤55 cap", "date": "2026-06-18"}
```

Next LLM scoring run reads `calibration.jsonl` as few-shot reference to continuously improve scoring accuracy.

## Scheduling (Auto-Configured)

`/job-scan setup` calls `scripts/install_scheduler.sh` to automatically install:
- macOS: launchd plist (`~/Library/LaunchAgents/com.job-scan.daily.plist`)
- Linux: crontab entry

Runs `scripts/daily_scan.sh` daily at the time set in `preferences.toml` (`schedule.fetch_time`).
If `schedule.auto_score = true`, auto-invokes the AI coding agent in headless mode to score pending jobs after fetch.
Scoring failure does not affect fetch results; pending jobs accumulate until next run.

## Lessons Learned

See `lessons.md` in this directory for operational pitfalls discovered during use.
