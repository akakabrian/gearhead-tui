"""Modal screens — help / controls cheatsheet for the TUI re-shell.

Kept narrow. GearHead itself has extensive in-game help (press `?`
in any menu); these screens document the *shell* bindings that are
outside the engine.
"""
from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Static


_HELP = """\
[bold cyan]gearhead-tui — shell controls[/bold cyan]

The engine's own help is available by pressing [bold]?[/bold] inside
the game. These bindings are added by the Textual re-shell.

  [bold]ctrl+q[/bold]    — quit the shell (sends Q+Enter to the engine)
  [bold]ctrl+c[/bold]    — force quit (terminates engine subprocess)
  [bold]ctrl+h[/bold]    — this help screen
  [bold]ctrl+l[/bold]    — force-redraw
  [bold]tab[/bold]       — cycle side-panel focus

[bold]Movement[/bold] — vi keys (same as engine):
  h/j/k/l          — west, south, north, east
  y/u/b/n          — diagonals (nw, ne, sw, se)
  Arrow keys       — translated to h/j/k/l.

[bold]GearHead-specific[/bold]:
  s   — save / quit (in-game)
  i   — inventory
  e   — equipment
  ?   — in-game help

Press [bold]escape[/bold] or [bold]ctrl+h[/bold] to close this screen.
"""


class HelpScreen(ModalScreen):
    """Shell-level help overlay."""

    BINDINGS = [
        Binding("escape", "dismiss", "Close"),
        Binding("ctrl+h", "dismiss", "Close"),
        Binding("q", "dismiss", "Close"),
    ]

    DEFAULT_CSS = """
    HelpScreen {
        align: center middle;
    }
    HelpScreen > Container {
        width: 70;
        height: auto;
        padding: 1 2;
        border: thick $accent;
        background: $surface;
    }
    """

    def compose(self) -> ComposeResult:
        with Container():
            yield Static(_HELP, id="help-body")

    def action_dismiss(self) -> None:
        self.app.pop_screen()
