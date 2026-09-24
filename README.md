# Chronoshot

A tiny, local-only time tracker that takes periodic screenshots while you work. Everything lives on your machine — no account, no cloud, no telemetry.

You start a session, chronoshot snaps a screenshot every N seconds, and when you stop it logs the time. Screenshots can be accepted on the spot, reviewed later, or auto-accepted. Then `report` builds a single self-contained HTML page with every day, filterable and charted.

---

## Quick start

```bash
# 1. Start tracking a project (screenshot every 30s, popup asks each time)
python chronoshot.py start -p "My Project"

# 2. See what's happening
python chronoshot.py status

# 3. Stop and log the session
python chronoshot.py stop

# 4. Build and open the report
python chronoshot.py report --open
```

That's the whole loop. Everything else is optional.

---

## Requirements

- **Python 3.9+** (no third-party packages required to run it)
- **A screenshot tool**, any one of these — chronoshot tries them in order:
  - `spectacle` (KDE)
  - `gnome-screenshot` (GNOME)
  - `grim` (wlroots Wayland)
  - `scrot` (X11)
- **`yad`** (optional) — for the accept/reject popup while tracking, and the review window. Without it, screenshots pile up for `review` instead.
- **Pillow** (optional) — makes popup previews smaller and lets `report --embed` produce a single shareable file.

  ```bash
  pip install Pillow
  ```

---

## Installation

Chronoshot is a plain script + package. Clone it and run it in place:

```bash
git clone git@github.com:mdborhan-dev/chronoshot-tracker.git
cd chronoshot-tracker
python chronoshot.py status      # smoke test
```

Want it on your `$PATH`?

```bash
# Make the launcher executable
chmod +x chronoshot.py

# Symlink it somewhere on your PATH
ln -s "$PWD/chronoshot.py" ~/.local/bin/chronoshot
```

Then `chronoshot start -p "My Project"` works from anywhere.

---

## Commands

### `start` — begin tracking

```bash
python chronoshot.py start -p "My Project"
python chronoshot.py start "My Project"            # project as positional arg
python chronoshot.py start -p "Writing" -i 15m     # screenshot every 15 minutes
python chronoshot.py start -p "Deep work" --mode later
```

| Flag               | Meaning                                             | Default   |
| ------------------ | --------------------------------------------------- | --------- |
| `-p`, `--project`  | Project name                                        | `Default` |
| `-i`, `--interval` | Time between screenshots (`30`, `30s`, `15m`, `1h`) | `30`      |
| `--mode`           | `ask` / `later` / `auto` (see below)                | `ask`     |
| `--note`           | Short note shown in the report                      | —         |
| `--verbose`        | Print daemon logs to this terminal                  | off       |

> **Note on the default interval:** `30s` is a testing value. Once you're happy with how it behaves, switch to something like `-i 15m` or `-i 1h`. Screenshots add up fast.

### `switch` — change project without stopping

Stops the current session (logs it) and starts a new one, keeping the interval and mode:

```bash
python chronoshot.py switch "Other Project"
```

### `stop` — stop and log

```bash
python chronoshot.py stop
python chronoshot.py stop --note "wrapped up early"
python chronoshot.py stop --at 17:30      # you actually stopped at 17:30, not now
```

`--at HH:MM` is handy if you forgot to stop and only remember later.

### `status` — what's running, what's pending

```bash
python chronoshot.py status
```

Shows the running project, elapsed time, interval, mode, plus a breakdown of pending screenshots by day and project.

### `review` — accept or reject pending screenshots

```bash
python chronoshot.py review                    # interactive: pick a scope
python chronoshot.py review --today
python chronoshot.py review --project Writing
python chronoshot.py review --date 2026-09-24
python chronoshot.py review --all
python chronoshot.py review --terminal         # no yad, use your image viewer
```

With no filters, chronoshot lists the pending groups and asks which one to review. With `--today`, `--project`, `--date`, or `--all` it jumps straight in.

**Keys:**

| Key | Action                                 |
| --- | -------------------------------------- |
| `a` | Accept                                 |
| `r` | Reject (delete)                        |
| `s` | Skip (leave pending)                   |
| `o` | Reopen in your image viewer            |
| `q` | Quit — the rest stay pending           |
| `A` | Accept all remaining in this batch     |
| `R` | Reject all remaining (asks to confirm) |

### `report` — one HTML page with everything

```bash
python chronoshot.py report --open
python chronoshot.py report --last 7 --open
python chronoshot.py report --from 2026-09-01 --to 2026-09-30
python chronoshot.py report --project Writing --open
python chronoshot.py report --embed --out ~/Desktop/report.html
```

| Flag                       | Meaning                                                   |
| -------------------------- | --------------------------------------------------------- |
| `--date DATE`              | A single day (`YYYY-MM-DD`)                               |
| `--from DATE`, `--to DATE` | Date range                                                |
| `--last N`                 | Last N days including today                               |
| `--project NAME`           | Only this project                                         |
| `--embed`                  | Copy screenshots _into_ the HTML — one file you can email |
| `--open`                   | Open the result in your browser                           |
| `--out PATH`               | Where to write it (default: `<data>/reports/report.html`) |

Without `--embed`, screenshots are linked relatively — the report is tiny but only works if it stays next to the screenshots. With `--embed`, images are base64'd into the file. Handy for sharing; expect a few MB.

**The report itself has:**

- Date range presets (today / 7 days / 30 days / all) plus manual `from`/`to`
- Project filter with per-project totals and share bars
- Full-text search across project names and notes
- A stacked bar chart: time per day, split by project
- Per-day timeline strip with clickable screenshot pins
- Session table (start, end, duration, project, note)
- Screenshot grid with a built-in lightbox (arrow keys, Esc)
- **Export CSV** of the currently filtered sessions
- **Print** stylesheet (dark theme off, all days expanded)
- Theme toggle: auto / light / dark (remembered in `localStorage`)

### `serve` — view the report at `http://localhost:8000/`

Builds (if needed) and serves the report over localhost as a background daemon. Runs in a detached process, so your shell stays free.

```bash
python chronoshot.py serve                  # build if needed, serve, open browser
python chronoshot.py serve --build          # always rebuild first
python chronoshot.py serve --port 9000      # different port
python chronoshot.py serve --foreground     # Ctrl+C to stop, for debugging
python chronoshot.py serve --status         # is it running?
python chronoshot.py serve --stop           # stop the daemon
```

| Flag                 | Meaning                                                      |
| -------------------- | ------------------------------------------------------------ |
| `--host ADDR`        | Bind address (default: `127.0.0.1` — localhost only)         |
| `--port N`           | Port (default: `8000`)                                       |
| `--report PATH`      | Report file to serve (default: `<data>/reports/report.html`) |
| `--build`            | Regenerate the report before starting                        |
| `--no-open`          | Don't open the browser automatically                         |
| `--foreground`, `-f` | Run in the foreground instead of as a daemon                 |
| `--stop`             | Stop the running server                                      |
| `--status`           | Show whether the server is running                           |

**Why it's served from the data folder, not from `reports/`:** without `--embed`, the report references screenshots with relative paths like `../screenshots/accepted/...`. Serving `~/timetrack/` keeps both `reports/` and `screenshots/` reachable; serving just `reports/` would 404 every image.

**Regenerating the report while serving:** the server reads files fresh on each request, so just run `chronoshot.py report` in another terminal and hit refresh in the browser — no restart needed.

**Sharing with your phone on the same wifi:**

```bash
python chronoshot.py serve --host 0.0.0.0
# then visit http://<your-laptop-ip>:8000/reports/report.html
```

⚠️ The server has **no authentication**. Only bind `0.0.0.0` on networks you trust. Stop it with `serve --stop` when you're done.

**Environment variables** (same pattern as `TIMETRACK_HOME`):

```bash
CHRONOSHOT_HOST=127.0.0.1 CHRONOSHOT_PORT=9000 python chronoshot.py serve
```

### `summary` — quick totals in the terminal

```bash
python chronoshot.py summary --last 7
python chronoshot.py summary --project Writing --last 30
```

Prints a per-day breakdown and totals by project.

### `delete` — remove a screenshot by file name

```bash
python chronoshot.py delete 2026-09-24_153012__Writing.png
```

Looks in both `accepted/` and `pending/`.

---

## Modes explained

| Mode        | What happens to each screenshot                                                                                                                                                                                      |
| ----------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **`ask`**   | A `yad` popup appears with a preview and Accept / Reject / Later buttons. The popup times out after `interval - 5` seconds (clamped to 10–120s) and defaults to **Later**. No `yad`? Falls back to `later` behavior. |
| **`later`** | Every screenshot is kept in `pending/`. You sort them out in bulk with `review`.                                                                                                                                     |
| **`auto`**  | Everything is accepted immediately. Good for "I just want a record, I'll delete later."                                                                                                                              |

`ask` is the default and usually the right choice for focused work. `later` is better if popups break your flow.

---

## Where your data lives

By default, everything is under `~/timetrack`:

```
~/timetrack/
├── logs/
│   └── 2026-09-24.json              one file per day, list of sessions
├── screenshots/
│   ├── pending/                     waiting for review
│   └── accepted/                    kept
├── reports/
│   └── report.html                  last generated report
├── current_session.json             present only while tracking
├── daemon.pid                       PID of the running daemon
└── daemon.log                       daemon stdout/stderr
```

**Session format** (`logs/YYYY-MM-DD.json`) — a list, appended to:

```json
[
  {
    "start": "2026-09-24T09:15:00",
    "end": "2026-09-24T11:42:33",
    "duration": 8853.0,
    "project": "Writing",
    "note": ""
  }
]
```

**Screenshot file names** carry everything needed to filter:

```
2026-09-24_153012__Writing.png
│          │      │
│          │      └── URL-encoded project name (omitted for old "Default" files)
│          └────────── HHMMSS
└───────────────────── YYYY-MM-DD
```

Old files without `__project` are treated as project `Default`, so previous logs keep working.

### Using a different data folder

Set `TIMETRACK_HOME` to put the data somewhere else — useful for testing:

```bash
TIMETRACK_HOME=/tmp/chronoshot-test python chronoshot.py start -p Test
```

---

## Project layout

Chronoshot is a thin launcher next to a small package. Every file does one thing.

```
chronoshot-tracker/
├── chronoshot.py          ← the launcher you run
├── README.md
└── chronoshot/            ← the package
    ├── __init__.py
    ├── __main__.py        ← enables `python -m chronoshot`
    ├── cli.py             ← argparse: defines every command
    ├── config.py          ← paths, defaults
    ├── util.py            ← dates, JSON, formatting, daemon PID
    ├── shots.py           ← screenshot naming, listing, capture, previews
    ├── daemon.py          ← the background loop
    ├── session.py         ← start / stop / switch / status
    ├── review.py          ← accept / reject pending
    ├── report.py          ← the HTML report + its template
    └── summary.py         ← terminal totals + delete
```

You can also run it as a module — the two are equivalent:

```bash
python chronoshot.py start -p "My Project"
python -m chronoshot start -p "My Project"
```

---

## Tips

- **Set the interval to something realistic.** `30s` is only for testing. `15m` or `1h` is normal for real use.
- **Run `stop` when you're done.** Forgetting leaves a session "unfinished" — `status` will nag, and `stop --at HH:MM` lets you backdate it.
- **`switch` beats `stop` + `start`.** One command, keeps your interval and mode.
- **Review in batches.** `review --today` right before bed is much less painful than a week of `ask` popups.
- **Use `--embed` to share.** One HTML file with everything; send it, print it, whatever.
- **CSV export for spreadsheets.** In the report sidebar, "Export CSV" gives you whatever's currently filtered.

---

## Troubleshooting

**"Tracking already running"**
You have a live daemon. `status` shows it; `stop` ends it. If you're sure nothing is running:

```bash
rm ~/timetrack/daemon.pid
```

**"An unfinished session exists … but nothing is running"**
The daemon died without logging (crash, kill -9, reboot). Run:

```bash
python chronoshot.py stop                 # logs it as ending now
python chronoshot.py stop --at 17:30      # logs it as ending at 17:30
```

**No screenshots are being taken**
Your screenshot tool isn't installed or isn't working. Check:

```bash
which spectacle gnome-screenshot grim scrot
```

and look at `~/timetrack/daemon.log` for errors.

**Popups don't appear (`ask` mode)**
`yad` isn't installed. Either:

```bash
sudo apt install yad          # Debian/Ubuntu
sudo pacman -S yad            # Arch
```

or just use `--mode later` and review in bulk.

**Report has no screenshots, only times**
Without `--embed`, the HTML links to files next to it. If you moved `report.html` away from `~/timetrack/`, the links break. Regenerate it in place, or use `--embed`.

**`git push` fails with `Temporary failure in name resolution`**
That's DNS, not git. Check `ping github.com`; if the hostname doesn't resolve but `ping 8.8.8.8` does, your resolver is the problem (try a different network, VPN off/on, or `wsl --shutdown` if you're on WSL).

---

## License

Do whatever you want with it.
