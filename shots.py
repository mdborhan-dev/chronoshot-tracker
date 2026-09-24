"""Screenshot files: naming, listing, capturing, previews."""

import os
import re
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import quote, unquote

FILE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})_(\d{6})(?:__(.+))?\.png$")


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
        ["spectacle", "-b", "-n", "-o", filepath],
        ["gnome-screenshot", "-f", filepath],
        ["grim", filepath],
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
