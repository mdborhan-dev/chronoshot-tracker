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
REPORT_FILE = REPORTS_DIR / "report.html"

DEFAULT_INTERVAL = 900  # 900 seconds/ 15 minutes between screenshots
DEFAULT_MODE = "ask"  # ask | later | auto

# Localhost report server (chronoshot serve).
# Override with env vars, e.g.
#   CHRONOSHOT_HOST=0.0.0.0 CHRONOSHOT_PORT=9000 chronoshot.py serve
SERVE_HOST = os.environ.get("CHRONOSHOT_HOST", "127.0.0.1")
SERVE_PORT = int(os.environ.get("CHRONOSHOT_PORT", "8000"))
SERVER_PID_FILE = BASE_DIR / "server.pid"
SERVER_LOG_FILE = BASE_DIR / "server.log"
