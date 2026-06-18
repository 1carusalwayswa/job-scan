#!/usr/bin/env python3
"""本地 review server：在浏览器里一键标记岗位状态。

用法: python3 review_server.py
GET /  → 重新渲染并返回 HTML
POST /api/status {"link":..., "status":...} → 写事实源并重渲染
闲置 60 分钟自动退出。
"""
import http.server
import json
import os
import subprocess
import sys
import threading
import time
import webbrowser

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
from config import RESULTS, MD, HTML

PORT = 8765
IDLE_EXIT_SECONDS = 60 * 60
ALLOWED_STATUSES = {"新", "待确认", "已看", "已忽略", "已转apply"}

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

    def do_GET(self):
        self._touch()
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
