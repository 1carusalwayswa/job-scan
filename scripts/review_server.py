#!/usr/bin/env python3
"""Local review server: one-click job status updates in the browser.

Usage: python3 review_server.py
GET /  -> re-render and serve HTML
POST /api/status {"link":..., "status":...} -> update fact source and re-render
POST /api/doc {"link":..., "kind": "cv"|"cover_letter", "force": bool} -> start generation
GET  /api/doc-status?link=... -> generation state + available files
GET  /files/<job-dir>/<file> -> download a generated file (overleaf.zip, cv.tex, ...)
Auto-exits after 60 minutes idle.
"""
import http.server
import json
import os
import subprocess
import sys
import threading
import time
import urllib.parse
import webbrowser

SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, SCRIPT_DIR)
from config import RESULTS, MD, HTML, APPLICATIONS_DIR
import apply_docs

PORT = 8765
IDLE_EXIT_SECONDS = 60 * 60
ALLOWED_STATUSES = {"new", "shortlisted", "reviewed", "ignored", "applied", "rejected"}
ALLOWED_ORIGINS = {f"http://localhost:{PORT}", f"http://127.0.0.1:{PORT}"}

last_request = time.time()


def render():
    subprocess.run(
        [sys.executable, os.path.join(SCRIPT_DIR, "render_html.py")],
        check=True, capture_output=True,
    )


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _touch(self):
        global last_request
        last_request = time.time()

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _same_origin_json(self):
        """Block cross-site requests: other pages can't send JSON here without a preflight."""
        origin = self.headers.get("Origin")
        ctype = self.headers.get("Content-Type", "")
        return ctype.startswith("application/json") and (origin is None or origin in ALLOWED_ORIGINS)

    def _serve_file(self, rel):
        parts = rel.split("/")
        if len(parts) != 2 or parts[1] not in apply_docs.DOC_FILES or parts[0] in ("", ".", ".."):
            self._send(404, {"error": "not found"})
            return
        path = os.path.join(APPLICATIONS_DIR, parts[0], parts[1])
        if not os.path.isfile(path):
            self._send(404, {"error": "not found"})
            return
        self.send_response(200)
        if path.endswith(".pdf"):
            self.send_header("Content-Type", "application/pdf")
            self.send_header("Content-Disposition", f'inline; filename="{parts[1]}"')
        elif path.endswith(".zip"):
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Disposition", f'attachment; filename="{parts[0]}.zip"')
        else:
            self.send_header("Content-Type", "text/plain; charset=utf-8")
        data = open(path, "rb").read()
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self._touch()
        url = urllib.parse.urlsplit(self.path)
        if url.path.startswith("/files/"):
            self._serve_file(urllib.parse.unquote(url.path[len("/files/"):]))
            return
        if url.path == "/api/doc-status":
            link = urllib.parse.parse_qs(url.query).get("link", [""])[0]
            row = apply_docs.find_row(link)
            if row is None:
                self._send(404, {"error": f"link not found: {link}"})
                return
            self._send(200, apply_docs.status_for_row(row))
            return
        if self.path not in ("/", "/index.html"):
            self._send(404, {"error": "not found"})
            return
        try:
            render()
            self._send(200, open(HTML, "rb").read(), "text/html; charset=utf-8")
        except Exception as e:
            self._send(500, {"error": str(e)})

    def do_POST(self):
        self._touch()
        if not self._same_origin_json():
            self._send(403, {"error": "forbidden"})
            return
        if self.path == "/api/doc":
            self._post_doc()
            return
        if self.path != "/api/status":
            self._send(404, {"error": "not found"})
            return
        try:
            payload = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
            link, status = payload["link"], payload["status"]
        except Exception:
            self._send(400, {"error": "bad request"})
            return
        if status not in ALLOWED_STATUSES:
            self._send(400, {"error": f"invalid status: {status}"})
            return
        if not link.startswith("http"):
            self._send(400, {"error": f"invalid link: {link}"})
            return
        proc = subprocess.run(
            [sys.executable, os.path.join(SCRIPT_DIR, "results_io.py"),
             "--mode", "status", "--results", RESULTS, "--md", MD,
             "--link", link, "--status", status],
            capture_output=True, text=True,
        )
        if proc.returncode != 0:
            self._send(500, {"error": proc.stderr.strip() or proc.stdout.strip()})
            return
        render()
        print(f"  {status} <- {link}")
        self._send(200, {"ok": True})


    def _post_doc(self):
        try:
            payload = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
            link, kind = payload["link"], payload["kind"]
        except Exception:
            self._send(400, {"error": "bad request"})
            return
        try:
            st = apply_docs.start(link, kind, force=bool(payload.get("force")))
        except (ValueError, subprocess.CalledProcessError) as e:
            self._send(400, {"error": str(e)})
            return
        print(f"  {kind} generation started <- {link}")
        self._send(200, st)


def idle_watchdog(server):
    while True:
        time.sleep(60)
        if time.time() - last_request > IDLE_EXIT_SECONDS:
            print("idle timeout, exiting.")
            threading.Thread(target=server.shutdown, daemon=True).start()
            return


def main():
    server = http.server.ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    threading.Thread(target=idle_watchdog, args=(server,), daemon=True).start()
    url = f"http://localhost:{PORT}/"
    print(f"review server: {url}  (Ctrl-C to quit, auto-exits after 60 min idle)")
    webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
