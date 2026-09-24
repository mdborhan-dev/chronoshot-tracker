"""The background loop that takes screenshots every interval."""

import html
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime

from . import config, shots


def ask_popup(filepath, info, interval):
    """Popup shown while tracking. Returns 'accept', 'reject' or 'later'."""
    if not shutil.which("yad"):
        return "later"
    preview = shots.make_preview(filepath, (480, 320))
    timeout = min(max(interval - 5, 10), 120)
    text = (
        f"<b>{html.escape(info['project'])}</b>   {info['time']}\nKeep this screenshot?"
    )
    try:
        rc = subprocess.run(
            [
                "yad",
                "--image",
                preview or str(filepath),
                "--text",
                text,
                "--button=Reject:1",
                "--button=Later:2",
                "--button=Accept:0",
                f"--timeout={timeout}",
                "--timeout-indicator=bottom",
                "--center",
                "--on-top",
                "--title=Chronoshot",
            ]
        ).returncode
    finally:
        shots.drop(preview)
    return {0: "accept", 1: "reject"}.get(rc, "later")


def daemon_loop(interval, project, mode):
    """Take a screenshot every `interval` seconds until stopped."""
    signal.signal(signal.SIGTERM, lambda signum, frame: sys.exit(0))
    signal.signal(signal.SIGINT, lambda signum, frame: sys.exit(0))
    from .util import ensure_dirs

    ensure_dirs()
    print(
        f"[{datetime.now():%F %T}] daemon started: project={project!r} "
        f"interval={interval}s mode={mode}",
        flush=True,
    )
    if mode == "ask" and not shutil.which("yad"):
        print("yad not found: screenshots will be kept for later review.", flush=True)

    next_run = time.monotonic()
    while True:
        now = datetime.now()
        name = shots.make_name(now, project)
        filepath = config.PENDING_DIR / name
        if shots.take_screenshot(filepath):
            info = shots.parse_name(name)
            if mode == "auto":
                choice = "accept"
            elif mode == "later":
                choice = "later"
            else:
                choice = ask_popup(filepath, info, interval)

            if choice == "accept":
                shutil.move(str(filepath), config.ACCEPTED_DIR / name)
                print(f"Accepted: {name}", flush=True)
            elif choice == "reject":
                filepath.unlink(missing_ok=True)
                print(f"Rejected: {name}", flush=True)
            else:
                print(f"Kept for review: {name}", flush=True)
        else:
            print(f"[{now}] Failed to take screenshot", flush=True)

        next_run += interval
        delay = next_run - time.monotonic()
        if delay < 0:
            next_run = time.monotonic()
            delay = 0
        time.sleep(delay)
