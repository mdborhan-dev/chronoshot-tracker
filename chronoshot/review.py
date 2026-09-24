"""Accept or reject pending screenshots."""

import html
import shutil
import subprocess
from collections import defaultdict
from datetime import date

from . import config, shots
from .util import ensure_dirs


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
    preview = shots.make_preview(it["path"], (1100, 700))
    text = f"<b>{html.escape(it['project'])}</b>   {it['date']} {it['time']}\nScreenshot {i} of {n}"
    try:
        rc = subprocess.run(
            [
                "yad",
                "--image",
                preview or str(it["path"]),
                "--text",
                text,
                "--button=Quit:3",
                "--button=Skip:2",
                "--button=Reject:1",
                "--button=Accept:0",
                "--center",
                "--title=Chronoshot review",
            ]
        ).returncode
    finally:
        shots.drop(preview)
    return {0: "a", 1: "r", 2: "s"}.get(rc, "q")


def open_viewer(path):
    try:
        subprocess.Popen(
            ["xdg-open", str(path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        print("  xdg-open not found, open this file yourself:", path)


def decide_terminal(it, i, n):
    print(f"\n[{i}/{n}] {it['date']} {it['time']}   project: {it['project']}")
    print(f"      {it['path']}")
    open_viewer(it["path"])
    while True:
        try:
            ans = input(
                "  a=accept  r=reject  s=skip  o=reopen  q=quit  "
                "A=accept rest  R=reject rest > "
            ).strip()
        except (EOFError, KeyboardInterrupt):
            return "q"
        if ans in ("A", "R"):
            if (
                ans == "R"
                and input("  Delete ALL remaining in this batch? [y/N] ")
                .strip()
                .lower()
                != "y"
            ):
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
    pending = shots.list_shots(config.PENDING_DIR)
    if not pending:
        print("No pending screenshots.")
        return
    scope = choose_scope(pending, args)
    if scope is None:
        return
    items, label = scope
    other = len(pending) - len(items)
    if not items:
        print(
            f"No pending screenshots for {label}. "
            f"({other} pending elsewhere: try 'review' with no options.)"
        )
        return

    use_gui = bool(shutil.which("yad")) and not args.terminal
    print(
        f"Reviewing {len(items)} screenshot(s): {label}"
        + (f"   ({other} more pending elsewhere)" if other else "")
    )
    if not use_gui and not args.terminal:
        print("(yad not installed, using terminal mode)")

    counts = {"a": 0, "r": 0, "s": 0}
    bulk = None
    for i, it in enumerate(items, 1):
        action = bulk or (
            decide_gui(it, i, len(items))
            if use_gui
            else decide_terminal(it, i, len(items))
        )
        if action in ("A", "R"):
            bulk = action
            action = action.lower()
        if action == "q":
            print("Stopped. The rest stay pending.")
            break
        if action == "a":
            shutil.move(str(it["path"]), config.ACCEPTED_DIR / it["name"])
        elif action == "r":
            it["path"].unlink(missing_ok=True)
        counts[action] += 1
    print(
        f"Done: {counts['a']} accepted, {counts['r']} rejected, {counts['s']} skipped."
    )
