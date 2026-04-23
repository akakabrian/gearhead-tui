"""PTY + pyte harness around the vendored GearHead: Arena binary.

GearHead 1's console mode uses Free Pascal's `crt` unit — on Linux this
emits standard vt100/ANSI sequences and reads keys from raw stdin. We
spawn the game in a pty, pump its output through `pyte.ByteStream` into
a `pyte.Screen`, and expose a thread-safe snapshot of that screen to
Textual.

Design highlights:

- **Worker thread owns the pty.** Reads block — we don't want them on
  the asyncio loop. A dedicated thread drains the pty into pyte at
  whatever pace the engine emits (usually bursty on turn changes).
- **Serial counter for redraw skip.** Bumps on every dirty-line event
  from pyte. Textual's render timer checks the serial; if unchanged,
  no paint.
- **Input is a bytestring.** We translate Textual keys to the byte
  sequences GearHead expects, then write them to the pty master.
- **Lifetime:** `start()` spawns, `stop()` sends `q` + a few escapes,
  waits briefly, then SIGKILLs if the process is still around. The
  daemon reader thread dies with the process.

The public surface is `GearheadEngine` — the App just calls
`start()`, reads `.grid` / `.serial` / `.running`, and pushes keys via
`post_key()`.
"""
from __future__ import annotations

import os
import select
import shutil
import signal
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import ptyprocess
import pyte


# ---------------------------------------------------------------------------
# Defaults tuned for GearHead 1.

DEFAULT_COLS = 100
DEFAULT_ROWS = 40

# Colour-palette fallback: if pyte hands us "default" for a cell, we use
# these. The engine writes white-on-black for most text and cyan for
# borders; defaults matter only while the screen is empty.
DEFAULT_FG = "white"
DEFAULT_BG = "black"


@dataclass(slots=True)
class Cell:
    """One character cell — public view for the TUI.

    `fg` / `bg` are colour *names* in pyte's lightweight scheme (one of
    the 16 ANSI colour names, `"default"`, or a 6-hex-digit string for
    palette-mapped entries). The rendering layer converts these to Rich
    `Color` objects with its own cache."""
    char: str = " "
    fg: str = DEFAULT_FG
    bg: str = DEFAULT_BG
    bold: bool = False
    reverse: bool = False


def _find_binary() -> Path:
    """Locate the vendored gharena binary. Raises if missing."""
    here = Path(__file__).resolve().parent
    repo = here.parent
    cand = [
        repo / "vendor" / "gearhead-1" / "gharena",
        repo / "vendor" / "gharena",
    ]
    for c in cand:
        if c.exists() and os.access(c, os.X_OK):
            return c
    raise FileNotFoundError(
        "gharena not built — run `make engine` from the repo root"
    )


class GearheadEngine:
    """Owns one GearHead pty subprocess and its VT parser.

    Callers: `e = GearheadEngine(); e.start(); …; e.stop()`. While
    running, `e.snapshot()` returns the current screen state, `e.serial`
    bumps on every change, and `e.post_key(b"l")` forwards input.

    The engine is single-use — once stopped, create a new instance.
    """

    def __init__(self, *, cols: int = DEFAULT_COLS, rows: int = DEFAULT_ROWS,
                 binary: Path | None = None) -> None:
        self.cols = cols
        self.rows = rows
        self.binary = binary or _find_binary()
        self._screen = pyte.Screen(cols, rows)
        self._stream = pyte.ByteStream(self._screen)

        # The pyte screen's internal state is not thread-safe — writes
        # and reads must both hold this lock.
        self._lock = threading.Lock()
        self._serial = 0

        # Last-known copy of the cells, refreshed by the reader thread
        # after each drain. Textual reads this without holding the
        # parser lock, which keeps per-row render_line calls cheap.
        self._grid: list[list[Cell]] = [
            [Cell() for _ in range(cols)] for _ in range(rows)
        ]

        self._pty: ptyprocess.PtyProcess | None = None
        self._thread: threading.Thread | None = None
        self._running = False
        self._die = False

        # Hook for notify-style events. Not used today — kept so the
        # App can register a death/victory callback later if we start
        # scraping the message line for "you died".
        self.on_notify: Callable[[str], None] | None = None

    # --- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        """Spawn the engine in a pty. Returns immediately."""
        if self._running:
            return
        self._running = True

        # GearHead expects to be launched from its own data directory —
        # it reads design files, game data, and saves from cwd. We
        # launch with that as cwd, but keep the binary path absolute.
        cwd = str(self.binary.parent)
        env = dict(os.environ)
        env["TERM"] = "xterm-256color"
        env["LINES"] = str(self.rows)
        env["COLUMNS"] = str(self.cols)

        self._pty = ptyprocess.PtyProcess.spawn(
            [str(self.binary)],
            cwd=cwd, env=env,
            dimensions=(self.rows, self.cols),
        )

        self._thread = threading.Thread(
            target=self._reader_loop, name="gearhead-pty-reader",
            daemon=True,
        )
        self._thread.start()

    def _reader_loop(self) -> None:
        """Drain pty output into pyte. Runs until the child exits."""
        pty = self._pty
        assert pty is not None
        fd = pty.fd

        while self._running and not self._die:
            # Use select to avoid tight spin when the engine is idle
            # waiting for a keypress.
            try:
                r, _, _ = select.select([fd], [], [], 0.1)
            except (OSError, ValueError):
                break
            if not r:
                continue
            try:
                data = pty.read(8192)
            except (OSError, EOFError):
                break
            if not data:
                break

            with self._lock:
                # pyte expects bytes for ByteStream. If we ever switch
                # to pyte.Stream (str), decode here — but ByteStream
                # handles the UTF-8/Latin-1 charset state internally.
                self._stream.feed(data)
                self._serial += 1
                self._snapshot_into_grid_locked()

        # Process ended — mark not-running so the UI can notice.
        self._running = False

    def _snapshot_into_grid_locked(self) -> None:
        """Copy pyte.Screen.buffer → self._grid. Caller holds _lock."""
        screen = self._screen
        buf = screen.buffer
        grid = self._grid
        for y in range(self.rows):
            row_src = buf[y]
            row_dst = grid[y]
            for x in range(self.cols):
                ch = row_src[x]
                # pyte.Char: (data, fg, bg, bold, italics, underscore,
                # strikethrough, reverse, blink). We only care about
                # char/fg/bg/bold/reverse.
                row_dst[x] = Cell(
                    char=ch.data or " ",
                    fg=ch.fg or DEFAULT_FG,
                    bg=ch.bg or DEFAULT_BG,
                    bold=bool(ch.bold),
                    reverse=bool(ch.reverse),
                )

    def stop(self, timeout: float = 2.0) -> None:
        """Best-effort shutdown.

        GearHead's main menu quits on a plain `q` + selecting "Quit
        Game" (which is the last menu item) + an 'Enter' confirmation.
        Mid-game quit is deeper in a menu tree. We send a conservative
        sequence of escapes + q + returns that should unwind most
        screens to the main menu and then out, and fall back to
        SIGTERM / SIGKILL if the process is still alive.
        """
        if not self._running or self._pty is None:
            return
        self._die = True
        # Try the polite exit first. Send each byte separately in case
        # the engine is mid-animation and eats a burst.
        for seq in (b"\x1b", b"\x1b", b"q", b"\r", b"y", b"\r"):
            try:
                self._pty.write(seq)
            except (OSError, EOFError):
                break
            time.sleep(0.05)

        # Wait for the process to exit politely.
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not self._pty.isalive():
                break
            time.sleep(0.05)

        # Escalate.
        try:
            if self._pty.isalive():
                self._pty.kill(signal.SIGTERM)
                time.sleep(0.1)
            if self._pty.isalive():
                self._pty.kill(signal.SIGKILL)
        except Exception:
            pass

        self._running = False
        # Best-effort join on the reader (daemon, so non-fatal if it hangs).
        if self._thread is not None:
            self._thread.join(timeout=0.5)

    # --- public state -----------------------------------------------------

    @property
    def serial(self) -> int:
        return self._serial

    @property
    def running(self) -> bool:
        if self._pty is None:
            return False
        try:
            return self._running and self._pty.isalive()
        except Exception:
            return False

    def is_running(self) -> bool:
        return self.running

    def snapshot(self) -> tuple[list[list[Cell]], int]:
        """Return a deep copy of the grid + the serial seen."""
        with self._lock:
            g = [[Cell(c.char, c.fg, c.bg, c.bold, c.reverse) for c in row]
                 for row in self._grid]
            return g, self._serial

    def cell_at(self, x: int, y: int) -> Cell:
        """Single-cell read, safe to call concurrently."""
        if not (0 <= x < self.cols and 0 <= y < self.rows):
            return Cell()
        with self._lock:
            c = self._grid[y][x]
            return Cell(c.char, c.fg, c.bg, c.bold, c.reverse)

    def row_copy(self, y: int) -> list[Cell]:
        """Copy one row for fast render_line. Cheap vs full snapshot."""
        if not (0 <= y < self.rows):
            return [Cell() for _ in range(self.cols)]
        with self._lock:
            row = self._grid[y]
            return [Cell(c.char, c.fg, c.bg, c.bold, c.reverse) for c in row]

    def cursor(self) -> tuple[int, int]:
        """Return the engine's current cursor position."""
        with self._lock:
            cur = self._screen.cursor
            return int(cur.x), int(cur.y)

    # --- input -----------------------------------------------------------

    def post_bytes(self, data: bytes) -> None:
        """Write raw bytes to the engine's stdin. No retry."""
        if self._pty is None or not self._running:
            return
        try:
            self._pty.write(data)
        except (OSError, EOFError):
            self._running = False

    def post_key(self, key: str | int | bytes) -> None:
        """Forward a single key to the engine.

        Accepts a str (single character or Textual key name we map),
        an int codepoint, or raw bytes. Arrow keys translate to
        GearHead's vi-style direction keys.
        """
        if isinstance(key, bytes):
            self.post_bytes(key)
            return
        if isinstance(key, int):
            self.post_bytes(bytes([key]))
            return
        # str path
        m = _KEY_MAP.get(key)
        if m is not None:
            self.post_bytes(m)
            return
        if len(key) == 1:
            self.post_bytes(key.encode("utf-8"))
            return
        # Unmapped multi-char key — drop silently.

    # --- derived state ---------------------------------------------------

    def message_line(self) -> str:
        """Return the topmost message row stripped of trailing whitespace.

        GearHead writes status messages at the top of the map zone
        (~row 2). Useful for the side-panel tail-log. The exact row
        can vary by screen — we scan the first 5 rows for the first
        non-blank one."""
        with self._lock:
            for y in range(min(5, self.rows)):
                row = self._screen.buffer[y]
                text = "".join((row[x].data or " ")
                               for x in range(self.cols)).rstrip()
                if text:
                    return text
            return ""


# Textual-key-name → bytes to send to GearHead.
#
# GearHead 1's console mode uses FPC's `crt` unit, which translates
# real ANSI arrow sequences (`ESC [ A` etc.) internally to the DOS-era
# two-byte `#0 + scancode` format expected by the keymap. The menus
# (`conmenus.pp`) look at the keymap's North/South bindings, which
# default to `'8'`/`'2'` — the numpad digits. In-game `PCAction`
# (movement) reads the same keymap for direction.
#
# So we want to send *real ANSI arrow sequences* for directional keys:
# they work in both menus and in-game through the single keymap path.
# Letters pass through as themselves (engine reads them via ReadKey),
# `Enter` → CR (`crt` converts to space internally via RPGKey), `Esc`
# → `\x1b`, `Backspace` → `\x08` (converted to ESC by RPGKey).
_KEY_MAP: dict[str, bytes] = {
    "enter":       b"\r",
    "return":      b"\r",
    "escape":      b"\x1b",
    "tab":         b"\t",
    "backspace":   b"\x08",
    "delete":      b"\x7f",
    "space":       b" ",
    "up":          b"\x1b[A",
    "down":        b"\x1b[B",
    "right":       b"\x1b[C",
    "left":        b"\x1b[D",
    "home":        b"\x1b[H",
    "end":         b"\x1b[F",
    "pageup":      b"\x1b[5~",
    "pagedown":    b"\x1b[6~",
    "insert":      b"\x1b[2~",
    "f1":          b"\x1bOP",
    "f2":          b"\x1bOQ",
    "f3":          b"\x1bOR",
    "f4":          b"\x1bOS",
    # Ctrl+L → form-feed; many terminal programs treat it as "repaint".
    "ctrl+l":      b"\x0c",
}
