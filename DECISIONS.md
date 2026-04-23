# gearhead-tui — design decisions

## Upstream

- **Engine:** [GearHead: Arena (GearHead 1)](https://github.com/jwvhewitt/gearhead-1)
  by Joseph Hewitt. Free Pascal, **LGPL 2.1+** (friendlier than GPL — our
  wrapper isn't forced to be GPL, but we match LGPL for the whole repo to
  keep things simple). Vendored at `vendor/gearhead-1/`.
- **Why GH1 and not GH2 (Arena/Space):** GH1 is 15 MB, 56 `.pp` units, has
  a clean `{$IFDEF SDLMODE} … {$ELSE}` split with a fully-featured
  console path (`congfx` / `conmap` / `conmenus` / `coninfo`) that writes
  through Free Pascal's standard `crt` unit. GH2 is ~40% larger, its
  console path is less exercised, and Arena (GH2) requires more data
  assets. GH1's console build produces a static 1.1 MB ELF that renders
  the full game in a terminal on first run. That's exactly what we want
  to re-shell.
- **Already terminal-native.** FPC's `crt` emits vt100/ANSI sequences on
  Linux (cursor positioning, colour, ClrScr) and reads keyboard via
  raw stdin. GearHead console mode is, essentially, already a text-UI
  mainframe program. The job is to reshape its viewport, not to
  reimplement its renderer.

## Binding strategy — subprocess + pty + pyte VT parser

Three options were on the table (per the skill):

1. **Build as a library via CFFI.** Not viable without deep surgery — GH1
   is a program, not a library, and the Pascal/C FFI story isn't as
   clean as C↔Python. `rogueMain()`-style entry refactor would require
   patching dozens of `.pp` units.
2. **Platform-shim replacement.** Replace the `crt` calls in `congfx` /
   `conmap` / `conmenus` / `coninfo` with a thin wrapper that funnels
   to Python. Cleaner than #1 but still requires patching ~4 Pascal
   units and building a custom shared library loadable from Python.
   Brogue chose the equivalent strategy (`py-platform.c`) and it works
   — but Brogue already had a `brogueConsole` abstraction (six function
   pointers). GH1 has no such abstraction; the Pascal units call `crt`
   directly dozens of times.
3. **Subprocess in pty, VT parse with `pyte`.**  GearHead already emits
   clean, deterministic ANSI escape sequences (FPC `crt` on Linux has a
   very narrow repertoire: cursor up/down, `ClrScr`, `[38;5;Nm`
   colour, `[H` home). `pyte.Screen` is a battle-tested VT100 parser
   that maintains an (x,y) → (char, fg, bg) grid. **We ship this.**

Strategy 3 was flagged as "simpler but fragile" in the skill. It's
fragile when scraping raw text off tools that print unpredictable ANSI
(shell prompts, log output with colour embedded mid-word). GearHead's
output is very regular — `crt` only paints character cells — and `pyte`
handles the entire VT100 surface. We get no false robustness penalty
over strategy 2 because the engine isn't going to start printing
things we can't parse: `crt` is that narrow.

**Deferred:** if strategy 3 hits a real wall (input edge cases, ncurses
mode, terminal resize), we can fall back to strategy 2 by writing a
custom `crt`-shaped unit and re-linking. We keep that option open by
shipping the Makefile with both a vendored build **and** a
`ppc-for-repatch` target. Not today.

## Dimensions

- GH1 expects a **minimum 80×25** terminal. The default layout uses
  extra rows/cols if available: sidebar zones position via negative
  offsets from the right edge. We default the pty winsize to **100×40**
  to give the info/menu panes breathing room, and the Textual MapView
  just renders whatever pyte says.
- We spawn with `TERM=xterm-256color` so colour pairs come through as
  indexed palette bytes that pyte can map to RGB.

## TUI layout (target)

- **Map pane (main)** — full pty screen as rendered by GearHead. One
  `GearHeadView` ScrollView widget that iterates pyte's `screen.buffer`
  on each paint. ~30 Hz redraw when the engine serial bumps.
- **Side panels (Textual-side chrome)**
  - *Pilot* — name, class, skill summary (scraped from the engine's
    info pane once per second via known zone offsets).
  - *Mech* — current gear, armour, HP bars. Same pattern.
  - *Controls cheatsheet* — static help.
- **Message log** — tail of the engine's message area, scrollable.
- **Dynamic title bar** — depth / HP / status string, pulled from pyte.

## Render contract

- `engine.start()` spawns GearHead in a pty (via `ptyprocess` or
  `pexpect`) on a worker thread. Worker loops reading bytes and pumps
  them into `pyte.Stream` → `pyte.Screen`.
- A serial counter bumps every time the screen changes.
- Textual's `MapView.render_line(y)` reads pyte's `buffer[y]` under a
  lock and builds a `Strip` from `(char, fg, bg)` tuples.
- Style cache keyed on `(fg, bg)` — GH1 uses the 16-colour palette
  overwhelmingly (~30 pairs total), so cache hit rate is ~99%.

## Input contract

- Textual captures keys via `on_key`. Arrow keys → vi-style
  `h/j/k/l/y/u/b/n` (GH1 accepts both, but vi is canonical). Letters /
  digits forward as-is. `Escape` / `Enter` / `Space` / `Backspace` pass
  through.
- Ctrl+C handled at the App level — Textual's own quit binding. We
  separately send `Q` + `y` to the engine stdin so GearHead saves +
  exits cleanly.

## Save / load

- GearHead owns this. Its main menu has "Load RPG Campaign" and
  in-game saves are triggered by ordinary keystrokes. Nothing for us
  to wrap.

## QA harness

- Textual `App.run_test` + `Pilot` — pattern from brogue-tui. Scenarios:
  mount clean, cursor moves, menu navigation, map paints after new
  game, quit flow doesn't leave a zombie pty.
- **Subprocess isolation:** each scenario spawns a fresh GearHead
  subprocess via a fresh App. GearHead's global state lives entirely
  in its own process, so cross-scenario contamination is impossible.
  That's one of the nicer side-effects of strategy 3.

## REST API

- Same pattern as brogue-tui / simcity-tui. `aiohttp` on a background
  task, endpoints:
  - `GET /health` — ok + uptime
  - `GET /state` — {depth, hp, gold, running, serial, cursor}
  - `GET /snapshot` — the full pyte grid as JSON
  - `POST /key {k}` — forward keystroke to engine
- CLI: `--agent PORT` starts the API alongside the TUI; `--headless`
  runs engine + API with no TUI (for agents).

## Open questions parked for later

- Does GearHead emit any non-ANSI / non-pyte-handled sequences? The
  smoke test says no for the main menu, but in-game map draws might
  use high-bit characters (box-drawing). FPC `crt` emits them as Latin-1
  / CP437 depending on build; we handle that via pyte's charset state.
- Does the pty buffer have to be drained continuously, or is periodic
  polling fine? Real GearHead is turn-based — there's no animation
  timer flooding the pipe — so periodic reads should suffice, but we
  run a dedicated reader thread to be safe.
