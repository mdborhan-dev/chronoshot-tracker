#!/usr/bin/env python3
"""
chronoshot - a small time tracker that takes periodic screenshots.

    chronoshot.py start -p "My Project"      start tracking (screenshot every 30s while testing)
    chronoshot.py switch "Other Project"     stop the current session and start a new project
    chronoshot.py stop                       stop and log the session
    chronoshot.py status                     what is running right now
    chronoshot.py review                     accept/reject pending screenshots (scoped by project/day)
    chronoshot.py report --open              ONE html page with every day, filters and charts
    chronoshot.py summary --last 7           quick totals in the terminal
    chronoshot.py delete FILE...             delete screenshots by file name

Data lives in ~/timetrack (same place as the old script, so old logs still work).
Set TIMETRACK_HOME=/some/dir to use a separate folder, handy for testing.
"""
import argparse
import base64
import html
import io
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import webbrowser
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import quote, unquote

# ----------------------------------------------------------------------------
# Settings
# ----------------------------------------------------------------------------
BASE_DIR = Path(os.environ.get("TIMETRACK_HOME", str(Path.home() / "timetrack"))).expanduser()
LOGS_DIR = BASE_DIR / "logs"
PENDING_DIR = BASE_DIR / "screenshots" / "pending"
ACCEPTED_DIR = BASE_DIR / "screenshots" / "accepted"
REPORTS_DIR = BASE_DIR / "reports"
PID_FILE = BASE_DIR / "daemon.pid"
LOG_FILE = BASE_DIR / "daemon.log"
CURRENT_SESSION = BASE_DIR / "current_session.json"

DEFAULT_INTERVAL = 30  # seconds. Testing value: change to 900 (15 min) when you are happy.
DEFAULT_MODE = "ask"   # ask = popup on every screenshot, later = keep all for review, auto = accept all

FILE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})_(\d{6})(?:__(.+))?\.png$")
DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# ----------------------------------------------------------------------------
# Small helpers
# ----------------------------------------------------------------------------
def ensure_dirs():
    for d in [BASE_DIR, LOGS_DIR, PENDING_DIR, ACCEPTED_DIR, REPORTS_DIR]:
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
        pid = int(PID_FILE.read_text().strip())
    except (FileNotFoundError, ValueError):
        return None
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        PID_FILE.unlink(missing_ok=True)
        return None
    except PermissionError:
        return pid
    return pid


# ----------------------------------------------------------------------------
# Screenshot files. The project is part of the file name, so review/report can
# filter by project and day without any extra database:
#   2026-09-24_153012__My%20Project.png
# Old files without "__project" are treated as project "Default".
# ----------------------------------------------------------------------------
def make_name(ts, project):
    return f"{ts:%Y-%m-%d_%H%M%S}__{quote(project, safe='')}.png"


def parse_name(name):
    m = FILE_RE.match(name)
    if not m:
        return None
    day, hms, proj = m.groups()
    return {
        "name": name,
        "date": day,
        "time": f"{hms[:2]}:{hms[2:4]}:{hms[4:]}",
        "sec": int(hms[:2]) * 3600 + int(hms[2:4]) * 60 + int(hms[4:]),
        "project": unquote(proj) if proj else "Default",
    }


def list_shots(folder, day=None, project=None):
    out = []
    for p in sorted(Path(folder).glob("*.png")):
        info = parse_name(p.name)
        if not info:
            continue
        if day and info["date"] != day:
            continue
        if project and info["project"].lower() != project.lower():
            continue
        info["path"] = p
        out.append(info)
    return out


def take_screenshot(filepath):
    """Try KDE's spectacle first, then fall back to others."""
    filepath = str(filepath)
    commands = [
        ["spectacle", "-b", "-n", "-o", filepath],  # KDE
        ["gnome-screenshot", "-f", filepath],
        ["grim", filepath],  # wlroots Wayland
        ["scrot", filepath],
    ]
    for cmd in commands:
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
            if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
                return True
        except FileNotFoundError:
            continue
        except subprocess.CalledProcessError as e:
            print(f"❌ {cmd[0]} failed: {e.stderr}", flush=True)
    return False


def make_preview(src, size):
    """Small temp copy of an image for popups. Returns a path or None (needs Pillow)."""
    try:
        from PIL import Image
    except ImportError:
        return None
    try:
        fd, tmp = tempfile.mkstemp(suffix=".png", prefix="chronoshot_")
        os.close(fd)
        with Image.open(src) as img:
            img.thumbnail(size)
            img.save(tmp)
        return tmp
    except Exception:
        return None


def drop(path):
    if path:
        try:
            os.unlink(path)
        except OSError:
            pass


# ----------------------------------------------------------------------------
# Background daemon
# ----------------------------------------------------------------------------
def ask_popup(filepath, info, interval):
    """Popup shown while tracking. Returns 'accept', 'reject' or 'later'."""
    if not shutil.which("yad"):
        return "later"
    preview = make_preview(filepath, (480, 320))
    timeout = min(max(interval - 5, 10), 120)  # never block longer than the interval allows
    text = f"<b>{html.escape(info['project'])}</b>   {info['time']}\nKeep this screenshot?"
    try:
        rc = subprocess.run(
            [
                "yad", "--image", preview or str(filepath), "--text", text,
                "--button=Reject:1", "--button=Later:2", "--button=Accept:0",
                f"--timeout={timeout}", "--timeout-indicator=bottom",
                "--center", "--on-top", "--title=Chronoshot",
            ]
        ).returncode
    finally:
        drop(preview)
    return {0: "accept", 1: "reject"}.get(rc, "later")  # timeout / closed window -> later


def daemon_loop(interval, project, mode):
    """Take a screenshot every `interval` seconds until stopped."""
    signal.signal(signal.SIGTERM, lambda signum, frame: sys.exit(0))
    signal.signal(signal.SIGINT, lambda signum, frame: sys.exit(0))
    ensure_dirs()
    print(f"[{datetime.now():%F %T}] daemon started: project={project!r} interval={interval}s mode={mode}", flush=True)
    if mode == "ask" and not shutil.which("yad"):
        print("yad not found: screenshots will be kept for later review.", flush=True)

    next_run = time.monotonic()
    while True:
        now = datetime.now()
        name = make_name(now, project)
        filepath = PENDING_DIR / name
        if take_screenshot(filepath):
            info = parse_name(name)
            if mode == "auto":
                choice = "accept"
            elif mode == "later":
                choice = "later"
            else:
                choice = ask_popup(filepath, info, interval)

            if choice == "accept":
                shutil.move(str(filepath), ACCEPTED_DIR / name)
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
        if delay < 0:  # a popup ran long; do not try to catch up
            next_run = time.monotonic()
            delay = 0
        time.sleep(delay)


# ----------------------------------------------------------------------------
# start / stop / switch / status
# ----------------------------------------------------------------------------
def do_start(project, interval, mode, note="", verbose=False):
    ensure_dirs()
    if daemon_pid():
        print("Tracking already running. Use 'switch' to change project, or 'stop' first.")
        return False
    if CURRENT_SESSION.exists():
        s = read_json(CURRENT_SESSION, {})
        print(
            f"⚠️  An unfinished session exists ({s.get('project', '?')}, started {s.get('start', '?')}) "
            "but nothing is running.\n   Run 'stop' first (or 'stop --at HH:MM' to set when it really ended)."
        )
        return False

    write_json(
        CURRENT_SESSION,
        {
            "start": datetime.now().isoformat(timespec="seconds"),
            "project": project,
            "note": note or "",
            "interval": interval,
            "mode": mode,
        },
    )
    cmd = [sys.executable, str(Path(__file__).resolve()), "_daemon", str(interval),
           "--project", project, "--mode", mode]
    if verbose:
        proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, start_new_session=True)
    else:
        log = open(LOG_FILE, "a")
        proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
    PID_FILE.write_text(str(proc.pid))

    mode_text = {"ask": "popup asks on each screenshot",
                 "later": "screenshots wait for 'review'",
                 "auto": "screenshots are accepted automatically"}[mode]
    print(f"Tracking started (PID {proc.pid}). Project: {project}")
    print(f"Screenshot every {fmt_dur(interval)}; {mode_text}.")
    if mode == "ask" and not shutil.which("yad"):
        print("Note: 'yad' is not installed, so screenshots will wait for 'review' instead.")
    return True


def parse_at(text, start):
    try:
        t = datetime.strptime(text, "%H:%M").time()
    except ValueError:
        raise SystemExit("--at must look like HH:MM, for example 17:30")
    end = datetime.combine(date.today(), t)
    if end < start:
        end = datetime.combine(start.date(), t)
    if end < start:
        raise SystemExit("--at is earlier than the session start")
    return end


def do_stop(note="", at=None):
    ensure_dirs()
    if not CURRENT_SESSION.exists():
        print("No active session.")
        return None
    pid = daemon_pid()
    if pid:
        try:
            os.kill(pid, signal.SIGTERM)
            print("Daemon stopped.")
        except ProcessLookupError:
            pass
    PID_FILE.unlink(missing_ok=True)

    data = read_json(CURRENT_SESSION, None)
    if not data:
        CURRENT_SESSION.unlink(missing_ok=True)
        print("Session file was unreadable and has been discarded.")
        return None

    start = datetime.fromisoformat(data["start"])
    end = parse_at(at, start) if at else datetime.now()
    duration = (end - start).total_seconds()
    notes = " / ".join(n for n in [data.get("note", ""), note] if n)

    session = {
        "start": start.isoformat(timespec="seconds"),
        "end": end.isoformat(timespec="seconds"),
        "duration": duration,
        "project": data.get("project", "Default"),
        "note": notes,
    }
    log_file = LOGS_DIR / f"{start:%Y-%m-%d}.json"
    sessions = read_json(log_file, [])
    sessions.append(session)
    write_json(log_file, sessions)
    CURRENT_SESSION.unlink(missing_ok=True)

    print(f"Session logged: {start:%H:%M} - {end:%H:%M} ({fmt_dur(duration)}) [Project: {session['project']}]")
    left = len(list_shots(PENDING_DIR, project=session["project"]))
    if left:
        print(f"{left} screenshot(s) still waiting: chronoshot.py review --project \"{session['project']}\"")
    return session


def cmd_start(args):
    project = args.project or args.project_pos or "Default"
    do_start(project, args.interval, args.mode, args.note, args.verbose)


def cmd_stop(args):
    do_stop(args.note or "", args.at)


def cmd_switch(args):
    current = read_json(CURRENT_SESSION, {}) if CURRENT_SESSION.exists() else {}
    interval = args.interval or current.get("interval") or DEFAULT_INTERVAL
    mode = args.mode or current.get("mode") or DEFAULT_MODE
    if CURRENT_SESSION.exists():
        do_stop()
    do_start(args.project, interval, mode, args.note, args.verbose)


def cmd_status(args):
    ensure_dirs()
    pid = daemon_pid()
    data = read_json(CURRENT_SESSION, None) if CURRENT_SESSION.exists() else None
    if pid and data:
        start = datetime.fromisoformat(data["start"])
        elapsed = (datetime.now() - start).total_seconds()
        print(f"Tracking is running (PID {pid}).")
        print(f"  Project:  {data.get('project', 'Default')}")
        print(f"  Started:  {start:%Y-%m-%d %H:%M:%S} ({fmt_dur(elapsed)} ago)")
        print(f"  Interval: {fmt_dur(data.get('interval', DEFAULT_INTERVAL))}, mode: {data.get('mode', DEFAULT_MODE)}")
        if data.get("note"):
            print(f"  Note:     {data['note']}")
    elif data:
        print(f"Not running, but an unfinished session is on file ({data.get('project')}, started {data.get('start')}).")
        print("Run 'stop' (optionally 'stop --at HH:MM') to log it.")
    else:
        print("Tracking is not running.")

    today = date.today().isoformat()
    pending = list_shots(PENDING_DIR)
    print(f"Today: {len(list_shots(ACCEPTED_DIR, day=today))} accepted, "
          f"{len(list_shots(PENDING_DIR, day=today))} pending. Pending overall: {len(pending)}.")
    per = defaultdict(int)
    for it in pending:
        per[(it["date"], it["project"])] += 1
    for (d, p), n in sorted(per.items(), reverse=True)[:8]:
        print(f"    {d}  {p}: {n} pending")


# ----------------------------------------------------------------------------
# Review
# ----------------------------------------------------------------------------
def choose_scope(pending, args):
    """Decide which pending screenshots to review. Returns (items, label) or None."""
    if args.all:
        return pending, "everything"

    day = args.date or (date.today().isoformat() if args.today else None)
    if day or args.project:
        items, label = pending, []
        if day:
            items = [i for i in items if i["date"] == day]
            label.append(day)
        if args.project:
            items = [i for i in items if i["project"].lower() == args.project.lower()]
            label.append(f"project {args.project}")
        return items, ", ".join(label)

    groups = defaultdict(list)
    for it in pending:
        groups[(it["date"], it["project"])].append(it)
    keys = sorted(groups, reverse=True)
    if len(keys) == 1:
        k = keys[0]
        return groups[k], f"{k[0]}, project {k[1]}"

    print("Pending screenshots:")
    for n, k in enumerate(keys, 1):
        print(f"  {n}. {k[0]}   {k[1]}   ({len(groups[k])})")
    print(f"  {len(keys) + 1}. everything ({len(pending)})")
    while True:
        try:
            ans = input("Review which one? [1, or q to quit] ").strip().lower() or "1"
        except (EOFError, KeyboardInterrupt):
            return None
        if ans in ("q", "quit"):
            return None
        if ans.isdigit() and 1 <= int(ans) <= len(keys):
            k = keys[int(ans) - 1]
            return groups[k], f"{k[0]}, project {k[1]}"
        if ans.isdigit() and int(ans) == len(keys) + 1:
            return pending, "everything"
        print("Type one of the numbers above.")


def decide_gui(it, i, n):
    preview = make_preview(it["path"], (1100, 700))
    text = f"<b>{html.escape(it['project'])}</b>   {it['date']} {it['time']}\nScreenshot {i} of {n}"
    try:
        rc = subprocess.run(
            [
                "yad", "--image", preview or str(it["path"]), "--text", text,
                "--button=Quit:3", "--button=Skip:2", "--button=Reject:1", "--button=Accept:0",
                "--center", "--title=Chronoshot review",
            ]
        ).returncode
    finally:
        drop(preview)
    return {0: "a", 1: "r", 2: "s"}.get(rc, "q")  # closing the window quits


def open_viewer(path):
    try:
        subprocess.Popen(["xdg-open", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except FileNotFoundError:
        print("  xdg-open not found, open this file yourself:", path)


def decide_terminal(it, i, n):
    print(f"\n[{i}/{n}] {it['date']} {it['time']}   project: {it['project']}")
    print(f"      {it['path']}")
    open_viewer(it["path"])
    while True:
        try:
            ans = input("  a=accept  r=reject  s=skip  o=reopen  q=quit  A=accept rest  R=reject rest > ").strip()
        except (EOFError, KeyboardInterrupt):
            return "q"
        if ans in ("A", "R"):
            if ans == "R" and input("  Delete ALL remaining in this batch? [y/N] ").strip().lower() != "y":
                continue
            return ans
        ans = ans.lower()
        if ans == "o":
            open_viewer(it["path"])
        elif ans in ("a", "r", "s", "q"):
            return ans
        else:
            print("  Type a, r, s, o or q.")


def cmd_review(args):
    ensure_dirs()
    pending = list_shots(PENDING_DIR)
    if not pending:
        print("No pending screenshots.")
        return
    scope = choose_scope(pending, args)
    if scope is None:
        return
    items, label = scope
    other = len(pending) - len(items)
    if not items:
        print(f"No pending screenshots for {label}. ({other} pending elsewhere: try 'review' with no options.)")
        return

    use_gui = bool(shutil.which("yad")) and not args.terminal
    print(f"Reviewing {len(items)} screenshot(s): {label}" + (f"   ({other} more pending elsewhere)" if other else ""))
    if not use_gui and not args.terminal:
        print("(yad not installed, using terminal mode)")

    counts = {"a": 0, "r": 0, "s": 0}
    bulk = None
    for i, it in enumerate(items, 1):
        action = bulk or (decide_gui(it, i, len(items)) if use_gui else decide_terminal(it, i, len(items)))
        if action in ("A", "R"):
            bulk = action
            action = action.lower()
        if action == "q":
            print("Stopped. The rest stay pending.")
            break
        if action == "a":
            shutil.move(str(it["path"]), ACCEPTED_DIR / it["name"])
        elif action == "r":
            it["path"].unlink(missing_ok=True)
        counts[action] += 1
    print(f"Done: {counts['a']} accepted, {counts['r']} rejected, {counts['s']} skipped.")


# ----------------------------------------------------------------------------
# Data for summary / report
# ----------------------------------------------------------------------------
def log_days():
    return sorted(p.stem for p in LOGS_DIR.glob("*.json") if DAY_RE.match(p.stem))


def norm_session(s, running=False):
    st = datetime.fromisoformat(s["start"])
    en = datetime.fromisoformat(s["end"])
    base = datetime.combine(st.date(), datetime.min.time())
    end_label = en.strftime("%H:%M:%S")
    if en.date() != st.date():
        end_label += f" (+{(en.date() - st.date()).days}d)"
    return {
        "project": s.get("project", "Default"),
        "note": s.get("note", ""),
        "start": st.strftime("%H:%M:%S"),
        "end": end_label,
        "startSec": int((st - base).total_seconds()),
        "endSec": int((en - base).total_seconds()),
        "duration": round(float(s.get("duration", (en - st).total_seconds())), 1),
        "running": running,
    }


def in_range(day, d_from, d_to):
    return not ((d_from and day < d_from) or (d_to and day > d_to))


def embed_image(path):
    """Self-contained copy of a screenshot (JPEG, max 1600px when Pillow is available)."""
    try:
        from PIL import Image

        with Image.open(path) as img:
            img = img.convert("RGB")
            img.thumbnail((1600, 1600))
            buf = io.BytesIO()
            img.save(buf, "JPEG", quality=80)
        return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return "data:image/png;base64," + base64.b64encode(Path(path).read_bytes()).decode()


def collect_report_data(d_from, d_to, project, embed, base_dir):
    days = {}

    def bucket(d):
        return days.setdefault(d, {"date": d, "sessions": [], "shots": []})

    def keep_project(p):
        return not project or p.lower() == project.lower()

    for day in log_days():
        if not in_range(day, d_from, d_to):
            continue
        for s in read_json(LOGS_DIR / f"{day}.json", []):
            try:
                n = norm_session(s)
            except (KeyError, ValueError):
                continue
            if keep_project(n["project"]):
                bucket(day)["sessions"].append(n)

    live = read_json(CURRENT_SESSION, None) if daemon_pid() else None
    if live:
        try:
            st = datetime.fromisoformat(live["start"])
            now = datetime.now()
            n = norm_session(
                {"start": live["start"], "end": now.isoformat(timespec="seconds"),
                 "duration": (now - st).total_seconds(), "project": live.get("project", "Default"),
                 "note": live.get("note", "")},
                running=True,
            )
            day = st.strftime("%Y-%m-%d")
            if in_range(day, d_from, d_to) and keep_project(n["project"]):
                bucket(day)["sessions"].append(n)
        except (KeyError, ValueError):
            pass

    for it in list_shots(ACCEPTED_DIR):
        if not in_range(it["date"], d_from, d_to) or not keep_project(it["project"]):
            continue
        if embed:
            src = embed_image(it["path"])
        else:
            rel = os.path.relpath(it["path"], base_dir).replace(os.sep, "/")
            src = quote(rel, safe="/")
        bucket(it["date"])["shots"].append(
            {"name": it["name"], "time": it["time"], "sec": it["sec"], "project": it["project"], "src": src}
        )

    out = []
    for day in sorted(days):
        b = days[day]
        b["sessions"].sort(key=lambda s: s["startSec"])
        b["shots"].sort(key=lambda s: s["sec"])
        if b["sessions"] or b["shots"]:
            out.append(b)
    projects = sorted({s["project"] for d in out for s in d["sessions"]} | {x["project"] for d in out for x in d["shots"]})
    return {
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "days": out,
        "projects": projects,
        "minDate": out[0]["date"] if out else "",
        "maxDate": out[-1]["date"] if out else "",
    }


def cmd_summary(args):
    ensure_dirs()
    d_from, d_to = resolve_range(args)
    per_day = defaultdict(lambda: defaultdict(float))
    for day in log_days():
        if not in_range(day, d_from, d_to):
            continue
        for s in read_json(LOGS_DIR / f"{day}.json", []):
            p = s.get("project", "Default")
            if args.project and p.lower() != args.project.lower():
                continue
            per_day[day][p] += float(s.get("duration", 0))
    if not per_day:
        print("No sessions logged for that range.")
        return
    grand = defaultdict(float)
    for day in sorted(per_day):
        total = sum(per_day[day].values())
        shots = len(list_shots(ACCEPTED_DIR, day=day))
        print(f"{day}   {fmt_dur(total):>9}   {shots} screenshot(s)")
        for p, v in sorted(per_day[day].items(), key=lambda kv: -kv[1]):
            print(f"    {p:<28} {fmt_dur(v):>9}")
            grand[p] += v
    print("\nTotals by project:")
    for p, v in sorted(grand.items(), key=lambda kv: -kv[1]):
        print(f"    {p:<28} {fmt_dur(v):>9}")
    print(f"    {'All projects':<28} {fmt_dur(sum(grand.values())):>9}")


def cmd_delete(args):
    ensure_dirs()
    for raw in args.filenames:
        name = Path(raw).name
        for folder in (ACCEPTED_DIR, PENDING_DIR):
            f = folder / name
            if f.exists():
                f.unlink()
                print(f"Deleted {name}")
                break
        else:
            print(f"File {name} not found.")


# ----------------------------------------------------------------------------
# Report: one page, every day, filters done in the browser
# ----------------------------------------------------------------------------
REPORT_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en" data-theme="auto">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
:root{
  color-scheme:light;
  --bg:#eceee9; --panel:#f8f9f6; --ink:#182126; --muted:#5b686e; --line:#d2d8d1;
  --accent:#2350d8; --accent-soft:#dbe4fa; --track:#dde2db;
  --serif:"Iowan Old Style","Palatino Linotype",Palatino,Georgia,serif;
  --sans:system-ui,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;
  --thumb:260px;
}
:root[data-theme="dark"]{
  color-scheme:dark;
  --bg:#11161a; --panel:#182027; --ink:#e6ebed; --muted:#93a1a8; --line:#28343b;
  --accent:#7ea0ff; --accent-soft:#233052; --track:#232d34;
}
@media (prefers-color-scheme:dark){
  :root[data-theme="auto"]{
    color-scheme:dark;
    --bg:#11161a; --panel:#182027; --ink:#e6ebed; --muted:#93a1a8; --line:#28343b;
    --accent:#7ea0ff; --accent-soft:#233052; --track:#232d34;
  }
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 var(--sans);font-variant-numeric:tabular-nums}
button,input,select{font:inherit;color:inherit}
button{cursor:pointer}
:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.app{display:grid;grid-template-columns:290px minmax(0,1fr);gap:44px;max-width:1440px;margin:0 auto;padding:28px 28px 72px}
aside{position:sticky;top:20px;align-self:start;max-height:calc(100vh - 40px);overflow:auto;padding-right:8px}
.brand h1{font:600 30px/1.1 var(--serif);margin:0 0 4px}
.brand p{margin:0;color:var(--muted);font-size:13px}
.actions{display:flex;flex-wrap:wrap;gap:6px;margin-top:14px}
.btn{border:1px solid var(--line);background:var(--panel);border-radius:6px;padding:5px 11px;font-size:13px}
.btn:hover{border-color:var(--muted)}
.group{margin-top:24px}
.group h3{font:600 13px/1.2 var(--sans);margin:0 0 9px;color:var(--muted)}
.chips{display:flex;flex-wrap:wrap;gap:6px}
.chips button{border:1px solid var(--line);background:transparent;border-radius:999px;padding:4px 11px;font-size:13px}
.chips button[aria-pressed="true"]{background:var(--ink);color:var(--bg);border-color:var(--ink)}
.row2{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:10px}
label.f{display:flex;flex-direction:column;gap:3px;font-size:12px;color:var(--muted)}
input[type=date],input[type=search],select{background:var(--panel);border:1px solid var(--line);border-radius:6px;padding:6px 8px;width:100%}
input[type=range]{width:100%;accent-color:var(--accent)}
.check{display:flex;align-items:center;gap:8px;font-size:14px;margin-bottom:10px}
.proj{display:block;width:100%;text-align:left;background:transparent;border:0;border-radius:6px;padding:7px 8px;margin-bottom:2px}
.proj:hover{background:var(--panel)}
.proj.on{background:var(--accent-soft)}
.pl{display:flex;align-items:center;gap:8px}
.pn{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.pt{color:var(--muted);font-size:13px}
.pbar{display:block;height:3px;background:var(--track);border-radius:2px;margin-top:5px;overflow:hidden}
.pbar i{display:block;height:100%}
.dot{display:inline-block;width:9px;height:9px;border-radius:50%;flex:none}
.lead{font:400 32px/1.2 var(--serif);margin:0 0 6px}
.sub{margin:0;color:var(--muted)}
.chart{margin:26px 0 10px;border:1px solid var(--line);border-radius:10px;background:var(--panel);padding:16px 18px 12px}
.chart h2{font:600 15px var(--sans);margin:0 0 12px}
.bars{display:flex;gap:10px;overflow-x:auto;padding-bottom:6px}
.col{flex:1 0 50px;max-width:96px;display:flex;flex-direction:column;align-items:center;gap:4px}
.val{font-size:11px;color:var(--muted);white-space:nowrap}
.barwrap{height:130px;width:100%;display:flex;align-items:flex-end}
.bar{width:100%;display:flex;flex-direction:column-reverse;min-height:2px;border-radius:4px 4px 0 0;overflow:hidden}
.bseg{min-height:1px}
.lbl{font-size:11px;color:var(--muted)}
.empty{color:var(--muted);margin:8px 0}
.day{border-top:1px solid var(--line);padding:18px 0 14px}
.day>summary{list-style:none;display:flex;align-items:center;gap:12px;cursor:pointer}
.day>summary::-webkit-details-marker{display:none}
.day>summary::before{content:"";flex:none;width:7px;height:7px;border-right:2px solid var(--muted);border-bottom:2px solid var(--muted);transform:rotate(-45deg);transition:transform .15s}
.day[open]>summary::before{transform:rotate(45deg)}
.dname{flex:1}
.dname b{font:600 22px var(--serif)}
.dname span{color:var(--muted);margin-left:8px;font-size:14px}
.dtot{font:600 20px var(--serif)}
.dchips{display:flex;flex-wrap:wrap;gap:6px;margin:10px 0 0 19px}
.chip{display:inline-flex;align-items:center;gap:6px;font-size:12.5px;border:1px solid var(--line);border-radius:999px;padding:1px 10px}
.stripwrap{position:relative;margin:20px 0 38px 19px}
.strip{position:relative;height:26px;background:var(--track);border-radius:6px}
.strip .seg{position:absolute;top:0;bottom:0;border-radius:4px;opacity:.93}
.strip .pin{position:absolute;top:-6px;width:10px;height:10px;margin-left:-5px;border-radius:50%;background:var(--ink);border:2px solid var(--panel);padding:0;cursor:pointer}
.tick{position:absolute;top:32px;transform:translateX(-50%);font-size:11px;color:var(--muted)}
.sessions{width:calc(100% - 19px);margin:0 0 18px 19px;border-collapse:collapse;font-size:14px}
.sessions td{padding:6px 12px 6px 0;border-bottom:1px solid var(--line);vertical-align:top}
.sessions .t{white-space:nowrap}
.sessions .n{width:100%;color:var(--muted)}
.live{margin-left:8px;color:var(--accent);font-size:12px}
.shots{display:grid;grid-template-columns:repeat(auto-fill,minmax(var(--thumb),1fr));gap:12px;margin-left:19px}
.shots figure{margin:0;border:1px solid var(--line);border-radius:8px;overflow:hidden;background:var(--panel);cursor:zoom-in}
.shots img{display:block;width:100%;aspect-ratio:16/10;object-fit:cover;background:var(--track)}
.shots figcaption{display:flex;justify-content:space-between;align-items:center;gap:8px;padding:6px 9px;font-size:12px;color:var(--muted)}
.lb{position:fixed;inset:0;z-index:50;background:rgba(8,10,12,.93);display:flex;flex-direction:column;align-items:center;justify-content:center;padding:20px;gap:12px}
.lb[hidden]{display:none}
.lb img{max-width:100%;max-height:calc(100vh - 120px);object-fit:contain;border-radius:4px}
.lbbar{display:flex;flex-wrap:wrap;gap:8px;align-items:center;justify-content:center;color:#dfe6e9;font-size:13px}
.lbbar button,.lbbar a{color:#dfe6e9;background:transparent;border:1px solid #4a565c;border-radius:6px;padding:4px 12px;text-decoration:none;font-size:13px}
.noscroll{overflow:hidden}
@media (max-width:900px){
  .app{grid-template-columns:1fr;gap:20px;padding:16px}
  aside{position:static;max-height:none}
  .lead{font-size:26px}
}
@media print{
  aside,.lb{display:none!important}
  .app{display:block;padding:0}
  body{background:#fff;color:#000}
  .shots{grid-template-columns:repeat(3,1fr)}
  .shots figure,.day>summary{break-inside:avoid}
}
</style>
</head>
<body>
<div class="app">
  <aside>
    <div class="brand">
      <h1>Time report</h1>
      <p id="gen"></p>
      <div class="actions">
        <button class="btn" id="btnTheme" type="button">Theme: auto</button>
        <button class="btn" id="btnCsv" type="button">Export CSV</button>
        <button class="btn" id="btnPrint" type="button">Print</button>
      </div>
    </div>

    <div class="group">
      <h3>Date range</h3>
      <div class="chips" id="ranges">
        <button type="button" data-r="today">Today</button>
        <button type="button" data-r="7">Last 7 days</button>
        <button type="button" data-r="30">Last 30 days</button>
        <button type="button" data-r="all">All time</button>
      </div>
      <div class="row2">
        <label class="f">From<input type="date" id="from"></label>
        <label class="f">To<input type="date" id="to"></label>
      </div>
    </div>

    <div class="group">
      <h3>Project</h3>
      <div id="projList"></div>
    </div>

    <div class="group">
      <h3>Search project or note</h3>
      <input type="search" id="q" placeholder="Type to filter">
    </div>

    <div class="group">
      <h3>Display</h3>
      <label class="check"><input type="checkbox" id="showShots" checked> Show screenshots</label>
      <label class="f">Screenshot size<input type="range" id="size" min="140" max="520" step="10" value="260"></label>
      <label class="f" style="margin-top:10px">Day order
        <select id="order"><option value="desc">Newest first</option><option value="asc">Oldest first</option></select>
      </label>
      <div class="actions">
        <button class="btn" id="expand" type="button">Expand all days</button>
        <button class="btn" id="collapse" type="button">Collapse all days</button>
      </div>
    </div>
  </aside>

  <main>
    <div id="summary"></div>
    <section class="chart" id="chartBox"><h2>Time per day</h2><div id="daily"></div></section>
    <div id="days"></div>
  </main>
</div>

<div class="lb" id="lb" hidden>
  <img id="lbImg" alt="Screenshot">
  <div class="lbbar">
    <button type="button" id="lbPrev">Previous</button>
    <span id="lbCap"></span>
    <button type="button" id="lbNext">Next</button>
    <a id="lbOpen" target="_blank" rel="noopener">Open original</a>
    <button type="button" id="lbClose">Close</button>
  </div>
</div>

<script>
(function () {
  'use strict';
  const D = __DATA__;
  const S = { range: 'all', from: '', to: '', project: '', q: '', shots: true, order: 'desc' };
  const VIS = [];
  const $ = (s) => document.querySelector(s);
  const pad = (n) => String(n).padStart(2, '0');

  function el(tag, props) {
    const e = document.createElement(tag);
    if (props) {
      for (const k in props) {
        const v = props[k];
        if (k === 'class') e.className = v;
        else if (k === 'style') e.style.cssText = v;
        else if (k.slice(0, 2) === 'on') e.addEventListener(k.slice(2), v);
        else if (v !== false && v !== null && v !== undefined) e.setAttribute(k, v === true ? '' : v);
      }
    }
    for (const c of Array.prototype.slice.call(arguments, 2).flat()) {
      if (c === null || c === undefined || c === false) continue;
      e.append(c.nodeType ? c : document.createTextNode(String(c)));
    }
    return e;
  }
  function fmtDur(sec) {
    sec = Math.round(sec);
    const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
    if (h) return h + 'h ' + pad(m) + 'm';
    if (m) return m + 'm ' + pad(s) + 's';
    return s + 's';
  }
  function color(name) {
    let h = 7;
    for (const c of name) h = (h * 131 + c.charCodeAt(0)) >>> 0;
    return 'hsl(' + (h % 360) + ' 60% 50%)';
  }
  function iso(d) { return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()); }
  function niceDate(s) {
    const d = new Date(s + 'T00:00:00');
    return {
      dow: d.toLocaleDateString(undefined, { weekday: 'long' }),
      rest: d.toLocaleDateString(undefined, { day: 'numeric', month: 'long', year: 'numeric' })
    };
  }
  const plural = (n, w) => n + ' ' + w + (n === 1 ? '' : 's');
  const total = (ss) => ss.reduce((a, s) => a + s.duration, 0);
  function byProject(ss) {
    const o = {};
    for (const s of ss) o[s.project] = (o[s.project] || 0) + s.duration;
    return o;
  }
  const chip = (p, extra) => el('span', { class: 'chip' }, el('i', { class: 'dot', style: 'background:' + color(p) }), p + (extra ? ' ' + extra : ''));

  function filtered(skipProject) {
    const q = S.q.trim().toLowerCase();
    const out = [];
    for (const day of D.days) {
      if (S.from && day.date < S.from) continue;
      if (S.to && day.date > S.to) continue;
      const okP = (p) => skipProject || !S.project || p === S.project;
      const sessions = day.sessions.filter((s) => okP(s.project) && (!q || (s.project + ' ' + (s.note || '')).toLowerCase().includes(q)));
      const shots = day.shots.filter((x) => okP(x.project) && (!q || x.project.toLowerCase().includes(q)));
      if (sessions.length || shots.length) out.push({ date: day.date, sessions: sessions, shots: shots });
    }
    out.sort((a, b) => (S.order === 'asc' ? a.date.localeCompare(b.date) : b.date.localeCompare(a.date)));
    return out;
  }

  function renderSummary(days) {
    const box = $('#summary');
    box.replaceChildren();
    if (!days.length) {
      box.append(el('p', { class: 'lead' }, 'Nothing matches these filters.'),
        el('p', { class: 'sub' }, D.days.length ? 'Widen the date range or choose All projects.' : 'No sessions or accepted screenshots yet. Run start, then stop, then report again.'));
      return;
    }
    const sess = days.flatMap((d) => d.sessions);
    const shots = days.reduce((a, d) => a + d.shots.length, 0);
    const tot = total(sess);
    const active = days.filter((d) => d.sessions.length).length;
    const projs = Object.keys(byProject(sess)).length;
    box.append(el('p', { class: 'lead' }, tot ? fmtDur(tot) + ' tracked over ' + plural(active, 'day') + ' on ' + plural(projs, 'project') + '.' : 'No sessions in this range.'));
    const bits = [plural(sess.length, 'session'), plural(shots, 'accepted screenshot')];
    if (active) {
      const longest = days.filter((d) => d.sessions.length).reduce((a, b) => (total(b.sessions) > total(a.sessions) ? b : a));
      bits.push('average ' + fmtDur(tot / active) + ' per active day');
      bits.push('longest day ' + longest.date + ' (' + fmtDur(total(longest.sessions)) + ')');
    }
    box.append(el('p', { class: 'sub' }, bits.join(', ') + '.'));
  }

  function renderDaily(days) {
    const box = $('#daily');
    box.replaceChildren();
    const asc = days.filter((d) => total(d.sessions) > 0).sort((a, b) => a.date.localeCompare(b.date));
    $('#chartBox').style.display = asc.length ? '' : 'none';
    if (!asc.length) return;
    const max = Math.max.apply(null, asc.map((d) => total(d.sessions)));
    box.append(el('div', { class: 'bars' }, asc.map((d) => {
      const tot = total(d.sessions);
      const segs = Object.entries(byProject(d.sessions)).sort((a, b) => b[1] - a[1]).map((e) =>
        el('span', { class: 'bseg', style: 'flex:' + e[1] + ' 1 0px;background:' + color(e[0]), title: e[0] + ': ' + fmtDur(e[1]) }));
      return el('div', { class: 'col' },
        el('div', { class: 'val' }, fmtDur(tot)),
        el('div', { class: 'barwrap' }, el('div', { class: 'bar', style: 'height:' + (tot / max * 100) + '%', title: d.date + ': ' + fmtDur(tot) }, segs)),
        el('div', { class: 'lbl' }, d.date.slice(5)));
    })));
  }

  function projBtn(value, label, secs, share, col) {
    return el('button', { class: 'proj' + (S.project === value ? ' on' : ''), type: 'button', 'aria-pressed': S.project === value ? 'true' : 'false',
      onclick: function () { S.project = value; update(); } },
      el('span', { class: 'pl' }, el('i', { class: 'dot', style: 'background:' + col }), el('span', { class: 'pn' }, label), el('span', { class: 'pt' }, fmtDur(secs))),
      el('span', { class: 'pbar' }, el('i', { style: 'width:' + (share * 100) + '%;background:' + col })));
  }
  function renderProjects() {
    const days = filtered(true);
    const by = byProject(days.flatMap((d) => d.sessions));
    for (const d of days) for (const x of d.shots) if (!(x.project in by)) by[x.project] = 0;
    if (S.project && !(S.project in by)) by[S.project] = 0;
    const tot = Object.values(by).reduce((a, b) => a + b, 0);
    const box = $('#projList');
    box.replaceChildren(projBtn('', 'All projects', tot, 1, 'var(--muted)'));
    Object.entries(by).sort((a, b) => b[1] - a[1]).forEach((e) => box.append(projBtn(e[0], e[0], e[1], tot ? e[1] / tot : 0, color(e[0]))));
  }

  function strip(day, base) {
    const pts = day.sessions.map((s) => [s.startSec, Math.min(s.endSec, 86400)]).concat(day.shots.map((x) => [x.sec, x.sec]));
    if (!pts.length) return null;
    let loH = Math.max(0, Math.floor(Math.min.apply(null, pts.map((p) => p[0])) / 3600));
    let hiH = Math.min(24, Math.ceil(Math.max.apply(null, pts.map((p) => p[1])) / 3600));
    if (hiH - loH < 2) { hiH = Math.min(24, loH + 2); loH = Math.max(0, hiH - 2); }
    const span = (hiH - loH) * 3600;
    const pos = (sec) => Math.max(0, Math.min(100, (sec - loH * 3600) / span * 100));
    const wrap = el('div', { class: 'stripwrap' });
    const bar = el('div', { class: 'strip' });
    day.sessions.forEach((s) => {
      const l = pos(s.startSec), w = Math.max(0.5, pos(Math.min(s.endSec, 86400)) - l);
      bar.append(el('div', { class: 'seg', style: 'left:' + l + '%;width:' + w + '%;background:' + color(s.project), title: s.project + ' ' + s.start + ' to ' + s.end + ' (' + fmtDur(s.duration) + ')' }));
    });
    day.shots.forEach((x, i) => {
      bar.append(el('button', { class: 'pin', type: 'button', style: 'left:' + pos(x.sec) + '%', title: 'Screenshot ' + x.time, 'aria-label': 'Open screenshot from ' + x.time, onclick: function () { openLB(base + i); } }));
    });
    wrap.append(bar);
    const hours = hiH - loH, step = hours <= 6 ? 1 : hours <= 12 ? 2 : 4;
    for (let h = loH; h <= hiH; h += step) wrap.append(el('span', { class: 'tick', style: 'left:' + pos(h * 3600) + '%' }, pad(h % 24) + ':00'));
    return wrap;
  }

  function renderDays(days) {
    const root = $('#days');
    root.replaceChildren();
    VIS.length = 0;
    for (const day of days) {
      const nd = niceDate(day.date);
      const tot = total(day.sessions);
      const base = VIS.length;
      day.shots.forEach((x) => VIS.push(Object.assign({ date: day.date }, x)));
      const det = el('details', { class: 'day', open: true });
      det.append(el('summary', null,
        el('span', { class: 'dname' }, el('b', null, nd.dow), el('span', null, nd.rest)),
        el('span', { class: 'dtot' }, tot ? fmtDur(tot) : 'no sessions')));
      const chips = Object.entries(byProject(day.sessions)).sort((a, b) => b[1] - a[1]).map((e) => chip(e[0], fmtDur(e[1])));
      if (chips.length) det.append(el('div', { class: 'dchips' }, chips));
      const st = strip(day, base);
      if (st) det.append(st);
      if (day.sessions.length) {
        det.append(el('table', { class: 'sessions' }, el('tbody', null, day.sessions.map((s) =>
          el('tr', null,
            el('td', { class: 't' }, s.start + ' to ' + s.end),
            el('td', { class: 't' }, fmtDur(s.duration)),
            el('td', { class: 't' }, chip(s.project)),
            el('td', { class: 'n' }, s.note || '', s.running ? el('span', { class: 'live' }, 'running now') : null))))));
      }
      if (S.shots && day.shots.length) {
        const grid = el('div', { class: 'shots' });
        day.shots.forEach((x, i) => {
          const idx = base + i;
          grid.append(el('figure', { tabindex: '0', onclick: function () { openLB(idx); }, onkeydown: function (e) { if (e.key === 'Enter') openLB(idx); } },
            el('img', { src: x.src, loading: 'lazy', decoding: 'async', alt: 'Screenshot at ' + x.time }),
            el('figcaption', null, el('span', null, x.time), chip(x.project))));
        });
        det.append(grid);
      }
      root.append(det);
    }
  }

  let LBI = -1;
  function openLB(i) {
    if (i < 0 || i >= VIS.length) return;
    LBI = i;
    const x = VIS[i];
    $('#lbImg').src = x.src;
    $('#lbCap').textContent = x.date + ' ' + x.time + ', ' + x.project + ', ' + x.name + ' (' + (i + 1) + '/' + VIS.length + ')';
    $('#lbOpen').href = x.src;
    $('#lb').hidden = false;
    document.body.classList.add('noscroll');
  }
  function closeLB() {
    $('#lb').hidden = true;
    $('#lbImg').removeAttribute('src');
    document.body.classList.remove('noscroll');
    LBI = -1;
  }

  function exportCsv() {
    const rows = [['date', 'start', 'end', 'duration_seconds', 'duration', 'project', 'note']];
    for (const d of filtered(false)) for (const s of d.sessions) rows.push([d.date, s.start, s.end, Math.round(s.duration), fmtDur(s.duration), s.project, s.note || '']);
    const csv = rows.map((r) => r.map((v) => '"' + String(v).replace(/"/g, '""') + '"').join(',')).join('\n');
    const a = el('a', { href: URL.createObjectURL(new Blob(['\ufeff' + csv], { type: 'text/csv' })), download: 'time-report.csv' });
    document.body.append(a); a.click(); a.remove();
  }

  function applyRange(r) {
    S.range = r;
    const t = new Date();
    if (r === 'all') { S.from = ''; S.to = ''; }
    else if (r === 'today') { S.from = S.to = iso(t); }
    else { const f = new Date(t); f.setDate(f.getDate() - (parseInt(r, 10) - 1)); S.from = iso(f); S.to = iso(t); }
    $('#from').value = S.from; $('#to').value = S.to;
    update();
  }

  function update() {
    const days = filtered(false);
    renderSummary(days);
    renderDaily(days);
    renderProjects();
    renderDays(days);
    document.querySelectorAll('#ranges button').forEach((b) => b.setAttribute('aria-pressed', b.dataset.r === S.range ? 'true' : 'false'));
  }

  // wiring
  $('#gen').textContent = 'Generated ' + D.generated;
  $('#from').min = $('#to').min = D.minDate; $('#from').max = $('#to').max = D.maxDate;
  document.querySelectorAll('#ranges button').forEach((b) => b.addEventListener('click', () => applyRange(b.dataset.r)));
  $('#from').addEventListener('input', (e) => { S.from = e.target.value; S.range = 'custom'; update(); });
  $('#to').addEventListener('input', (e) => { S.to = e.target.value; S.range = 'custom'; update(); });
  $('#q').addEventListener('input', (e) => { S.q = e.target.value; update(); });
  $('#showShots').addEventListener('change', (e) => { S.shots = e.target.checked; update(); });
  $('#order').addEventListener('change', (e) => { S.order = e.target.value; update(); });
  $('#size').addEventListener('input', (e) => document.documentElement.style.setProperty('--thumb', e.target.value + 'px'));
  $('#expand').addEventListener('click', () => document.querySelectorAll('details.day').forEach((d) => { d.open = true; }));
  $('#collapse').addEventListener('click', () => document.querySelectorAll('details.day').forEach((d) => { d.open = false; }));
  $('#btnCsv').addEventListener('click', exportCsv);
  $('#btnPrint').addEventListener('click', () => window.print());
  window.addEventListener('beforeprint', () => document.querySelectorAll('details.day').forEach((d) => { d.open = true; }));
  $('#lbPrev').addEventListener('click', () => openLB(LBI - 1));
  $('#lbNext').addEventListener('click', () => openLB(LBI + 1));
  $('#lbClose').addEventListener('click', closeLB);
  $('#lb').addEventListener('click', (e) => { if (e.target.id === 'lb') closeLB(); });
  document.addEventListener('keydown', (e) => {
    if ($('#lb').hidden) return;
    if (e.key === 'Escape') closeLB();
    else if (e.key === 'ArrowLeft') openLB(LBI - 1);
    else if (e.key === 'ArrowRight') openLB(LBI + 1);
  });

  const themes = ['auto', 'light', 'dark'];
  function setTheme(t) {
    document.documentElement.dataset.theme = t;
    $('#btnTheme').textContent = 'Theme: ' + t;
    try { localStorage.setItem('chronoshot-theme', t); } catch (e) { /* storage can be blocked */ }
  }
  let saved = 'auto';
  try { saved = localStorage.getItem('chronoshot-theme') || 'auto'; } catch (e) { /* ignore */ }
  setTheme(themes.indexOf(saved) >= 0 ? saved : 'auto');
  $('#btnTheme').addEventListener('click', () => setTheme(themes[(themes.indexOf(document.documentElement.dataset.theme) + 1) % 3]));

  update();
})();
</script>
</body>
</html>
"""


def cmd_report(args):
    ensure_dirs()
    d_from, d_to = resolve_range(args)
    out_path = Path(args.out).expanduser().resolve() if args.out else REPORTS_DIR / "report.html"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    data = collect_report_data(d_from, d_to, args.project, args.embed, out_path.parent)
    if not data["days"]:
        print("⚠️  No sessions or accepted screenshots found. The report will be empty.")
    payload = json.dumps(data).replace("<", "\\u003c")  # keep the JSON from ending the script tag
    page = REPORT_TEMPLATE.replace("__TITLE__", "Time report").replace("__DATA__", payload)
    out_path.write_text(page, encoding="utf-8")

    n_sessions = sum(len(d["sessions"]) for d in data["days"])
    n_shots = sum(len(d["shots"]) for d in data["days"])
    print(f"✅ Report generated: {out_path}")
    print(f"   {len(data['days'])} day(s), {n_sessions} session(s), {n_shots} screenshot(s)"
          + (f", {out_path.stat().st_size / 1e6:.1f} MB" if args.embed else ""))
    if not args.embed:
        print("   Screenshots are linked, not copied. Use --embed for a single file you can send to someone.")
    if args.open:
        webbrowser.open(out_path.as_uri())
    else:
        print(f"   Open it: xdg-open {out_path}")


# ----------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------
def add_range_args(p):
    p.add_argument("--date", type=valid_day, help="a single day, YYYY-MM-DD")
    p.add_argument("--from", dest="from_", type=valid_day, metavar="DATE", help="first day, YYYY-MM-DD")
    p.add_argument("--to", type=valid_day, metavar="DATE", help="last day, YYYY-MM-DD")
    p.add_argument("--last", type=int, metavar="N", help="the last N days including today")
    p.add_argument("--project", help="only this project")


def main():
    parser = argparse.ArgumentParser(
        prog="chronoshot",
        description="Time tracker with periodic screenshots, project-aware review and one-page reports.",
        epilog=f"Data folder: {BASE_DIR}   (override with TIMETRACK_HOME)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def add_session_args(p, defaults):
        p.add_argument("--interval", "-i", type=parse_interval, default=defaults,
                       help="time between screenshots: 30, 30s, 15m, 1h (default: %(default)s)")
        p.add_argument("--mode", choices=["ask", "later", "auto"], default=None if defaults is None else DEFAULT_MODE,
                       help="ask = popup each time, later = keep all for 'review', auto = accept all")
        p.add_argument("--note", help="short note shown in the report")
        p.add_argument("--verbose", action="store_true", help="show daemon logs in this terminal")

    p = sub.add_parser("start", help="start tracking")
    p.add_argument("project_pos", nargs="?", metavar="PROJECT")
    p.add_argument("--project", "-p", help="project name (default: Default)")
    add_session_args(p, DEFAULT_INTERVAL)
    p.set_defaults(func=cmd_start)

    p = sub.add_parser("switch", help="stop the current session and start another project")
    p.add_argument("project")
    add_session_args(p, None)
    p.set_defaults(func=cmd_switch)

    p = sub.add_parser("stop", help="stop tracking and log the session")
    p.add_argument("--note", help="add a note to this session")
    p.add_argument("--at", metavar="HH:MM", help="the session really ended at this time")
    p.set_defaults(func=cmd_stop)

    p = sub.add_parser("status", help="show what is running and what is pending")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("review", help="accept or reject pending screenshots")
    p.add_argument("--project", "-p", help="only this project")
    p.add_argument("--date", type=valid_day, help="only this day, YYYY-MM-DD")
    p.add_argument("--today", action="store_true", help="only today")
    p.add_argument("--all", action="store_true", help="every pending screenshot")
    p.add_argument("--terminal", action="store_true", help="use terminal prompts and your image viewer instead of the yad window")
    p.set_defaults(func=cmd_review)

    p = sub.add_parser("report", help="build the one-page report (all days)")
    add_range_args(p)
    p.add_argument("--embed", action="store_true", help="copy screenshots into the html so it is one shareable file")
    p.add_argument("--open", action="store_true", help="open the report in your browser")
    p.add_argument("--out", help="where to write it (default: <data>/reports/report.html)")
    p.set_defaults(func=cmd_report)

    p = sub.add_parser("summary", help="print totals in the terminal")
    add_range_args(p)
    p.set_defaults(func=cmd_summary)

    p = sub.add_parser("delete", help="delete screenshots by file name")
    p.add_argument("filenames", nargs="+")
    p.set_defaults(func=cmd_delete)

    d = sub.add_parser("_daemon")
    d.add_argument("interval", type=int)
    d.add_argument("--project", default="Default")
    d.add_argument("--mode", default=DEFAULT_MODE)
    d.set_defaults(func=lambda a: daemon_loop(a.interval, a.project, a.mode))

    args = parser.parse_args()
    ensure_dirs()
    if args.command == "switch" and args.mode is None:
        args.mode = None
    if args.command == "start" and args.mode is None:
        args.mode = DEFAULT_MODE
    args.func(args)


if __name__ == "__main__":
    main()
