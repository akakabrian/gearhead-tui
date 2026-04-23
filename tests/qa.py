"""QA harness — Textual Pilot scenarios.

Each scenario spawns a fresh GearheadApp (which owns its own engine
subprocess). Subprocess isolation is free with strategy 3 — the
engine's globals live in its own process.

Run all: .venv/bin/python -m tests.qa
Run a subset: .venv/bin/python -m tests.qa <pattern>
"""
from __future__ import annotations

import asyncio
import os
import re
import sys
import time
from dataclasses import dataclass
from typing import Callable, Awaitable

from gearhead_tui.app import (
    GearheadApp, GearheadView, PilotPanel, ControlsPanel,
    MechPanel, MessageLog,
)
from gearhead_tui.engine import GearheadEngine


Scn = Callable[[GearheadApp, "object"], Awaitable[None]]


@dataclass(slots=True)
class Scenario:
    name: str
    fn: Scn


# ---------------------------------------------------------------------------
# Helpers.

async def _wait_for(condition: Callable[[], bool], timeout: float = 3.0,
                    interval: float = 0.1) -> bool:
    """Poll `condition()` until True or `timeout` elapses."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        await asyncio.sleep(interval)
    return False


def _grid_text(app: GearheadApp) -> str:
    grid, _ = app.engine.snapshot()
    return "\n".join("".join(c.char for c in row) for row in grid)


# ---------------------------------------------------------------------------
# Scenarios.

async def scn_mount_clean(app: GearheadApp, pilot) -> None:
    """App mounts, all four panels + map exist, engine thread starts."""
    await pilot.pause(0.5)
    assert app.query("#map"), "#map missing"
    assert app.query("#pilot"), "#pilot missing"
    assert app.query("#mech"), "#mech missing"
    assert app.query("#controls"), "#controls missing"
    assert app.query("#log"), "#log missing"
    assert app.engine.is_running(), "engine thread didn't start"


async def scn_engine_paints_menu(app: GearheadApp, pilot) -> None:
    """Engine paints the main menu within ~3s."""
    ok = await _wait_for(lambda: "GearHead" in _grid_text(app), timeout=4.0)
    assert ok, "GearHead banner never appeared"
    text = _grid_text(app)
    assert "Quit Game" in text, "Quit Game menu item missing"
    assert "Start RPG Campaign" in text, "Start RPG Campaign missing"


async def scn_serial_bumps_on_paint(app: GearheadApp, pilot) -> None:
    """Serial counter advances as the engine paints."""
    s0 = app.engine.serial
    ok = await _wait_for(lambda: app.engine.serial > s0, timeout=3.0)
    assert ok, f"serial stuck at {s0}"


async def scn_key_forwards_to_engine(app: GearheadApp, pilot) -> None:
    """A direct character forwards to the engine and changes its grid.

    GH1's main-menu selection uses numpad-style '2' for down (see
    conmenus.pp::SelectMenu) — so we can assert that sending '2'
    bumps the serial because the engine repaints the highlighted
    item. This exercises the non-arrow keypath."""
    await _wait_for(lambda: "GearHead" in _grid_text(app), timeout=4.0)
    before = app.engine.serial
    await pilot.press("2")
    await pilot.press("2")
    await asyncio.sleep(0.4)
    assert app.engine.serial > before, (
        f"serial {before}→{app.engine.serial} — engine didn't react to '2'"
    )


async def scn_arrow_key_maps_to_vi(app: GearheadApp, pilot) -> None:
    """Arrow keys are translated to vi-style direction keys."""
    await _wait_for(lambda: "GearHead" in _grid_text(app), timeout=4.0)
    before = app.engine.serial
    await pilot.press("down")
    await asyncio.sleep(0.3)
    assert app.engine.serial > before, (
        "down arrow didn't register with engine"
    )


async def scn_help_screen_opens_and_closes(app: GearheadApp, pilot) -> None:
    """Ctrl+H opens the help modal, escape closes it."""
    await pilot.press("ctrl+h")
    await pilot.pause()
    # Screen stack should have two entries now.
    assert len(app.screen_stack) >= 2, "HelpScreen didn't push"
    await pilot.press("escape")
    await pilot.pause()
    assert len(app.screen_stack) == 1, "HelpScreen didn't pop on escape"


async def scn_pilot_panel_updates(app: GearheadApp, pilot) -> None:
    """Pilot panel's text mentions 'running' + 'yes' after engine starts."""
    # Let the 1 Hz refresh fire at least once.
    await asyncio.sleep(1.2)
    panel = app.query_one("#pilot", PilotPanel)
    # Static.render() returns the current content — a Rich renderable
    # (str or Text). Cast to str to search for tokens.
    text = str(panel.render())
    assert "running" in text.lower(), f"pilot panel has no 'running': {text!r}"
    # After the engine's started, we expect 'yes'.
    assert "yes" in text.lower(), f"pilot panel says engine not running: {text!r}"


async def scn_map_renders_cells(app: GearheadApp, pilot) -> None:
    """GearheadView renders cells with non-default style colors."""
    await _wait_for(lambda: "GearHead" in _grid_text(app), timeout=4.0)
    map_view = app.query_one("#map", GearheadView)
    strip = map_view.render_line(0)
    segs = list(strip)
    assert segs, "render_line produced no segments"
    # At least one segment should have real text (not just blanks).
    has_text = any(seg.text.strip() for seg in segs)
    # Row 0 is usually blank — walk a few rows.
    if not has_text:
        for y in range(min(20, app.engine.rows)):
            s = list(map_view.render_line(y))
            if any(seg.text.strip() for seg in s):
                has_text = True
                break
    assert has_text, "render_line produced no non-blank text across 20 rows"


async def scn_shutdown_no_zombie(app: GearheadApp, pilot) -> None:
    """App unmount kills the engine subprocess cleanly."""
    engine = app.engine
    assert engine.is_running(), "setup precondition: engine should be running"
    # Pilot's context manager exits after this returns — trigger the
    # same path as action_quit_game so the stop() runs before unmount.
    engine.stop(timeout=2.0)
    ok = await _wait_for(lambda: not engine.is_running(), timeout=3.0)
    assert ok, "engine still running after stop()"


# ---------------------------------------------------------------------------
# Harness.

SCENARIOS: list[Scenario] = [
    Scenario("mount_clean",                  scn_mount_clean),
    Scenario("engine_paints_menu",           scn_engine_paints_menu),
    Scenario("serial_bumps_on_paint",        scn_serial_bumps_on_paint),
    Scenario("key_forwards_to_engine",       scn_key_forwards_to_engine),
    Scenario("arrow_key_maps_to_vi",         scn_arrow_key_maps_to_vi),
    Scenario("help_screen_opens_and_closes", scn_help_screen_opens_and_closes),
    Scenario("pilot_panel_updates",          scn_pilot_panel_updates),
    Scenario("map_renders_cells",            scn_map_renders_cells),
    Scenario("shutdown_no_zombie",           scn_shutdown_no_zombie),
]


async def run_scenario(scn: Scenario) -> tuple[str, bool, str]:
    out_dir = "tests/out"
    os.makedirs(out_dir, exist_ok=True)
    app = GearheadApp(cols=100, rows=40)
    try:
        async with app.run_test(size=(180, 50)) as pilot:
            await pilot.pause(0.3)
            try:
                await scn.fn(app, pilot)
                app.save_screenshot(f"{out_dir}/{scn.name}.PASS.svg")
                return (scn.name, True, "")
            except AssertionError as e:
                app.save_screenshot(f"{out_dir}/{scn.name}.FAIL.svg")
                return (scn.name, False, f"AssertionError: {e}")
            except Exception as e:
                app.save_screenshot(f"{out_dir}/{scn.name}.ERROR.svg")
                return (scn.name, False, f"{type(e).__name__}: {e}")
    finally:
        # Belt + suspenders — ensure the engine's reaped even if the
        # Pilot harness bailed before on_unmount.
        try:
            app.engine.stop(timeout=1.0)
        except Exception:
            pass


async def main_async(pattern: str | None) -> int:
    scns = SCENARIOS
    if pattern:
        pat = re.compile(pattern)
        scns = [s for s in SCENARIOS if pat.search(s.name)]
        if not scns:
            print(f"no scenarios match '{pattern}'")
            return 1

    results: list[tuple[str, bool, str]] = []
    for scn in scns:
        print(f"» {scn.name:40s} ", end="", flush=True)
        result = await run_scenario(scn)
        results.append(result)
        _, ok, msg = result
        print("PASS" if ok else f"FAIL — {msg}")

    passes = sum(1 for _, ok, _ in results if ok)
    print()
    print(f"  {passes}/{len(results)} scenarios passed")
    return 0 if passes == len(results) else 1


def main() -> int:
    pattern = sys.argv[1] if len(sys.argv) > 1 else None
    return asyncio.run(main_async(pattern))


if __name__ == "__main__":
    sys.exit(main())
