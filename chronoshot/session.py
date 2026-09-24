"""start / stop / switch / status."""

import os
import shutil
import signal
import subprocess
import sys
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

from . import config, shots
from .util import ensure_dirs, read_json, write_json, fmt_dur, daemon_pid

# Where the `chronoshot` package lives (so the spawned daemon can find it).
PKG_PARENT = Path(__file__).resolve().parent.parent


def do_start(project, interval, mode, note="", verbose=False):
    ensure_dirs()
    if daemon_pid():
        print(
            "Tracking already running. Use 'switch' to change project, or 'stop' first."
        )
        return False
    if config.CURRENT_SESSION.exists():
        s = read_json(config.CURRENT_SESSION, {})
        print(
            f"⚠️  An unfinished session exists ({s.get('project', '?')}, "
            f"started {s.get('start', '?')}) but nothing is running.\n"
            "   Run 'stop' first (or 'stop --at HH:MM' to set when it really ended)."
        )
        return False

    write_json(
        config.CURRENT_SESSION,
        {
            "start": datetime.now().isoformat(timespec="seconds"),
            "project": project,
            "note": note or "",
            "interval": interval,
            "mode": mode,
        },
    )
    cmd = [
        sys.executable,
        "-m",
        "chronoshot",
        "_daemon",
        str(interval),
        "--project",
        project,
        "--mode",
        mode,
    ]
    if verbose:
        proc = subprocess.Popen(
            cmd, stdin=subprocess.DEVNULL, start_new_session=True, cwd=str(PKG_PARENT)
        )
    else:
        log = open(config.LOG_FILE, "a")
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            start_new_session=True,
            cwd=str(PKG_PARENT),
        )
    config.PID_FILE.write_text(str(proc.pid))

    mode_text = {
        "ask": "popup asks on each screenshot",
        "later": "screenshots wait for 'review'",
        "auto": "screenshots are accepted automatically",
    }[mode]
    print(f"Tracking started (PID {proc.pid}). Project: {project}")
    print(f"Screenshot every {fmt_dur(interval)}; {mode_text}.")
    if mode == "ask" and not shutil.which("yad"):
        print(
            "Note: 'yad' is not installed, so screenshots will wait for 'review' instead."
        )
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
    if not config.CURRENT_SESSION.exists():
        print("No active session.")
        return None
    pid = daemon_pid()
    if pid:
        try:
            os.kill(pid, signal.SIGTERM)
            print("Daemon stopped.")
        except ProcessLookupError:
            pass
    config.PID_FILE.unlink(missing_ok=True)

    data = read_json(config.CURRENT_SESSION, None)
    if not data:
        config.CURRENT_SESSION.unlink(missing_ok=True)
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
    log_file = config.LOGS_DIR / f"{start:%Y-%m-%d}.json"
    sessions = read_json(log_file, [])
    sessions.append(session)
    write_json(log_file, sessions)
    config.CURRENT_SESSION.unlink(missing_ok=True)

    print(
        f"Session logged: {start:%H:%M} - {end:%H:%M} "
        f"({fmt_dur(duration)}) [Project: {session['project']}]"
    )
    left = len(shots.list_shots(config.PENDING_DIR, project=session["project"]))
    if left:
        print(
            f"{left} screenshot(s) still waiting: "
            f'chronoshot.py review --project "{session["project"]}"'
        )
    return session


def cmd_start(args):
    project = args.project or args.project_pos or "Default"
    do_start(project, args.interval, args.mode, args.note, args.verbose)


def cmd_stop(args):
    do_stop(args.note or "", args.at)


def cmd_switch(args):
    current = (
        read_json(config.CURRENT_SESSION, {}) if config.CURRENT_SESSION.exists() else {}
    )
    interval = args.interval or current.get("interval") or config.DEFAULT_INTERVAL
    mode = args.mode or current.get("mode") or config.DEFAULT_MODE
    if config.CURRENT_SESSION.exists():
        do_stop()
    do_start(args.project, interval, mode, args.note, args.verbose)


def cmd_status(args):
    ensure_dirs()
    pid = daemon_pid()
    data = (
        read_json(config.CURRENT_SESSION, None)
        if config.CURRENT_SESSION.exists()
        else None
    )
    if pid and data:
        start = datetime.fromisoformat(data["start"])
        elapsed = (datetime.now() - start).total_seconds()
        print(f"Tracking is running (PID {pid}).")
        print(f"  Project:  {data.get('project', 'Default')}")
        print(f"  Started:  {start:%Y-%m-%d %H:%M:%S} ({fmt_dur(elapsed)} ago)")
        print(
            f"  Interval: {fmt_dur(data.get('interval', config.DEFAULT_INTERVAL))}, "
            f"mode: {data.get('mode', config.DEFAULT_MODE)}"
        )
        if data.get("note"):
            print(f"  Note:     {data['note']}")
    elif data:
        print(
            f"Not running, but an unfinished session is on file "
            f"({data.get('project')}, started {data.get('start')})."
        )
        print("Run 'stop' (optionally 'stop --at HH:MM') to log it.")
    else:
        print("Tracking is not running.")

    today = date.today().isoformat()
    pending = shots.list_shots(config.PENDING_DIR)
    print(
        f"Today: {len(shots.list_shots(config.ACCEPTED_DIR, day=today))} accepted, "
        f"{len(shots.list_shots(config.PENDING_DIR, day=today))} pending. "
        f"Pending overall: {len(pending)}."
    )
    per = defaultdict(int)
    for it in pending:
        per[(it["date"], it["project"])] += 1
    for (d, p), n in sorted(per.items(), reverse=True)[:8]:
        print(f"    {d}  {p}: {n} pending")
