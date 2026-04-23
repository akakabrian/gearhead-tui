# gearhead-tui

A Textual re-shell over **GearHead: Arena** (GearHead 1) — Joseph
Hewitt's open-source mecha roguelike RPG, written in Free Pascal.

This is a companion repo to `brogue-tui` / `simcity-tui`: we vendor the
canonical engine, build it from source, and run it in a pty with a
`pyte`-parsed mirror feeding a Textual UI. See **DECISIONS.md** for
the full rationale on why subprocess+pty instead of a platform shim.

## Quickstart

```bash
# Linux (Mint / Ubuntu / Debian):
sudo apt install fpc                 # Free Pascal Compiler (~50 MB)

git clone <this repo> gearhead-tui
cd gearhead-tui
make all                             # bootstrap + engine + venv
make run                             # launch the TUI
```

`make all` does three things:

1. `bootstrap` — shallow-clones GearHead 1 into `vendor/gearhead-1/`.
2. `engine` — compiles `gharena` in console mode via FPC (~1 s).
3. `venv` — sets up a local Python venv with Textual / aiohttp / pyte.

## Usage

```bash
make run                 # TUI only
make headless            # engine + REST API on :8770, no TUI
.venv/bin/python gearhead.py --agent 8770     # TUI + REST API
```

**Shell controls** (layer on top of the engine's own bindings):

| Key | Action |
| -- | -- |
| `ctrl+h` | Shell help modal |
| `ctrl+q` | Polite quit — sends `Q`/`Enter` to the engine then exits |
| `ctrl+c` | Force quit — kills engine subprocess immediately |
| `ctrl+l` | Repaint |

Everything else (hjkl, arrows, enter, space, letters, digits) passes
through to GearHead as-is. Arrow keys are forwarded as real ANSI
sequences, which FPC's `crt` translates into the scancodes GearHead's
keymap expects.

## REST API

When launched with `--agent PORT` (or `make headless`):

```
GET  /health           → {"ok": true, "running": bool, "serial": int}
GET  /state            → {running, serial, cursor, message, cols, rows}
GET  /snapshot         → {serial, cols, rows, rows_data: [[char,fg,bg,flags]×cols]×rows}
POST /key  {"k":"..."} → {"ok": true}     — key: any Textual key name or single char
```

## Testing

```bash
make test        # TUI QA + API QA + perf baseline  (~90 s)
make test-only PAT=panel   # subset of TUI scenarios by regex
make test-api    # just the REST API suite  (~3 s)
make test-perf   # perf numbers only
make playtest    # real-binary screenshot artefacts → tests/out/
```

Current suite: **12 TUI scenarios + 7 API scenarios**, all green.

## Perf baseline

On an HP ProDesk G4 (Linux Mint, x86_64):

| path | ms/op |
| -- | -- |
| full grid snapshot (100×40) | 1.4 |
| single row copy | 0.03 |
| single cell read | < 0.001 |
| full render pass (40 rows → Segments) | 1.8 |
| end-to-end key → repaint round-trip | 4.0 |

Style cache holds 4 entries after menu warmup (> 99% hits).

## Architecture at a glance

```
┌─────────────────── Textual App (asyncio) ───────────────────┐
│  GearheadApp                                                │
│   ├─ Header / Footer                                         │
│   ├─ PilotPanel / MechPanel / ControlsPanel   (1 Hz refresh)│
│   ├─ GearheadView (ScrollView, render_line)   (30 Hz poll)  │
│   └─ MessageLog  (RichLog)                    (0.5 Hz)      │
└──────────────────────────────────────────────────────────────┘
              │ post_key(bytes)             ↑ snapshot() / serial
              ↓                              │
┌────────────── GearheadEngine (threading) ──────────────────┐
│  ptyprocess.PtyProcess      reader thread                  │
│        │  read() bytes  ─► pyte.ByteStream ─► pyte.Screen   │
│        ↑  write() bytes ◄──                                 │
│                                     │ under lock            │
│                                     ↓                       │
│                            self._grid[y][x] = Cell(...)     │
└──────────────────────────────────────────────────────────────┘
              │ subprocess stdin/stdout via pty master/slave
              ↓
┌────────────── vendor/gearhead-1/gharena (FPC) ──────────────┐
│  GearHead: Arena — unmodified LGPL console build            │
└──────────────────────────────────────────────────────────────┘
```

## Licensing

GearHead is LGPL 2.1+. Our wrapper code is also LGPL 2.1+ to match.
The vendored engine stays in its own directory with the original
`license.txt`; we don't redistribute sources from this repo by default
(the `.gitignore` excludes `vendor/`), so `make bootstrap` pulls a
fresh copy from upstream on demand.

## Status

- Stage 1 research — ✅
- Stage 2 engine bindings (subprocess+pty, pyte) — ✅
- Stage 3 TUI scaffold — ✅
- Stage 4 QA harness (12 scenarios) — ✅
- Stage 5 perf baseline — ✅
- Stage 6 robustness — ✅
- Stage 7 phased polish — partial (REST API + playtest shipped; sound /
  LLM advisor / graphs deferred)

## Upstream

- GearHead 1 source: https://github.com/jwvhewitt/gearhead-1
- GearHead RPG (game site): https://gearheadrpg.com/
