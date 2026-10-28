"""Central path and config resolution for job-scan.

All scripts import from here instead of hardcoding paths.
REPO_ROOT is the parent of scripts/.
"""
import os
import json
import sys

if sys.version_info < (3, 11):
    raise SystemExit("job-scan requires Python >= 3.11 (for tomllib). Current: " + sys.version)

import tomllib

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))

# Git-tracked assets
ASSETS_DIR = os.path.join(REPO_ROOT, "assets")
STAFFING_COMPANIES = os.path.join(ASSETS_DIR, "staffing_companies.json")
RESTRICTED_EMPLOYERS = os.path.join(ASSETS_DIR, "restricted_employers.json")

# User-generated config (created by setup)
PROFILE = os.path.join(REPO_ROOT, "profile.md")
PREFERENCES = os.path.join(REPO_ROOT, "preferences.toml")
SEARCH_CONFIG = os.path.join(REPO_ROOT, "search_config.json")
TARGET_COMPANIES = os.path.join(REPO_ROOT, "target_companies.json")

# Runtime output
OUTPUT_DIR = os.path.join(REPO_ROOT, "output")
RESULTS = os.path.join(OUTPUT_DIR, "job-scan-results.jsonl")
MD = os.path.join(OUTPUT_DIR, "job-scan-results.md")
HTML = os.path.join(OUTPUT_DIR, "job-scan-results.html")
TRACKER = os.path.join(OUTPUT_DIR, "applications-tracker.md")

# CV tailoring (personal, gitignored)
CV_DIR = os.path.join(REPO_ROOT, "cv")
CV_BASE_DIR = os.path.join(CV_DIR, "base")
CV_TEMPLATE_DIR = os.path.join(CV_DIR, "template")
CV_VARIANTS = os.path.join(CV_DIR, "variants.json")


def _apply_pref(key, default):
    """Read [apply].<key> from preferences.toml (paths below are needed at import time)."""
    try:
        with open(PREFERENCES, "rb") as f:
            return tomllib.load(f).get("apply", {}).get(key, default)
    except (OSError, tomllib.TOMLDecodeError):
        return default


# Per-job folders (job_summary, tailored cv.tex, PDFs). Keep it outside ~/.claude:
# headless Claude Code refuses to write there.
APPLICATIONS_DIR = os.path.expanduser(_apply_pref("output_dir", "~/Desktop/job-applications"))
PDF_NAME = _apply_pref("pdf_name", "Application")
CV_PDF = f"{PDF_NAME}_CV.pdf"
LETTER_PDF = f"{PDF_NAME}_Cover_Letter.pdf"

# Calibration feedback
CALIBRATION = os.path.join(REPO_ROOT, "calibration.jsonl")

# Temp files
TMP_RAW = "/tmp/job-scan-raw.jsonl"
TMP_TO_SCORE = "/tmp/job-scan-to-score.jsonl"
TMP_FLAGGED = "/tmp/job-scan-flagged.jsonl"
TMP_SCORED = "/tmp/job-scan-scored.jsonl"
TMP_PENDING = "/tmp/job-scan-pending.jsonl"


def ensure_output_dir():
    os.makedirs(OUTPUT_DIR, exist_ok=True)


def load_preferences():
    """Load preferences.toml, return dict. Returns empty dict if missing."""
    if not os.path.exists(PREFERENCES):
        return {}
    with open(PREFERENCES, "rb") as f:
        return tomllib.load(f)


def load_search_config():
    """Load search_config.json."""
    with open(SEARCH_CONFIG, encoding="utf-8") as f:
        return json.load(f)


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)
