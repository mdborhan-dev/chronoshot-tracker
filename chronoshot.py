#!/usr/bin/env python3
"""
chronoshot - a small time tracker that takes periodic screenshots.

This file is just a launcher; the real code lives in the chronoshot/ folder.

    python chronoshot.py start -p "My Project"
    python chronoshot.py switch "Other Project"
    python chronoshot.py stop
    python chronoshot.py status
    python chronoshot.py review
    python chronoshot.py report --open
    python chronoshot.py summary --last 7
    python chronoshot.py delete FILE...

Data lives in ~/timetrack. Set TIMETRACK_HOME=/some/dir to use a different folder.
"""

from chronoshot.cli import main

if __name__ == "__main__":
    main()
