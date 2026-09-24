"""Small helpers used everywhere: folders, JSON, formatting, dates, daemon PID."""

import argparse
import json
import os
import re
from datetime import date, datetime, timedelta
from pathlib import Path

from . import config

DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def ensure_dirs():
    for d in [
        config.BASE_DIR,
        config.LOGS_DIR,
        config.PENDING_DIR,
        config.ACCEPTED_DIR,
        config.REPORTS_DIR,
    ]:
        d.mkdir(parents=True, exist_ok=True)


def read_json(path, default):
    try:
        return json.loads(Path(path).read_text())
    except FileNotFoundError:
        return default
    except (json.JSONDecodeError, OSError) as e:
        print(f"⚠️  Could not read {Path(path).name}: {e}")
        return default


def write_json(path, data):
    path = Path(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.replace(path)


def fmt_dur(seconds):
    seconds = int(round(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m:02d}m"
    if m:
        return f"{m}m {s:02d}s"
    return f"{s}s"


def parse_interval(text):
    """'30' or '30s' -> 30, '15m' -> 900, '1h' -> 3600."""
    m = re.fullmatch(r"\s*(\d+)\s*([smh]?)\s*", str(text).lower())
    if not m:
        raise argparse.ArgumentTypeError("use a number of seconds, or 30s / 15m / 1h")
    value = int(m.group(1)) * {"": 1, "s": 1, "m": 60, "h": 3600}[m.group(2)]
    if value < 5:
        raise argparse.ArgumentTypeError("interval must be at least 5 seconds")
    return value


def valid_day(text):
    if not DAY_RE.match(text):
        raise argparse.ArgumentTypeError("date must look like YYYY-MM-DD")
    try:
        datetime.strptime(text, "%Y-%m-%d")
    except ValueError:
        raise argparse.ArgumentTypeError("not a real date")
    return text


def resolve_range(args):
    """Turn --date / --last / --from / --to into (from, to) strings (either may be None)."""
    if getattr(args, "date", None):
        return args.date, args.date
    if getattr(args, "last", None):
        start = date.today() - timedelta(days=args.last - 1)
        return start.isoformat(), date.today().isoformat()
    return getattr(args, "from_", None), getattr(args, "to", None)


def daemon_pid():
    try:
        pid = int(config.PID_FILE.read_text().strip())
    except (FileNotFoundError, ValueError):
        return None
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        config.PID_FILE.unlink(missing_ok=True)
        return None
    except PermissionError:
        return pid
    return pid


def in_range(day, d_from, d_to):
    return not ((d_from and day < d_from) or (d_to and day > d_to))


def log_days():
    return sorted(
        p.stem for p in config.LOGS_DIR.glob("*.json") if DAY_RE.match(p.stem)
    )
