#!/usr/bin/env python3
"""macfleet-dash endpoint — read-only fleet probe served as text/plain.

Runs the bundled POSIX probe and answers GET /metrics.txt with its output.
Bind it to a loopback or tailnet address only; it has no authentication, so
it must never be reachable from the public internet.

Bind address (first match wins):
  1. CLI argument:      python3 metrics_server.py 100.64.0.5:8791
  2. Environment:       MACFLEET_BIND=100.64.0.5:8791
  3. Default:           127.0.0.1:8791

Endpoints:
  GET /metrics.txt   probe output (text/plain), 5s cache, 45s probe timeout
  GET /healthz       "ok" when the server is alive (does not run the probe)

Python 3.9+ standard library only. See endpoint/install.sh for the LaunchAgent.
"""

import os
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

VERSION = "0.1.0"
APP_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROBE_PATH = os.path.join(APP_ROOT, "probe", "fleet-probe.sh")
PROBE_TIMEOUT_S = 45
CACHE_SECONDS = 5.0


def run_probe() -> str:
    """Run the probe script locally and return its stdout ('' on failure)."""
    with open(PROBE_PATH, "r", encoding="utf-8") as fh:
        script = fh.read()
    try:
        completed = subprocess.run(
            ["/bin/sh", "-c", script],
            capture_output=True, text=True, timeout=PROBE_TIMEOUT_S,
        )
    except (subprocess.TimeoutExpired, OSError):
        return ""
    return completed.stdout if completed.returncode == 0 else ""


class MetricsHandler(BaseHTTPRequestHandler):
    server_version = "macfleet-dash/%s" % VERSION

    # Small in-process cache so a polling fleet never stacks probes.
    cache_lock = threading.Lock()
    cache_text = ""
    cache_at = 0.0

    def _send(self, code: int, body: str, content_type: str) -> None:
        payload = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:  # noqa: N802 (http.server API)
        path = self.path.split("?", 1)[0]
        if path == "/metrics.txt":
            with MetricsHandler.cache_lock:
                fresh = time.monotonic() - MetricsHandler.cache_at < CACHE_SECONDS
                if not fresh:
                    MetricsHandler.cache_text = run_probe()
                    MetricsHandler.cache_at = time.monotonic()
                text = MetricsHandler.cache_text
            if "PROBE_OK" not in text:
                self._send(503, "probe unavailable\n", "text/plain; charset=utf-8")
                return
            self._send(200, text, "text/plain; charset=utf-8")
        elif path in ("/", "/healthz"):
            self._send(200, "ok\n", "text/plain; charset=utf-8")
        else:
            self._send(404, "not found\n", "text/plain; charset=utf-8")

    def log_message(self, fmt: str, *args: object) -> None:  # quiet access log
        sys.stderr.write("%s %s\n" % (self.log_date_time_string(), fmt % args))


def main(argv: list) -> int:
    raw_bind = argv[1] if len(argv) > 1 else os.environ.get("MACFLEET_BIND", "")
    if not raw_bind:
        raw_bind = "127.0.0.1:8791"
    if ":" in raw_bind:
        host, port_text = raw_bind.rsplit(":", 1)
        port = int(port_text)
    else:
        host, port = raw_bind, 8791

    if host in ("0.0.0.0", "::", ""):
        sys.stderr.write(
            "warning: binding to all interfaces — this endpoint has no auth. "
            "Bind a loopback or tailscale IP instead.\n"
        )

    server = ThreadingHTTPServer((host, port), MetricsHandler)
    sys.stderr.write(
        "macfleet-dash endpoint %s on http://%s:%d/metrics.txt (probe: %s)\n"
        % (VERSION, host, port, PROBE_PATH)
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        sys.stderr.write("\nstopped\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
