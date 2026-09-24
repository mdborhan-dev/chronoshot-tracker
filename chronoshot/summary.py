"""Terminal summary and screenshot deletion."""

from collections import defaultdict
from pathlib import Path

from . import config, shots
from .util import ensure_dirs, read_json, fmt_dur, in_range, log_days, resolve_range


def cmd_summary(args):
    ensure_dirs()
    d_from, d_to = resolve_range(args)
    per_day = defaultdict(lambda: defaultdict(float))
    for day in log_days():
        if not in_range(day, d_from, d_to):
            continue
        for s in read_json(config.LOGS_DIR / f"{day}.json", []):
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
        shot_count = len(shots.list_shots(config.ACCEPTED_DIR, day=day))
        print(f"{day}   {fmt_dur(total):>9}   {shot_count} screenshot(s)")
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
        for folder in (config.ACCEPTED_DIR, config.PENDING_DIR):
            f = folder / name
            if f.exists():
                f.unlink()
                print(f"Deleted {name}")
                break
        else:
            print(f"File {name} not found.")
