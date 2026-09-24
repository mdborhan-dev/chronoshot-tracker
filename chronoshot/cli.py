"""Command line interface."""

import argparse

from . import config, daemon, report, review, serve, session, summary
from .util import ensure_dirs, parse_interval, valid_day


def add_range_args(p):
    p.add_argument("--date", type=valid_day, help="a single day, YYYY-MM-DD")
    p.add_argument(
        "--from",
        dest="from_",
        type=valid_day,
        metavar="DATE",
        help="first day, YYYY-MM-DD",
    )
    p.add_argument("--to", type=valid_day, metavar="DATE", help="last day, YYYY-MM-DD")
    p.add_argument(
        "--last", type=int, metavar="N", help="the last N days including today"
    )
    p.add_argument("--project", help="only this project")


def main():
    parser = argparse.ArgumentParser(
        prog="chronoshot",
        description="Time tracker with periodic screenshots, "
        "project-aware review and one-page reports.",
        epilog=f"Data folder: {config.BASE_DIR}   (override with TIMETRACK_HOME)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def add_session_args(p, defaults):
        p.add_argument(
            "--interval",
            "-i",
            type=parse_interval,
            default=defaults,
            help="time between screenshots: 30, 30s, 15m, 1h (default: %(default)s)",
        )
        p.add_argument(
            "--mode",
            choices=["ask", "later", "auto"],
            default=None if defaults is None else config.DEFAULT_MODE,
            help="ask = popup each time, later = keep all for 'review', "
            "auto = accept all",
        )
        p.add_argument("--note", help="short note shown in the report")
        p.add_argument(
            "--verbose", action="store_true", help="show daemon logs in this terminal"
        )

    p = sub.add_parser("start", help="start tracking")
    p.add_argument("project_pos", nargs="?", metavar="PROJECT")
    p.add_argument("--project", "-p", help="project name (default: Default)")
    add_session_args(p, config.DEFAULT_INTERVAL)
    p.set_defaults(func=session.cmd_start)

    p = sub.add_parser(
        "switch", help="stop the current session and start another project"
    )
    p.add_argument("project")
    add_session_args(p, None)
    p.set_defaults(func=session.cmd_switch)

    p = sub.add_parser("stop", help="stop tracking and log the session")
    p.add_argument("--note", help="add a note to this session")
    p.add_argument(
        "--at", metavar="HH:MM", help="the session really ended at this time"
    )
    p.set_defaults(func=session.cmd_stop)

    p = sub.add_parser("status", help="show what is running and what is pending")
    p.set_defaults(func=session.cmd_status)

    p = sub.add_parser("review", help="accept or reject pending screenshots")
    p.add_argument("--project", "-p", help="only this project")
    p.add_argument("--date", type=valid_day, help="only this day, YYYY-MM-DD")
    p.add_argument("--today", action="store_true", help="only today")
    p.add_argument("--all", action="store_true", help="every pending screenshot")
    p.add_argument(
        "--terminal",
        action="store_true",
        help="use terminal prompts and your image viewer instead of the yad window",
    )
    p.set_defaults(func=review.cmd_review)

    p = sub.add_parser("report", help="build the one-page report (all days)")
    add_range_args(p)
    p.add_argument(
        "--embed",
        action="store_true",
        help="copy screenshots into the html so it is one shareable file",
    )
    p.add_argument(
        "--open", action="store_true", help="open the report in your browser"
    )
    p.add_argument(
        "--out", help="where to write it (default: <data>/reports/report.html)"
    )
    p.set_defaults(func=report.cmd_report)

    # serve
    p = sub.add_parser(
        "serve", help="serve the report over localhost (runs as a daemon)"
    )
    p.add_argument(
        "--host", default=None, help=f"bind address (default: {config.SERVE_HOST})"
    )
    p.add_argument(
        "--port", type=int, default=None, help=f"port (default: {config.SERVE_PORT})"
    )
    p.add_argument(
        "--report", help="report file to serve (default: <data>/reports/report.html)"
    )
    p.add_argument(
        "--build", action="store_true", help="regenerate the report before serving"
    )
    p.add_argument("--no-open", action="store_true", help="don't open the browser")
    p.add_argument(
        "--foreground",
        "-f",
        action="store_true",
        help="run in the foreground instead of as a daemon (Ctrl+C to stop)",
    )
    p.add_argument("--stop", action="store_true", help="stop the running server")
    p.add_argument(
        "--status", action="store_true", help="show whether the server is running"
    )
    p.set_defaults(func=serve.cmd_serve)

    p = sub.add_parser("summary", help="print totals in the terminal")
    add_range_args(p)
    p.set_defaults(func=summary.cmd_summary)

    p = sub.add_parser("delete", help="delete screenshots by file name")
    p.add_argument("filenames", nargs="+")
    p.set_defaults(func=summary.cmd_delete)

    d = sub.add_parser("_daemon")
    d.add_argument("interval", type=int)
    d.add_argument("--project", default="Default")
    d.add_argument("--mode", default=config.DEFAULT_MODE)
    d.set_defaults(func=lambda a: daemon.daemon_loop(a.interval, a.project, a.mode))

    s = sub.add_parser("_server")
    s.add_argument("--host", default=config.SERVE_HOST)
    s.add_argument("--port", type=int, default=config.SERVE_PORT)
    s.set_defaults(func=serve.cmd_server_daemon)

    args = parser.parse_args()
    ensure_dirs()
    args.func(args)
