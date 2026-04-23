"""Hot-path perf baselines.

Prints ms/op numbers so we can tell what actually moves the needle
before and after optimisations. Runs headlessly — no Textual needed.

Run: .venv/bin/python -m tests.perf
"""
from __future__ import annotations

import statistics
import sys
import time

from gearhead_tui.engine import GearheadEngine


def bench(name: str, fn, iters: int) -> None:
    # Warm one pass.
    fn()
    t0 = time.perf_counter()
    for _ in range(iters):
        fn()
    t1 = time.perf_counter()
    per_ms = (t1 - t0) * 1000 / iters
    print(f"  {name:35s}  {per_ms:8.4f} ms/op   ({iters}×)")


def main() -> int:
    print("gearhead-tui perf baseline")
    print("=" * 60)
    e = GearheadEngine(cols=100, rows=40)
    e.start()
    # Let the engine reach a stable menu state before benching.
    time.sleep(1.2)

    # 1. Full snapshot — copies the whole 100×40 grid under the lock.
    bench("snapshot() full grid", lambda: e.snapshot(), iters=500)

    # 2. Single-row copy — what render_line calls.
    bench("row_copy() one row",   lambda: e.row_copy(10), iters=5000)

    # 3. Single-cell read.
    bench("cell_at()",            lambda: e.cell_at(50, 20), iters=5000)

    # 4. Message-line scrape.
    bench("message_line()",       lambda: e.message_line(), iters=2000)

    # 5. Cursor read.
    bench("cursor()",             lambda: e.cursor(), iters=5000)

    # 6. Serial read (lock-free fast path).
    bench("serial",               lambda: e.serial,   iters=50000)

    # 7. End-to-end key round-trip — send a byte, wait for serial bump.
    def key_rt() -> None:
        s0 = e.serial
        e.post_bytes(b"2")
        deadline = time.perf_counter() + 0.5
        while e.serial == s0 and time.perf_counter() < deadline:
            time.sleep(0.001)
    bench("post '2' + wait for repaint", key_rt, iters=30)

    # 8. Full TUI render path — assemble Segments for every row once.
    # Load lazily so perf.py can run without Textual for contributors
    # who just want numbers.
    from gearhead_tui.app import GearheadView, _colour  # noqa: F401
    from rich.style import Style
    from rich.color import Color
    from rich.segment import Segment

    cache: dict = {}
    def render_all_rows() -> None:
        for y in range(e.rows):
            row = e.row_copy(y)
            segments = []
            cur = None
            buf: list[str] = []
            for cell in row:
                key = (cell.fg, cell.bg, cell.bold, cell.reverse)
                style = cache.get(key)
                if style is None:
                    fg = _colour(cell.fg, is_bg=False)
                    bg = _colour(cell.bg, is_bg=True)
                    if cell.reverse:
                        fg, bg = bg, fg
                    style = Style(
                        color=Color.from_rgb(*fg),
                        bgcolor=Color.from_rgb(*bg),
                        bold=cell.bold or None,
                    )
                    cache[key] = style
                ch = cell.char or " "
                if style is cur:
                    buf.append(ch)
                else:
                    if cur is not None:
                        segments.append(Segment("".join(buf), cur))
                    cur = style
                    buf = [ch]
            if cur is not None:
                segments.append(Segment("".join(buf), cur))
    bench("full 40-row render pass",  render_all_rows, iters=200)
    print(f"  style-cache size: {len(cache)}")

    e.stop()
    print()
    print("done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
