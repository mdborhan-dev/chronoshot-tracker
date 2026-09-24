# Chronoshot

**Chronoshot** is a lightweight Linux time tracker that periodically captures screenshots while you work.

It tracks time by **project**, lets you accept or reject screenshots, stores sessions as simple JSON files, and generates a self-contained HTML report with timelines, charts, filters, and screenshots.

> Built for a simple workflow: start working → Chronoshot takes screenshots → review them → generate a report.

## Features

- ⏱️ Track time spent on different projects
- 📸 Automatically capture screenshots at configurable intervals
- 🗂️ Project-aware screenshots and sessions
- 🔀 Switch between projects without manually stopping and restarting
- 👀 Review screenshots before accepting them
- 🖥️ GUI review with `yad`, with a terminal fallback
- 📊 Generate a single-page HTML time report
- 📈 Daily time charts and project breakdowns
- 🔎 Filter reports by date, project, and search text
- 🌙 Automatic/light/dark report themes
- 📤 Export report data to CSV from the browser
- 📝 Add notes to sessions
- 📁 Uses plain files and JSON — no database required
- 🔄 Compatible with existing data in `~/timetrack`
- 🧪 Use `TIMETRACK_HOME` for an isolated testing directory

## Requirements

Chronoshot requires **Python 3**.

For screenshots, it automatically tries the following tools in order:

1. `spectacle` — KDE
2. `gnome-screenshot` — GNOME
3. `grim` — wlroots/Wayland
4. `scrot` — X11

You only need one working screenshot backend.

### Optional dependencies

**YAD** provides graphical screenshot review dialogs.

**Pillow** is optional and is used to create smaller preview images and optimize screenshots embedded into reports.

For example, on Arch/CachyOS:

```bash
sudo pacman -S spectacle yad python-pillow
```

If you are using another desktop environment, install whichever screenshot utility is appropriate for your setup.

## Installation

Chronoshot is currently a single Python script, so no package installation is required.

Clone or copy the script somewhere in your `$PATH`:

```bash
chmod +x chronoshot.py
```

For example:

```bash
mkdir -p ~/.local/bin
cp chronoshot.py ~/.local/bin/chronoshot
chmod +x ~/.local/bin/chronoshot
```

Then run:

```bash
chronoshot --help
```

You can also run it directly:

```bash
./chronoshot.py --help
```

## Quick Start

Start tracking a project:

```bash
chronoshot start -p "My Project"
```

Chronoshot will take a screenshot every 30 seconds by default.

Check the current state:

```bash
chronoshot status
```

Stop tracking:

```bash
chronoshot stop
```

View your tracked time:

```bash
chronoshot summary --last 7
```

Generate an HTML report:

```bash
chronoshot report --open
```

That's the basic workflow.

---

# Commands

## `start`

Start a new tracking session.

```bash
chronoshot start -p "My Project"
```

A positional project name also works:

```bash
chronoshot start "My Project"
```

### Screenshot interval

The default interval is **30 seconds**.

You can specify seconds, minutes, or hours:

```bash
chronoshot start "My Project" --interval 30
chronoshot start "My Project" --interval 30s
chronoshot start "My Project" --interval 15m
chronoshot start "My Project" --interval 1h
```

The minimum interval is 5 seconds.

### Screenshot modes

Chronoshot has three modes.

#### `ask`

Ask what to do after every screenshot:

```bash
chronoshot start "My Project" --mode ask
```

The YAD dialog provides:

- Accept
- Reject
- Later

If YAD isn't installed, screenshots are kept for later review.

#### `later`

Keep every screenshot pending:

```bash
chronoshot start "My Project" --mode later
```

Review them later with:

```bash
chronoshot review
```

#### `auto`

Automatically accept every screenshot:

```bash
chronoshot start "My Project" --mode auto
```

### Session notes

Add a note to the session:

```bash
chronoshot start "My Project" --note "Working on authentication"
```

### Verbose mode

Run the daemon with its output visible in the current terminal:

```bash
chronoshot start "My Project" --verbose
```

---

## `switch`

Stop the current session and immediately start another project.

```bash
chronoshot switch "Other Project"
```

For example:

```bash
chronoshot start "Website"
chronoshot switch "Skyrim Modding"
chronoshot switch "Learning Python"
```

The interval and screenshot mode are inherited from the current session unless explicitly changed.

```bash
chronoshot switch "Other Project" --interval 15m
```

---

## `stop`

Stop the current tracking session and save it to the day's log.

```bash
chronoshot stop
```

You can add a note:

```bash
chronoshot stop --note "Finished the login page"
```

### Correct an ending time

If you forgot to stop Chronoshot at the actual time you finished:

```bash
chronoshot stop --at 17:30
```

This records the session as ending at `17:30`.

---

## `status`

Show the current tracking state:

```bash
chronoshot status
```

It displays information such as:

- Current project
- Start time
- Elapsed time
- Screenshot interval
- Screenshot mode
- Session note
- Accepted screenshots today
- Pending screenshots

---

# Reviewing Screenshots

Screenshots that haven't been accepted are stored as **pending**.

Run:

```bash
chronoshot review
```

If YAD is available, screenshots are displayed in a graphical review window.

Otherwise Chronoshot falls back to terminal prompts and opens screenshots using your system image viewer.

### Review a specific project

```bash
chronoshot review --project "My Project"
```

### Review a specific date

```bash
chronoshot review --date 2026-09-24
```

### Review today's screenshots

```bash
chronoshot review --today
```

### Review everything

```bash
chronoshot review --all
```

### Force terminal mode

```bash
chronoshot review --terminal
```

Terminal review supports:

```text
a = accept
r = reject
s = skip
o = reopen
q = quit
A = accept the rest
R = reject the rest
```

---

# Reports

Generate the HTML report:

```bash
chronoshot report
```

By default it is saved to:

```text
~/timetrack/reports/report.html
```

Open it automatically:

```bash
chronoshot report --open
```

The report includes:

- Total tracked time
- Number of sessions
- Number of accepted screenshots
- Time per day
- Project breakdowns
- Session timelines
- Session notes
- Screenshot galleries
- Screenshot lightbox
- Date filtering
- Project filtering
- Search
- Screenshot size control
- Day ordering
- Light/dark/automatic theme
- CSV export
- Printing

## Date filtering

Report for a single day:

```bash
chronoshot report --date 2026-09-24
```

Report for the last 7 days:

```bash
chronoshot report --last 7
```

Report for a custom range:

```bash
chronoshot report --from 2026-09-01 --to 2026-09-24
```

Filter by project:

```bash
chronoshot report --project "My Project"
```

You can combine these options:

```bash
chronoshot report \
    --from 2026-09-01 \
    --to 2026-09-24 \
    --project "My Project" \
    --open
```

## Single-file reports

By default, screenshots are linked from the report rather than copied into it.

To create a completely self-contained HTML file:

```bash
chronoshot report --embed
```

This embeds the screenshots directly into the HTML.

That makes the resulting report easier to send or move to another machine.

You can also specify the output path:

```bash
chronoshot report --embed --out ~/Desktop/my-report.html
```

---

# Terminal Summaries

Get a quick summary without generating an HTML report:

```bash
chronoshot summary
```

Last 7 days:

```bash
chronoshot summary --last 7
```

Today:

```bash
chronoshot summary --date 2026-09-24
```

Custom range:

```bash
chronoshot summary \
    --from 2026-09-01 \
    --to 2026-09-24
```

Specific project:

```bash
chronoshot summary --project "My Project"
```

The output includes daily totals, screenshots, time per project, and overall totals.

---

# Deleting Screenshots

Delete screenshots by filename:

```bash
chronoshot delete "2026-09-24_153012__My%20Project.png"
```

The command checks both the pending and accepted screenshot directories.

---

# Data Storage

By default, Chronoshot stores everything in:

```text
~/timetrack/
```

The directory looks approximately like this:

```text
~/timetrack/
├── current_session.json
├── daemon.pid
├── daemon.log
├── logs/
│   ├── 2026-09-23.json
│   └── 2026-09-24.json
├── screenshots/
│   ├── pending/
│   │   └── *.png
│   └── accepted/
│       └── *.png
└── reports/
    └── report.html
```

Sessions are stored as JSON, with one log file per day.

There is no external database.

## Custom data directory

Set `TIMETRACK_HOME` to use another location:

```bash
TIMETRACK_HOME=/tmp/chronoshot-test chronoshot start "Test"
```

This is particularly useful when testing Chronoshot without touching your normal tracking data.

For example:

```bash
export TIMETRACK_HOME="$HOME/.local/share/chronoshot"
chronoshot status
```

---

# Screenshot Naming

Screenshots include both the timestamp and project name.

Example:

```text
2026-09-24_153012__My%20Project.png
```

The format is:

```text
YYYY-MM-DD_HHMMSS__PROJECT.png
```

Project names are URL-encoded inside the filename.

Older screenshots without a project component are treated as belonging to the `Default` project.

---

# How It Works

When you run:

```bash
chronoshot start "My Project"
```

Chronoshot:

1. Creates the required data directories.
2. Records the session start time.
3. Starts a background daemon.
4. The daemon captures a screenshot at the configured interval.
5. Screenshots are initially placed in `screenshots/pending/`.
6. Depending on the selected mode, screenshots are:
   - accepted automatically,
   - presented for immediate approval,
   - or left pending for later review.
7. When the session is stopped, its duration is written to the daily JSON log.
8. Accepted screenshots and logged sessions are available to the report generator.

The project name is stored directly in screenshot filenames, so screenshots can be filtered by project without requiring a separate screenshot database.

---

# Example Workflow

A typical work session could look like:

```bash
# Start working
chronoshot start "Web Development" --interval 15m --mode later

# Check status
chronoshot status

# Switch to another project
chronoshot switch "Skyrim Modding"

# Finish working
chronoshot stop
```

Later, review screenshots:

```bash
chronoshot review
```

Then generate your report:

```bash
chronoshot report --last 7 --open
```

Or generate a portable report:

```bash
chronoshot report --last 7 --embed --out ~/Desktop/time-report.html
```

---

# Screenshot Backend Compatibility

Chronoshot attempts screenshot utilities in this order:

```text
spectacle
gnome-screenshot
grim
scrot
```

This makes it suitable for different Linux desktop environments.

For example:

| Environment | Suggested backend |
|---|---|
| KDE Plasma | `spectacle` |
| GNOME | `gnome-screenshot` |
| wlroots compositors | `grim` |
| X11 | `scrot` |

Only one needs to be available.

---

# Optional YAD GUI

YAD is used for the graphical screenshot approval and review dialogs.

If it isn't installed, Chronoshot still works.

During tracking, screenshots are simply kept pending instead of showing an approval popup.

During review, Chronoshot falls back to terminal mode.

So YAD is a convenience dependency, not a hard requirement.

---

# Privacy

Chronoshot captures screenshots of your desktop.

Because screenshots may contain sensitive information, treat the `~/timetrack/screenshots/` directory as private data.

In particular, screenshots can potentially contain:

- Password managers
- Private messages
- Browser tabs
- Documents
- Source code
- Personal information

Review screenshots before sharing reports, especially when using `--embed`.

Chronoshot does not require a cloud service or external account; its tracking data is stored locally.

---

# Command Reference

```text
chronoshot start [PROJECT]
chronoshot switch PROJECT
chronoshot stop
chronoshot status
chronoshot review
chronoshot report
chronoshot summary
chronoshot delete FILE...
```

Get the complete built-in help with:

```bash
chronoshot --help
```

Individual commands also provide their own help:

```bash
chronoshot start --help
chronoshot review --help
chronoshot report --help
chronoshot summary --help
```

---

# License

No license is currently specified in the source code.

If you plan to publish Chronoshot, add a license file and update this section accordingly.