# job-scan — Swedish IT Job Discovery + Triage Claude Code Skill

Discover and triage Swedish IT/software jobs: pull from the JobTech (Arbetsförmedlingen) API plus companies' public career pages, score them against your profile and custom lanes with an LLM, dedup by stable link, maintain a jsonl source of truth, render md/html lists, and flag high matches as "to confirm" for your decision.

> **This file is for the deployer / deploying agent** (how to go from clone to running). The skill's own usage lives in `SKILL.md`.

## Scope / Limits
- The data source is **Swedish JobTech**; it only covers Swedish jobs. `occupation_field` is a Swedish occupation-taxonomy code.
- This is a reshapeable **template**: language gate, lanes, and profile all come from config. Editing `local_language`/`lanes` adapts it to your situation, but the data source is still Sweden.
- LLM scoring happens in an interactive session (using your Claude subscription/quota); the daily `daily_scan.sh` runs only the zero-token deterministic pipeline.

## Dependencies
- Python 3 (standard library only, no third-party packages).
- Claude Code (loaded as a skill).
- Network access to `jobsearch.api.jobtechdev.se` (no API key required).

## Install

> Steps marked **[agent auto]** can be done directly by a deploying agent; **[ask user]** ones must first get info from the user.

1. **[agent auto]** Put this repo into the Claude Code skills directory (or use it as a skill in place). Confirm `SKILL.md` is discoverable.
2. **[agent auto]** Create the real config files:
   ```bash
   cp assets/profile.example.md         assets/profile.md
   cp assets/search_config.example.json assets/search_config.json
   cp assets/target_companies.example.json assets/target_companies.json
   ```
   (These three real files are already in `.gitignore` and won't be committed.)
3. **[ask user]** Fill in `assets/profile.md`: target level, location, **local-language ability** (decides whether the language gate excludes a job), core skills, per-lane weights.
4. **[ask user]** Edit `assets/search_config.json`: lanes and `thresholds`, `local_language` (default Swedish), optional `municipality_ids` (city codes; empty = nationwide).
5. **[ask user, optional]** Edit `assets/target_companies.json` to the company career pages you want to watch.
6. **[agent can do, path needs user confirmation]** Deploy the daily schedule (optional): see `deploy/README.md` (macOS launchd / Linux systemd).

## Smoke Test

```bash
# Pull from the main source (writes /tmp/raw.jsonl)
python3 scripts/fetch_jobtech.py --config assets/search_config.json --out /tmp/raw.jsonl
# Merge into the source of truth and render (RESULTS is auto-created on first run)
JOBDIR=${JOB_SCAN_DIR:-$HOME/job-scan}; mkdir -p "$JOBDIR"
python3 scripts/results_io.py --mode merge --scored /dev/null --seen /tmp/raw.jsonl \
  --results "$JOBDIR/job-scan-results.jsonl" --md "$JOBDIR/job-scan-results.md" --today "$(date +%F)"
python3 scripts/render_html.py --results "$JOBDIR/job-scan-results.jsonl" --out "$JOBDIR/job-scan-results.html"
# Run the tests
python3 -m pytest tests/ -v   # or: python3 -m unittest discover -s tests -t .
```
Expected: jsonl/md/html are generated under `$JOBDIR`, and the test suite is all green.

## Privacy Guard
- The real `profile.md`/`search_config.json`/`target_companies.json`, ledger outputs, and schedule instance files are all `.gitignore`d — **don't force `git add` them**.
- **Don't push copies containing your ledger/profile to a public repo.** To publish changes, ship only the engine and the `*.example.*` files.
- The application history `applications-tracker.md` (if used) contains personal data and is ignored.
