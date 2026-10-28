#!/usr/bin/env python3
"""apply_docs.py -- Background generation of a tailored CV / cover letter for one job.

Used by review_server.py (dashboard buttons). Each run:
  1. prep_apply.py --prep LINK [--cv]        deterministic: job dir + base CV
  2. claude -p "/job-scan tailor-cv|cover-letter"
       sandboxed: Read anywhere, Edit/Write only inside the job dir,
       no Bash and no web tools (the JD is untrusted text)
  3. prep_apply.py --build JOB_DIR           deterministic: changes.diff, overleaf.zip, PDFs
     (on LaTeX errors the agent gets one repair pass, then --build runs again)
State lives in APPLICATIONS_DIR/<job>/.status-<kind>.json so it survives page reloads.
"""
import json
import os
import shutil
import subprocess
import sys
import threading
import time

SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, SCRIPT_DIR)
from config import APPLICATIONS_DIR, CV_PDF, LETTER_PDF, REPO_ROOT, load_preferences
from prep_apply import dir_name, load_rows

# kind -> (skill sub-command, file the agent must produce, PDF the build must produce)
KINDS = {
    "cv": ("tailor-cv", "jd_match.md", CV_PDF),
    "cover_letter": ("cover-letter", "cover_letter.md", LETTER_PDF),
}
# Files the dashboard may link to (served by review_server /files/), in display order
DOC_FILES = (CV_PDF, LETTER_PDF, "jd_match.md", "cover_letter.md", "changes.diff",
             "cv.tex", "cover_letter.tex", "overleaf.zip")

PROMPT = """Task: job-scan `{cmd}` for one job. Read {root}/skills/job-scan/SKILL.md first and follow it.

Unattended run from the review dashboard — do not ask questions, do not wait for confirmation.
- PLUGIN_ROOT={root}
- LINK={link}
- JOB_DIR={job_dir}
The job dir already contains job_summary.md{cv_note}.
You have no shell in this run: read files with Read, change files in JOB_DIR with Edit/Write only.
The packaging step (--build) runs automatically after you exit.
Follow SKILL.md Phase 5 for this one job only, then exit.
"""

REPAIR_PROMPT = """The LaTeX in {job_dir} failed to compile. Errors:

{errors}

Fix only the offending lines in the .tex file(s) named above, using Read and Edit inside {job_dir}.
Do not change content otherwise. No shell is available; the build reruns after you exit.
"""


def find_row(link):
    for o in load_rows():
        if o.get("link") == link:
            return o
    return None


def job_dir_for(row):
    return os.path.join(APPLICATIONS_DIR, dir_name(row))


def _status_path(d, kind):
    return os.path.join(d, f".status-{kind}.json")


def _write_status(d, kind, **st):
    with open(_status_path(d, kind), "w") as f:
        json.dump(st, f)


def _pid_alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except (OSError, TypeError):
        return False


def status_for_row(row):
    """{"dir": name, "cv": {...}, "cover_letter": {...}, "files": [...]} for one results row."""
    d = job_dir_for(row)
    out = {"dir": os.path.basename(d), "files": []}
    for kind in KINDS:
        st = {"state": "none"}
        p = _status_path(d, kind)
        if os.path.exists(p):
            with open(p) as f:
                st = json.load(f)
            if st.get("state") == "running" and not _pid_alive(st.get("pid")):
                st["state"] = "failed"   # the server that ran this job died mid-run
        out[kind] = st
    if os.path.isdir(d):
        out["files"] = [f for f in DOC_FILES if os.path.exists(os.path.join(d, f))]
    return out


def claude_bin():
    return shutil.which("claude") or os.path.expanduser("~/.local/bin/claude")


def start(link, kind, force=False):
    """Kick off generation in the background. Returns status_for_row() or raises ValueError."""
    if kind not in KINDS:
        raise ValueError(f"unknown kind: {kind}")
    row = find_row(link)
    if row is None:
        raise ValueError(f"link not found: {link}")
    d = job_dir_for(row)
    if status_for_row(row)[kind].get("state") == "running":
        return status_for_row(row)
    if not os.path.exists(claude_bin()):
        raise ValueError("claude CLI not found on PATH")

    prep_apply = os.path.join(SCRIPT_DIR, "prep_apply.py")
    prep = [sys.executable, prep_apply, "--prep", link]
    if kind == "cv":
        prep.append("--cv")
        if force:
            prep.append("--force")   # reset cv.tex to the base before re-tailoring
    subprocess.run(prep, check=True, capture_output=True, text=True)

    cmd, agent_file, pdf_file = KINDS[kind]
    cv_note = " and cv.tex/cv_base.tex (base CV)" if kind == "cv" else ""
    prompt = PROMPT.format(cmd=cmd, root=REPO_ROOT, link=link, job_dir=d, cv_note=cv_note)
    budget = str(load_preferences().get("apply", {}).get("max_budget_usd", 3.0))
    log = open(os.path.join(d, f"{kind}.log"), "w")
    started = time.time()

    def spawn(text):
        return subprocess.Popen(
            [claude_bin(), "-p", text, "--add-dir", REPO_ROOT,
             # "//" marks an absolute path; Edit rules cover Write too
             "--allowedTools", "Read", f"Edit(/{d}/**)",
             "--disallowedTools", "Bash", "WebFetch", "WebSearch",
             "--max-budget-usd", budget],
            cwd=d, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
        )

    def fresh(name):
        path = os.path.join(d, name)
        return os.path.exists(path) and os.path.getmtime(path) >= started

    def build():
        log.flush()
        return subprocess.run([sys.executable, "-u", prep_apply, "--build", d],
                              stdout=log, stderr=subprocess.STDOUT).returncode

    proc = spawn(prompt)
    # liveness = this server process: the waiting thread below finalises the status
    _write_status(d, kind, state="running", pid=os.getpid(), started=started)

    def wait():
        nonlocal proc
        rc = proc.wait()
        ok = rc == 0 and fresh(agent_file)
        if ok and build() != 0:
            err_path = os.path.join(d, "build_errors.txt")
            errors = open(err_path).read() if os.path.exists(err_path) else "unknown error"
            proc = spawn(REPAIR_PROMPT.format(job_dir=d, errors=errors))
            proc.wait()
            build()
        ok = ok and fresh(pdf_file)
        log.close()
        _write_status(d, kind, state="done" if ok else "failed", rc=rc,
                      started=started, finished=time.time())

    threading.Thread(target=wait, daemon=True).start()
    return status_for_row(row)
