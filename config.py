"""Paths and default settings. Everything else imports from here."""

import os
from pathlib import Path

BASE_DIR = Path(
    os.environ.get("TIMETRACK_HOME", str(Path.home() / "timetrack"))
).expanduser()
LOGS_DIR = BASE_DIR / "logs"
PENDING_DIR = BASE_DIR / "screenshots" / "pending"
ACCEPTED_DIR = BASE_DIR / "screenshots" / "accepted"
REPORTS_DIR = BASE_DIR / "reports"
PID_FILE = BASE_DIR / "daemon.pid"
LOG_FILE = BASE_DIR / "daemon.log"
CURRENT_SESSION = BASE_DIR / "current_session.json"

DEFAULT_INTERVAL = 30  # seconds between screenshots
DEFAULT_MODE = "ask"  # ask | later | auto
