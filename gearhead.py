#!/usr/bin/env python3
"""Entry point for gearhead-tui.

Wires argparse → gearhead_tui.app.run(). Kept deliberately small so
programmatic callers can import `gearhead_tui.app.run` directly.
"""
from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="gearhead-tui",
        description="Textual re-shell over GearHead: Arena (GearHead 1).",
    )
    p.add_argument("--agent", type=int, default=None, metavar="PORT",
                   help="Start REST API on 127.0.0.1:PORT alongside the TUI.")
    p.add_argument("--headless", action="store_true",
                   help="Run engine + agent API, no TUI. Requires --agent.")
    p.add_argument("--cols", type=int, default=100,
                   help="Pty width (default 100).")
    p.add_argument("--rows", type=int, default=40,
                   help="Pty height (default 40).")
    args = p.parse_args(argv)

    if args.headless and args.agent is None:
        p.error("--headless requires --agent PORT")

    from gearhead_tui.app import run
    run(cols=args.cols, rows=args.rows, agent_port=args.agent,
        headless=args.headless)
    return 0


if __name__ == "__main__":
    sys.exit(main())
