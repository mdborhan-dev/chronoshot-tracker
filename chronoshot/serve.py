"""Serve the report (and its screenshots) over localhost, as a daemon by default."""

import http.server
import os
import signal
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from argparse import Namespace
from pathlib import Path
from urllib.parse import quote

from . import config
from .util import ensure_dirs


class _Handler(http.server.SimpleHTTPRequestHandler):
    """Serves everything from the data folder, so ../screenshots/... works."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(config.BASE_DIR), **kwargs)

    def log_message(self, fmt, *args):
        # Only complain about real errors; keep 2xx/3xx off the console.
        if args and str(args[1]).startswith(("4", "5")):
            super().log_message(fmt, *args)


def _server_pid():
    """Return the server PID if it's running, else None. Cleans up stale PID files."""
    try:
        pid = int(config.SERVER_PID_FILE.read_text().strip())
    except (FileNotFoundError, ValueError):
        return None
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        config.SERVER_PID_FILE.unlink(missing_ok=True)
        return None
    except PermissionError:
        return pid
    return pid


def _url_for(host, port, report_path):
    """URL where the report is reachable, or None if it's outside BASE_DIR."""
    try:
        rel = report_path.relative_to(config.BASE_DIR)
    except ValueError:
        return None
    return f"http://{host}:{port}/" + quote(str(rel).replace(os.sep, "/"))


def _server_loop(host, port):
    """The actual HTTP server. Runs forever until SIGTERM/SIGINT."""
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    signal.signal(signal.SIGINT, lambda *_: sys.exit(0))
    try:
        server = http.server.ThreadingHTTPServer((host, port), _Handler)
    except OSError as e:
        print(f"❌ Could not bind {host}:{port} — {e}", flush=True)
        sys.exit(1)
    print(f"serving {config.BASE_DIR} on http://{host}:{port}/", flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()


def _wait_for_port(host, port, timeout=3.0):
    """Wait until the server accepts a TCP connection. True if it came up."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.3):
                return True
        except OSError:
            time.sleep(0.1)
    return False


def _stop_server():
    pid = _server_pid()
    if not pid:
        print("Server is not running.")
        return
    try:
        os.kill(pid, signal.SIGTERM)
        print(f"Stopped server (PID {pid}).")
    except ProcessLookupError:
        print("Server was already gone.")
    config.SERVER_PID_FILE.unlink(missing_ok=True)


def _server_status(host, port, report_path):
    pid = _server_pid()
    if pid:
        print(f"Server is running (PID {pid}).")
        print(f"  URL: {_url_for(host, port, report_path)}")
    else:
        print("Server is not running.")
        print("  Start it with: chronoshot.py serve")


def cmd_serve(args):
    ensure_dirs()

    host = args.host or config.SERVE_HOST
    port = args.port or config.SERVE_PORT
    report_path = (
        Path(args.report).expanduser().resolve() if args.report else config.REPORT_FILE
    )

    if args.stop:
        _stop_server()
        return

    if args.status:
        _server_status(host, port, report_path)
        return

    # Already running? Don't start a second one.
    existing = _server_pid()
    if existing and not args.foreground:
        url = _url_for(host, port, report_path)
        print(f"Server already running (PID {existing}) at {url}")
        print("  Stop it with: chronoshot.py serve --stop")
        if not args.no_open:
            webbrowser.open(url)
        return

    # Build the report if asked, or if it isn't there yet.
    if args.build or not report_path.exists():
        from .report import cmd_report

        print(f"Building report: {report_path}")
        cmd_report(
            Namespace(
                date=None,
                last=None,
                from_=None,
                to=None,
                project=None,
                embed=False,
                open=False,
                out=str(report_path),
            )
        )
        if not report_path.exists():
            print("❌ Report could not be built. Run 'report' manually to see why.")
            return

    url = _url_for(host, port, report_path)
    if url is None:
        print(f"⚠️  {report_path} is outside the data folder ({config.BASE_DIR}).")
        print("    Screenshots may not load. Serving the data folder anyway.")
        url = f"http://{host}:{port}/"

    if args.foreground:
        if host not in ("127.0.0.1", "localhost"):
            print(
                "⚠️  Bound to a non-local address. Anyone on your network can view this."
            )
        print(f"Report: {url}")
        print("Press Ctrl+C to stop.")
        if not args.no_open:
            threading.Thread(
                target=lambda: (time.sleep(0.4), webbrowser.open(url)),
                daemon=True,
            ).start()
        _server_loop(host, port)
        return

    # Daemon mode: spawn a detached child, write its PID, wait for it to come up.
    cmd = [
        sys.executable,
        "-m",
        "chronoshot",
        "_server",
        "--host",
        host,
        "--port",
        str(port),
    ]
    log = open(config.SERVER_LOG_FILE, "a")
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=log,
        stderr=log,
        start_new_session=True,
        cwd=str(Path(__file__).resolve().parent.parent),
    )
    config.SERVER_PID_FILE.write_text(str(proc.pid))

    if not _wait_for_port(host, port, timeout=3.0):
        print(f"❌ Server failed to start. Check: {config.SERVER_LOG_FILE}")
        if config.SERVER_LOG_FILE.exists():
            for line in config.SERVER_LOG_FILE.read_text().splitlines()[-10:]:
                print("   ", line)
        config.SERVER_PID_FILE.unlink(missing_ok=True)
        try:
            proc.terminate()
        except ProcessLookupError:
            pass
        return

    print(f"Serving {config.BASE_DIR}")
    print(f"Report:  {url}")
    print(f"PID:     {proc.pid}   (stop with: chronoshot.py serve --stop)")
    if host not in ("127.0.0.1", "localhost"):
        print("⚠️  Bound to a non-local address. Anyone on your network can view this.")
    if not args.no_open:
        webbrowser.open(url)


def cmd_server_daemon(args):
    """The hidden `_server` child — runs the HTTP loop until killed."""
    _server_loop(args.host, args.port)
