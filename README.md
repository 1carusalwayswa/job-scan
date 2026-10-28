# job-scan

Automated job scanning and LLM-powered scoring for IT positions in Sweden.

A [Claude Code](https://docs.anthropic.com/en/docs/claude-code) plugin that fetches jobs from the Swedish JobTech API and target company career pages, scores them against your profile using Claude, and supports fully unattended daily runs.

## Prerequisites

- **Claude Code** CLI (with an active plan or API key)
- **Python ≥ 3.11** (uses `tomllib` from the standard library)
- **macOS** or **Linux** (for automated scheduling)

## Install

```bash
# Option 1: as a Claude Code plugin
claude plugin install https://github.com/1carusalwayswa/job-scan

# Option 2: manual
git clone https://github.com/1carusalwayswa/job-scan ~/.claude/plugins/job-scan
```

## Quick Start

```
/job-scan setup
```

The interactive setup will:
1. Generate your `profile.md` (background, skills, experience)
2. Generate `preferences.toml` (language ability, eligibility, gate toggles, schedule)
3. Generate `search_config.json` (search lanes and keywords based on your career goals)
4. Optionally generate `target_companies.json` (specific company career pages to watch)
5. Install a daily scheduler (launchd on macOS, cron on Linux)

## Usage

### Interactive (in a Claude Code session)

```
/job-scan              # Score pending backlog jobs
/job-scan setup        # First-time setup or re-configure
```

In the conversation you can also:
- "Confirm #3" / "Ignore #5" — change job status
- "Apply to #2" — prepare application materials
- "Run a full scan now" — fetch + score from scratch

### Automated (daily via launchd/cron)

After setup, `scripts/daily_scan.sh` runs daily:
1. Fetches new jobs from JobTech API
2. Runs deterministic gates (language, citizenship, staffing, occupation)
3. Merges into results and renders HTML
4. If `auto_score = true` in preferences, invokes `claude -p` to LLM-score pending jobs

### Review

Open the HTML dashboard:
```bash
python3 scripts/review_server.py   # http://localhost:8765
```
Or directly open `output/job-scan-results.html` in a browser.

### Tailored CV & cover letter (per job)

Turn a recommended job into a CV tailored to its JD — from your own LaTeX CV — and, if you want, a cover letter. Both come out as PDFs you review and upload yourself; nothing is ever submitted for you.

One-time setup (everything in `cv/` is personal and gitignored):

```
cv/base/<variant>.tex          # your LaTeX CV(s), one per role type (e.g. ml.tex, backend.tex)
cv/template/                   # class/style files they need (e.g. developercv.cls)
cv/variants.json               # lane -> variant; start from templates/cv/variants.example.json
cv/cover_letter_template.tex   # start from templates/cv/cover_letter_template.example.tex
cv/transcript.md               # optional: courses + grades for "relevant coursework"
cv/claims_to_confirm.md        # optional: statements the tailoring must not spread
```

PDFs are compiled locally with [Tectonic](https://tectonic-typesetting.github.io/) (`brew install tectonic`).

Then, either:
- **Dashboard:** `python3 scripts/review_server.py` → each job has **Tailor CV** and **Cover letter** buttons. Generation runs headless (`claude -p`) in ~1–3 min; the row then links the PDFs.
- **Chat:** "Tailor CV for #3", "Prepare the top 5", "Write a cover letter for #3".
- **CLI:** `prep_apply.py --top 5 --cv` (job folders + base CV), `prep_apply.py --build <dir>` (diff, PDFs, Overleaf zip).

Each job gets a folder in `[apply].output_dir` (default `~/Desktop/job-applications/`):

```
<company-title>/
  <pdf_name>_CV.pdf              # ready to upload
  <pdf_name>_Cover_Letter.pdf    # only if requested
  cover_letter.md                # plain text for application forms
  jd_match.md                    # JD requirement -> evidence -> hit/gap, interview prep
  cv.tex, cv_base.tex, changes.diff, overleaf.zip
```

How tailoring works:
- The base variant is picked from the job's lane, then rewritten for the JD: summary, skill order, bullet choice and wording, project order — using only facts from `profile.md`, your base CVs and transcript. Missing skills go into `jd_match.md` as interview prep, never onto the CV.
- Page count is checked against the base; LaTeX errors get one automatic repair pass.
- The headless run is sandboxed because the JD is untrusted text: it can read files and edit only that job's folder, with no shell and no web access. Packaging and compiling are done by the server, and the server only accepts same-origin JSON requests.
- The output folder must be outside `~/.claude/`, since headless Claude Code refuses to write there.

## Project Structure

```
.claude-plugin/plugin.json    — Claude Code plugin metadata
skills/job-scan/SKILL.md      — Skill definition (scoring methodology, flows)
scripts/
  config.py                   — Central path resolution
  daily_scan.sh               — Daily unattended scan pipeline
  setup_scheduler.sh          — Install launchd/cron scheduler
  fetch_jobtech.py            — JobTech API fetcher
  results_io.py               — JSONL fact-source read/write/merge
  dedup.py                    — Fuzzy dedup against application tracker
  lang_gate.py                — Swedish language requirement gate
  citizenship_gate.py         — Security clearance / citizenship gate
  pre_gate.py                 — Staffing company + occupation group gate
  render_html.py              — HTML dashboard renderer
  review_server.py            — Local HTTP server for status updates
  prep_apply.py               — Prepare application dirs, base CV copy, build (diff/PDF/zip)
  apply_docs.py               — Headless CV / cover-letter generation for dashboard buttons
assets/
  staffing_companies.json     — Known staffing/temp agency patterns
  restricted_employers.json   — Security-cleared employer patterns
templates/
  profile.example.md          — Example candidate profile
  preferences.example.toml    — Example preferences with all options
  cv/                         — Examples for the CV-tailoring setup (variants, cover letter)
```

User-generated files (gitignored):
```
profile.md                    — Your candidate profile
preferences.toml              — Your runtime preferences
search_config.json            — Your search lanes and keywords
target_companies.json         — Your target company career pages
output/                       — Results (JSONL, Markdown, HTML)
calibration.jsonl             — Scoring feedback for continuous improvement
cv/                           — Your base CVs, LaTeX class, cover-letter template
```

## Scoring Methodology

Scoring follows a **gate → cap → tier** framework:

1. **Deterministic gates** (pre-LLM, zero tokens): language requirements, security clearance, staffing agencies, occupation groups
2. **LLM scoring** reads your `profile.md` and applies:
   - **Cap rules**: senior/lead roles cap at ≤50, missing core stack caps at ≤55, staffing agencies cap at ≤58
   - **Evidence-level verification**: "used it" ≠ "built/debugged it"
   - **Tier anchors**: 80–90 (strong match), 70–79 (good match), 60–69 (partial), <60 (weak)
3. **Calibration loop**: when you mark a score as wrong, feedback is saved to `calibration.jsonl` and used as few-shot examples in future scoring

## License

MIT
