"""Stage-2 smoke: spawn GearHead, wait for menu paint, print top rows.

Success criterion (gate): the binary launches, pyte parses something,
and the main menu text ("GearHead Arena" and the menu items) appears
in the grid within a few seconds.

Run: .venv/bin/python -m tests.smoke_engine
"""
from __future__ import annotations

import sys
import time

from gearhead_tui.engine import GearheadEngine


def main() -> int:
    e = GearheadEngine()
    e.start()
    try:
        # Give the engine a moment to paint its menu.
        deadline = time.monotonic() + 4.0
        last_serial = -1
        while time.monotonic() < deadline:
            time.sleep(0.2)
            if e.serial != last_serial:
                last_serial = e.serial
            # Check if "GearHead" text has appeared anywhere.
            g, _ = e.snapshot()
            hit = any("GearHead" in "".join(c.char for c in row) for row in g)
            if hit:
                break

        g, serial = e.snapshot()
        print(f"serial={serial} running={e.running}")
        # Print a trimmed view of the first 20 rows (center of the menu).
        for y, row in enumerate(g[:25]):
            line = "".join(c.char for c in row).rstrip()
            if line:
                print(f"{y:2d} | {line}")

        # Search for menu markers.
        text = "\n".join("".join(c.char for c in row) for row in g)
        assert "GearHead" in text, "GearHead banner missing from grid"
        assert "Quit Game" in text or "Start" in text, "menu items missing"
        print()
        print("smoke OK — menu text present.")
        return 0
    finally:
        e.stop()


if __name__ == "__main__":
    sys.exit(main())
