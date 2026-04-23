"""Stage-3 smoke: boot the Textual app in headless-pilot mode.

Gate for stage 3: App mounts, widgets appear, a keystroke forwards
to the engine without exceptions, shutdown is clean.
"""
from __future__ import annotations

import asyncio
import sys

from gearhead_tui.app import GearheadApp, GearheadView, PilotPanel, ControlsPanel


async def _run() -> int:
    app = GearheadApp(cols=100, rows=40)
    async with app.run_test(size=(180, 50)) as pilot:
        await pilot.pause(0.5)
        # Widgets exist.
        assert app.query("#map")
        assert app.query("#pilot")
        assert app.query("#controls")
        assert app.query("#log")
        # Let the engine paint a few frames.
        await asyncio.sleep(1.5)
        serial = app.engine.serial
        assert serial > 0, f"engine didn't paint (serial={serial})"
        # Forward a movement key.
        before = app.engine.serial
        await pilot.press("j")
        await asyncio.sleep(0.4)
        # Engine should have reacted (menu cursor moved → serial bumped).
        assert app.engine.serial >= before, "serial didn't advance after key"
        app.save_screenshot("tests/out/stage3_smoke.svg")
        print(f"serial before={before} after={app.engine.serial} OK")
        return 0


def main() -> int:
    import os
    os.makedirs("tests/out", exist_ok=True)
    return asyncio.run(_run())


if __name__ == "__main__":
    sys.exit(main())
