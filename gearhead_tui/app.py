"""Textual application — re-shell over GearHead: Arena.

Layout is four-panel per the skill's canonical shape:

    +---------+-----------------------------------+--------+
    | pilot   |                                   | mech   |
    |         |       GearheadView (map)          |        |
    +---------+                                   +--------+
    | ctrls   |                                   |        |
    +---------+--------------+--------------------+--------+
                             | MessageLog                  |
                             +-----------------------------+

The map is the whole engine-rendered pty — GearHead already paints
its menus, combat screen, character sheet, and maps into the same
80-col region so we don't try to second-guess zones. Side panels are
small, stable, and scraped from the engine grid at 1 Hz (not 30 Hz,
since they only change on big state transitions).
"""
from __future__ import annotations

from rich.color import Color
from rich.segment import Segment
from rich.style import Style
from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.geometry import Size
from textual.scroll_view import ScrollView
from textual.strip import Strip
from textual.widgets import Footer, Header, RichLog, Static

from .engine import Cell, GearheadEngine
from .screens import HelpScreen


# ---------------------------------------------------------------------------
# Colour translation — pyte uses colour *names* ("red", "brightgreen",
# "cyan", "default") plus 6-hex strings for true-colour entries. We map
# names to the standard 8/16-colour palette and let Rich hex-parse
# everything else.

_PALETTE: dict[str, tuple[int, int, int]] = {
    "default":      (221, 221, 221),   # engine fg default
    "black":        (0, 0, 0),
    "red":          (205, 0, 0),
    "green":        (0, 205, 0),
    "brown":        (205, 205, 0),
    "yellow":       (255, 255, 85),
    "blue":         (0, 0, 238),
    "magenta":      (205, 0, 205),
    "cyan":         (0, 205, 205),
    "white":        (229, 229, 229),
    "brightblack":  (127, 127, 127),
    "brightred":    (255, 0, 0),
    "brightgreen":  (0, 255, 0),
    "brightbrown":  (255, 255, 0),
    "brightyellow": (255, 255, 0),
    "brightblue":   (92, 92, 255),
    "brightmagenta": (255, 0, 255),
    "brightcyan":   (0, 255, 255),
    "brightwhite":  (255, 255, 255),
}
_DEFAULT_BG = (0, 0, 0)


def _colour(name: str, *, is_bg: bool) -> tuple[int, int, int]:
    if name in _PALETTE:
        return _PALETTE[name]
    # pyte occasionally hands us 6-hex strings for palette-mapped
    # colour escapes. Accept both with and without the leading '#'.
    s = name.lstrip("#")
    if len(s) == 6:
        try:
            return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))
        except ValueError:
            pass
    # 3-hex fallback.
    if len(s) == 3:
        try:
            return (int(s[0]*2, 16), int(s[1]*2, 16), int(s[2]*2, 16))
        except ValueError:
            pass
    return _DEFAULT_BG if is_bg else _PALETTE["default"]


# ---------------------------------------------------------------------------
# Main map view — the scroll_view that mirrors pyte's grid.

class GearheadView(ScrollView):
    """Renders the engine's pty-parsed grid via `render_line`."""

    can_focus = True

    def __init__(self, engine: GearheadEngine, **kw) -> None:
        super().__init__(**kw)
        self.engine = engine
        self._last_serial = -1
        self.virtual_size = Size(engine.cols, engine.rows)
        # Cache for assembled Styles keyed on (fg, bg, bold, reverse).
        # GH1 uses ~30 distinct pairs in most screens — hit rate > 99%.
        self._style_cache: dict[tuple[str, str, bool, bool], Style] = {}
        self._blank_style = Style(color="rgb(221,221,221)", bgcolor="rgb(0,0,0)")

    def on_mount(self) -> None:
        # Poll every 33 ms. A ScrollView re-paints only dirty regions,
        # so refresh() on a serial bump is cheap — ~1 ms for the whole
        # viewport at 100×40.
        self.set_interval(1 / 30, self._maybe_refresh)

    def _maybe_refresh(self) -> None:
        s = self.engine.serial
        if s != self._last_serial:
            self._last_serial = s
            self.refresh()

    def _style_for(self, cell: Cell) -> Style:
        key = (cell.fg, cell.bg, cell.bold, cell.reverse)
        style = self._style_cache.get(key)
        if style is not None:
            return style
        fg = _colour(cell.fg, is_bg=False)
        bg = _colour(cell.bg, is_bg=True)
        if cell.reverse:
            fg, bg = bg, fg
        style = Style(
            color=Color.from_rgb(fg[0], fg[1], fg[2]),
            bgcolor=Color.from_rgb(bg[0], bg[1], bg[2]),
            bold=cell.bold or None,
        )
        self._style_cache[key] = style
        return style

    def render_line(self, y: int) -> Strip:
        scroll_y = int(self.scroll_offset.y)
        world_y = y + scroll_y
        engine = self.engine
        if world_y < 0 or world_y >= engine.rows:
            return Strip.blank(self.size.width, self._blank_style)

        row = engine.row_copy(world_y)

        # Run-length compress identical-style runs into Segments.
        segments: list[Segment] = []
        cur_style: Style | None = None
        cur_text: list[str] = []
        for cell in row:
            style = self._style_for(cell)
            ch = cell.char if cell.char else " "
            if len(ch) != 1:
                # Wide / combining — keep alignment with a fallback.
                ch = " "
            if style is cur_style:
                cur_text.append(ch)
            else:
                if cur_style is not None:
                    segments.append(Segment("".join(cur_text), cur_style))
                cur_style = style
                cur_text = [ch]
        if cur_style is not None:
            segments.append(Segment("".join(cur_text), cur_style))

        strip = Strip(segments)
        scroll_x = int(self.scroll_offset.x)
        return strip.crop(scroll_x, scroll_x + self.size.width)


# ---------------------------------------------------------------------------
# Side panels. Each is a Static with a `refresh_panel()` driven off a
# 1 Hz timer. They scrape text from the pyte grid — the engine paints
# its own sidebar at cols ~70-99 in most screens, and we mirror the
# bits we care about into Textual-native chrome.

class SidePanel(Static):
    """Base for the pilot / mech / controls panels. Subclass and
    override `_build_lines(grid)`."""

    DEFAULT_CSS = ""

    def __init__(self, engine: GearheadEngine, title: str, **kw) -> None:
        super().__init__("", **kw)
        self.engine = engine
        self._title = title
        self.add_class("side")

    def on_mount(self) -> None:
        self.border_title = self._title
        self.set_interval(1.0, self._refresh_panel)
        self._refresh_panel()

    def _refresh_panel(self) -> None:
        try:
            grid, _ = self.engine.snapshot()
            lines = self._build_lines(grid)
        except Exception as e:
            lines = [f"[red]error:[/red] {e}"]
        self.update("\n".join(lines))

    # Overridden by subclasses.
    def _build_lines(self, grid: list[list[Cell]]) -> list[str]:
        return []


def _strip(row: list[Cell]) -> str:
    return "".join(c.char for c in row).rstrip()


class PilotPanel(SidePanel):
    """Shell-side pilot info. Stage 3 just reports that the engine is
    alive — later phases scrape the character info zone."""

    def _build_lines(self, grid: list[list[Cell]]) -> list[str]:
        lines = ["[bold cyan]pilot[/bold cyan]", ""]
        lines.append(f"[dim]running[/dim]   "
                     f"{'[green]yes[/green]' if self.engine.running else '[red]no[/red]'}")
        lines.append(f"[dim]serial[/dim]    {self.engine.serial}")
        lines.append(f"[dim]cursor[/dim]    {self.engine.cursor()}")
        lines.append("")
        # First 2 lines of non-blank text from the right-hand info zone
        # (roughly cols 70-99). Good-enough placeholder until we wire
        # the proper zone parser in Phase B.
        lines.append("[dim]engine info[/dim]")
        seen = 0
        for y, row in enumerate(grid[:20]):
            right = row[70:] if len(row) > 70 else row
            txt = _strip(right)
            if txt and txt not in ("Start RPG Campaign", "Quit Game"):
                lines.append(f"  {txt[:26]}")
                seen += 1
                if seen >= 6:
                    break
        return lines


class MechPanel(SidePanel):
    """Shell-side mech status. Stage 3 placeholder."""

    def _build_lines(self, grid: list[list[Cell]]) -> list[str]:
        lines = ["[bold cyan]mech[/bold cyan]", ""]
        lines.append("[dim]not yet wired[/dim]")
        lines.append("")
        lines.append("Phase B will scrape the")
        lines.append("engine's mech status zone")
        lines.append("(cols 0-60 during combat).")
        return lines


class ControlsPanel(SidePanel):
    """Static controls cheatsheet."""

    def _build_lines(self, grid: list[list[Cell]]) -> list[str]:
        return [
            "[bold cyan]controls[/bold cyan]",
            "",
            "[bold]hjkl[/bold]  move cardinal",
            "[bold]yubn[/bold]  move diagonal",
            "[bold]enter[/bold]  select",
            "[bold]esc[/bold]    cancel / back",
            "[bold]?[/bold]      engine help",
            "",
            "[bold]ctrl+h[/bold]  shell help",
            "[bold]ctrl+q[/bold]  quit",
            "[bold]ctrl+l[/bold]  redraw",
        ]


class MessageLog(RichLog):
    """Tail of the top-of-screen message line, de-duplicated."""

    DEFAULT_CSS = ""

    def __init__(self, engine: GearheadEngine, **kw) -> None:
        super().__init__(max_lines=500, **kw)
        self.engine = engine
        self._last_msg = ""

    def on_mount(self) -> None:
        self.border_title = "messages"
        self.set_interval(0.5, self._refresh_log)

    def _refresh_log(self) -> None:
        try:
            msg = self.engine.message_line()
        except Exception:
            return
        if msg and msg != self._last_msg:
            self._last_msg = msg
            self.write(msg)


# ---------------------------------------------------------------------------

class GearheadApp(App):
    """Main Textual application."""

    CSS_PATH = "tui.tcss"
    TITLE = "gearhead-tui"
    SUB_TITLE = "Textual re-shell over GearHead: Arena"

    BINDINGS = [
        Binding("ctrl+c", "force_quit", "Force Quit", priority=True, show=False),
        Binding("ctrl+q", "quit_game", "Quit", show=True),
        Binding("ctrl+h", "show_help", "Help", show=True),
        Binding("ctrl+l", "redraw", "Redraw", show=True),
    ]

    def __init__(self, *, cols: int = 100, rows: int = 40,
                 agent_port: int | None = None) -> None:
        super().__init__()
        self.engine = GearheadEngine(cols=cols, rows=rows)
        self.agent_port = agent_port
        self._agent_runner = None

    # --- layout -----------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="body"):
            with Vertical(id="left"):
                yield PilotPanel(self.engine, "pilot", id="pilot")
                yield ControlsPanel(self.engine, "controls", id="controls")
            with Vertical(id="center"):
                yield GearheadView(self.engine, id="map")
                yield MessageLog(self.engine, id="log")
            yield MechPanel(self.engine, "mech", id="mech")
        yield Footer()

    # --- lifecycle --------------------------------------------------------

    def on_mount(self) -> None:
        self.engine.start()
        self.query_one("#map", GearheadView).focus()
        if self.agent_port is not None:
            self.run_worker(self._start_agent(), exclusive=True)

    async def _start_agent(self) -> None:
        from . import agent_api
        assert self.agent_port is not None
        port = self.agent_port
        try:
            self._agent_runner, _site = await agent_api.serve(
                self.engine, port=port,
            )
            self.notify(f"agent API on 127.0.0.1:{port}")
        except OSError as e:
            self.notify(f"agent API failed to bind: {e}", severity="warning")

    def on_unmount(self) -> None:
        try:
            self.engine.stop(timeout=1.5)
        except Exception:
            pass
        if self._agent_runner is not None:
            try:
                self.run_worker(self._agent_runner.cleanup(), exclusive=True)
            except Exception:
                pass

    # --- actions ----------------------------------------------------------

    def action_show_help(self) -> None:
        self.push_screen(HelpScreen())

    def action_redraw(self) -> None:
        # Ask the engine to repaint by nudging it with ctrl+L (clear +
        # redraw). GearHead's `crt` layer handles this on most screens.
        self.engine.post_bytes(b"\x0c")
        self.refresh()

    def action_quit_game(self) -> None:
        # Politely tell the engine to quit; on_unmount will escalate.
        try:
            self.engine.stop(timeout=1.0)
        finally:
            self.exit()

    def action_force_quit(self) -> None:
        # Ctrl+C — skip the polite exit, just bail.
        self.exit()

    # --- input forwarding -------------------------------------------------

    def on_key(self, event: events.Key) -> None:
        if event.key in ("ctrl+c", "ctrl+q", "ctrl+h", "ctrl+l"):
            # App-level bindings take these; don't forward to engine.
            return
        self.engine.post_key(event.key if event.key else (event.character or ""))
        event.stop()

    def on_click(self, event: events.Click) -> None:
        # GearHead console mode doesn't handle mouse — drop clicks on
        # the map. Shell-level widget clicks (side panels) work normally.
        try:
            widget, _ = self.get_widget_at(event.x, event.y)
        except Exception:
            return
        if not isinstance(widget, GearheadView):
            return
        event.stop()


def run(*, cols: int = 100, rows: int = 40,
        agent_port: int | None = None,
        headless: bool = False) -> None:
    """Entry point. gearhead.py calls this."""
    if headless:
        # Headless mode: start engine + agent API, block on sigint.
        # No TUI, no Textual. Useful for letting an agent drive the
        # game over REST while the human does something else.
        import asyncio

        async def _headless() -> None:
            from . import agent_api
            engine = GearheadEngine(cols=cols, rows=rows)
            engine.start()
            assert agent_port is not None
            runner, _ = await agent_api.serve(engine, port=agent_port)
            print(f"gearhead-tui headless: agent API on 127.0.0.1:{agent_port}")
            print("ctrl+c to quit.")
            try:
                while engine.running:
                    await asyncio.sleep(0.5)
            except KeyboardInterrupt:
                pass
            finally:
                engine.stop(timeout=1.5)
                await runner.cleanup()

        asyncio.run(_headless())
        return

    GearheadApp(cols=cols, rows=rows, agent_port=agent_port).run()
