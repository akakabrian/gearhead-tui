"""gearhead-tui — Textual re-shell over GearHead: Arena (GearHead 1).

The engine lives in a subprocess (`vendor/gearhead-1/gharena`) we spawn
in a pty. Output is VT100-parsed by `pyte` into a cell grid that the
Textual UI mirrors. See `DECISIONS.md` for why this strategy (3) over
library-build (1) or platform-shim (2).
"""
from __future__ import annotations

__version__ = "0.1.0"
