"""Real-binary playtest — drive the shell for a few seconds, save an SVG.

This is the "did it regress end-to-end?" test. Launches a fresh
GearheadApp, lets the menu paint, navigates a few items with arrow
keys (which GH accepts in both menus and in-game), opens the help
modal, and saves a screenshot.

Run: .venv/bin/python -m tests.playtest
"""
from __future__ import annotations

import asyncio
import os
import sys
import time

from gearhead_tui.app import GearheadApp


async def run() -> int:
    out_dir = "tests/out"
    os.makedirs(out_dir, exist_ok=True)

    app = GearheadApp(cols=100, rows=40)
    async with app.run_test(size=(180, 55)) as pilot:
        await pilot.pause(0.3)

        # Wait for the banner to paint.
        deadline = time.monotonic() + 4.0
        while time.monotonic() < deadline:
            g, _ = app.engine.snapshot()
            if any("GearHead" in "".join(c.char for c in r) for r in g):
                break
            await asyncio.sleep(0.2)

        app.save_screenshot(f"{out_dir}/playtest_01_menu.svg")

        # Walk the menu with arrows and screenshot intermediate states.
        for i in range(3):
            await pilot.press("down")
            await asyncio.sleep(0.2)
        app.save_screenshot(f"{out_dir}/playtest_02_menu_scrolled.svg")

        # Open help modal.
        await pilot.press("ctrl+h")
        await pilot.pause(0.2)
        app.save_screenshot(f"{out_dir}/playtest_03_help.svg")

        await pilot.press("escape")
        await pilot.pause(0.2)

        # Save the "final" view as the canonical artefact.
        app.save_screenshot(f"{out_dir}/playtest_latest.svg")

        print(f"playtest OK — artefacts in {out_dir}/")
        print(f"  serial={app.engine.serial}  running={app.engine.is_running()}")
    # Context manager handles shutdown.
    return 0


def main() -> int:
    return asyncio.run(run())


if __name__ == "__main__":
    sys.exit(main())
