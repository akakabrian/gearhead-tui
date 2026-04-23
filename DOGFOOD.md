# DOGFOOD — gearhead

_Session: 2026-04-23T13:17:29, driver: pty, duration: 3.0 min_

**PASS** — ran for 1.8m, captured 26 snap(s), 1 milestone(s), 0 blocker(s), 0 major(s).

## Summary

Ran a rule-based exploratory session via `pty` driver. Found no findings worth flagging. Game reached 98 unique state snapshots. Captured 1 milestone shot(s); top candidates promoted to `screenshots/candidates/`. 1 coverage note(s) — see Coverage section.

## Findings

### Blockers

_None._

### Majors

_None._

### Minors

_None._

### Nits

_None._

### UX (feel-better-ifs)

_None._

## Coverage

- Driver backend: `pty`
- Keys pressed: 799 (unique: 24)
- State samples: 127 (unique: 98)
- Score samples: 0
- Milestones captured: 1
- Phase durations (s): A=81.2, B=9.6, C=18.1
- Snapshots: `/home/brian/AI/projects/tui-dogfood/reports/snaps/gearhead-20260423-131538`

Unique keys exercised: /, 3, :, ?, H, R, ], c, down, enter, escape, h, left, n, p, question_mark, r, right, shift+slash, space, up, v, w, z

### Coverage notes

- **[CN1] Phase B exited early due to saturation**
  - State hash unchanged for 10 consecutive samples during the stress probe; remaining keys skipped.

## Milestones

| Event | t (s) | Interest | File | Note |
|---|---|---|---|---|
| first_input | 0.3 | 0.0 | `gearhead-20260423-131538/milestones/first_input.txt` | key=right |
