# "Timer too close" — the running record

Every `MCU '<board>' shutdown: Timer too close` on this printer, with what was
happening and what it turned out to be. Mike, 2026-10-13: "start making notes
of the timer too close logs and what you find".

**This file is the record, not the logs.** Klipper keeps about ten rotated
`klippy.log` files, so an event is gone within days — the 2026-09-06 and
2026-09-11 ones already were by 2026-10-13. When one happens:

1. `FIRMWARE_RESTART` recovers it.
2. Run `bash ~/autoloader/scripts/timer_too_close_report.sh` on the printer —
   read-only, one block per event: board, session, host load, CAN error
   counters, when Python's garbage collector last ran, and the commands just
   before.
3. Add a row below, and a line under "What it was" once it is understood.

## What the message means

The board was handed a command scheduled for a moment that had already passed
when it arrived. Klipper's own hint is "the host computer is overloaded", but
anything that makes a message late does it: the host stalling (CPU frequency
change, garbage collection, a burst of disk writes), or the CAN path delaying
it. It is a safety stop, not a bug — the board refuses to act late — so the fix
is always on the side of whatever made the message late.

## Machine baseline, 2026-10-13

Checked so a change can be spotted later.

| | Value |
|---|---|
| CAN | `can0` 1,000,000 bit/s, `txqueuelen` 128 (Klipper's recommendation), ERROR-ACTIVE, no bus errors, drops or bus-off since boot |
| Bridge | Manta M8P as USB-to-CAN bridge (`gs_usb`); its kernel messages line up with our own firmware restarts, nothing spontaneous |
| Boards on the bus | `mcu` (bridge), `autoloader` (MMB CAN), `et0`-`et5` (EBB36 toolheads) |
| Host | Raspberry Pi CM4, kernel 6.1.21-v8+, `vcgencmd get_throttled` = `0x0` (no undervoltage or throttling since boot), 37°C, swap unused |
| CPU governor | `ondemand` — the one item not at the usual recommendation (`performance`). Left as is by decision; see "Open threads" |

## Events

| Date | Board | What was running | Host load | CAN errors | Last GC before it |
|---|---|---|---|---|---|
| 2025-10-20 | `et1`, the active toolhead | G28, Z probing with Tap (three probe samples) — the Happy Hare setup, before this project. A second shutdown 11s later during the restart. | 0.22 | none | gen0 ~1s before |
| 2026-09-06 | `autoloader` | not recorded — log rotated away (noted in CLAUDE.md) | — | — | — |
| 2026-09-11 | `autoloader` | two auto-parks queued in the same second, the drain homing the selector back to back (CLAUDE.md; log gone) | — | — | — |
| 2026-10-09 | `autoloader` | Klipper starting: six separate `variables.cfg` rewrites at boot while KlipperScreen restarted | 0.65 | none | gen1 ~0.1s before |
| 2026-10-12 | `et0`, the active toolhead | G28 at the start of an `SA_UNLOAD` (X/Y homing currents just set; probing not yet reached) | 0.12 | none | gen1 ~1.2s before |

## What it was

- **Autoloader board, under a burst of host work** (09-06, 09-11, 10-09).
  Fixed in code: startup state writes batched into one rewrite, and the park
  queue drains one park per callback with a settle between. Not seen since
  2026-10-09.
- **The active toolhead's board, during G28** (2025-10-20 et1, 2026-10-12 et0).
  Same shape a year apart, the first before this project existed — so not
  caused by the extruder-sensor endstops added 2026-10-11. Homing across
  boards over CAN (Tap's probe on the toolhead board stopping motors on the
  main board) is the most timing-sensitive thing Klipper does. Two in a year.

## Ruled out

- CAN bus faults: no rx/tx errors or retries on any board at any event.
- Host overload in the ordinary sense: load 0.11-0.65, memory free, no swap.
- Undervoltage / throttling: `0x0` since the last boot (2026-10-10 16:17,
  after that day's mains outages — so the outages themselves are not covered).

## Open threads

- **CPU governor `ondemand`.** The CPU idles down and has to ramp up when work
  arrives; homing straight after an idle spell is the classic case. Setting
  `performance` is the common advice, but unproven here and, at two events a
  year, unprovable quickly. Decision 2026-10-13: leave it; revisit if the
  toolhead-during-G28 kind comes back.
- **Garbage collection.** In all three events with a log, a collection had run
  within ~1-1.5s before the shutdown. Suggestive, not evidence — gen0 runs
  every few seconds anyway. Keep recording the `gc:` line; it becomes evidence
  only if the gap is consistently tiny.
- **The autoloader's own cross-board homing.** The sensor-stopped blast
  (2026-10-11) stops the drive on the autoloader board from a sensor on a
  toolhead board — the same mechanism. It has run dozens of times clean. If it
  ever hits this, Klipper reports "Communication timeout during homing" for
  the move and the blast falls back to the polled one rather than shutting
  down.
