#!/usr/bin/env python3
"""
chronoshot - a small time tracker that takes periodic screenshots.

This file is just a launcher; the real code lives in the chronoshot/ folder.
First-time setup installs it as `chronoshot` (see the README). Then:

    chronoshot start -p "My Project"
    chronoshot switch "Other Project"
    chronoshot stop
    chronoshot status
    chronoshot review
    chronoshot report --open
    chronoshot serve --build
    chronoshot summary --last 7
    chronoshot delete FILE...

Data lives in ~/timetrack. Set TIMETRACK_HOME=/some/dir to use a different folder.
"""

from chronoshot.cli import main

if __name__ == "__main__":
    main()
