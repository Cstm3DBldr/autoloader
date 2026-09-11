# Mid-print runout — spend the tail, pause on a budget, swap on a datum

**Status: design note. Nothing is built.** Written 2026-09-10, revised
2026-09-11 to Mike's sequence, which is safer than the first draft and drops
the infill targeting entirely.

It changes what `docs/RECOVERY.md` is for. Recovery is what you do *after* the
tail is somewhere nothing can drive it. This is how the machine never gets
there.

## What happens today

The entry sensor clears on a loaded path. After `runout_timeout` (10s) the
state monitor sets the path `empty` and **wipes the filament profile**
(`autoloader.py:636-645`), whether or not a print is running.

Mid-print that is wrong twice over. The path still holds a Bowden length of
good filament — 1359–1517mm on this machine — and the print keeps consuming
it. And the profile it deletes is the only record of what is in the head,
which is exactly what the reload needs to pick a temperature.

## The sequence

```
entry clears
  └─► LOW: flag it, KEEP the profile, start the budget
        └─► keep printing until the budget is spent
              └─► PAUSE  ── reserve left: 50mm + sensor-to-gear
                    └─► go to purge position
                          └─► purge until the EXTRUDER SENSOR CLEARS   ◄── datum
                                └─► entry sensor?
                                      ├─ triggered ──► park, normal load,
                                      │                purge remaining + 50
                                      │                    └─► prompt: clean /
                                      │                        purge / resume /
                                      │                        cancel
                                      └─ clear ─────► HOLD. Arm the reload on
                                                      the sensor edge. Filament
                                                      goes in, load starts
                                                      immediately.
```

### Why purge to the sensor rather than load behind the old filament

**It converts an estimate into a measurement.** Purging until the extruder
sensor clears pins the tail at a known point, so the final purge is a constant
— `sensor_to_gear + nozzle_distance` — instead of accumulated tracking error.
The budget only has to get the tail *near* the sensor; the sensor does the
rest.

This is the gate-exit datum argument again, and it is what the wasted filament
buys: every other way of knowing where the tail is, is arithmetic.

It also means the new tip meets a **clean forward-pushed end**, not a break —
which is the one failure in `RECOVERY.md`'s table that no sensor can catch,
because a tip wedging alongside a jagged break reads as normal motion.

## The three things that decide whether this works

### 1. The pause must not let the monitor eat the profile

`_is_printing()` reads `print_stats.state == 'printing'`
(`autoloader.py:746-759`). During a `PAUSE` that state is `paused`, so
**`_is_printing()` returns False the moment we pause** — and the existing wipe
branch fires 10s later, deleting the profile we are standing there waiting to
reload against.

So `low` must be excluded from that branch **unconditionally**, not gated on
the print state. Gating on `_is_printing()` is the obvious fix and it is the
wrong one.

### 2. The budget reserves more than 50mm, and nothing says how much

"Tube length minus 50" reserves `(entry sensor → gate) + 50`, not 50. The tail
starts *at the entry sensor* and has to cross that segment before it even
enters the Bowden.

That segment is **not modelled anywhere** — it is the run from each spool
position to the carriage, and it differs per path. The error is in the safe
direction (pause earlier, never later) but it is paid for twice: filament left
unused, and a proportionally longer purge-to-sensor into the bucket. If it is
300mm, we pause with 350mm still in the tube and purge all of it.

### 3. `sensor_to_gear` is the safety margin, and nothing holds that number either

The purge-to-clear must stop **on the sensor edge**. What is left after it is
`sensor_to_gear + nozzle_distance`, and only the first of those keeps the tail
in the gears. Overshoot it and the tail clears the gears, at which point
nothing in the machine can move it — that is `RECOVERY.md`, needing an
operator and a hot nozzle.

`nozzle_distance` is 50 and `fill_nozzle_length` is 50. `sensor_to_gear` is
not a parameter.

## The encoder may delete problem 2 entirely

There are **six independent encoders**, one per path, each with its own pin
and its own calibrated `mm_per_pulse` (`hardware.cfg:109-131`). And
`register_buttons` is called once in `__init__` (`sa_encoder.py:46`), so the
counting callback is **always live** — every pulse accumulates whatever the
machine is doing, including mid-print with the drive disengaged.

CLAUDE.md's architecture diagram still describes "Drive Encoder (single, on
drive gear output shaft)". The hardware says six. One of those is stale.

**If each encoder wheel rides its own path's filament permanently, then the
budget is not arithmetic at all — it is measured**, entry→gate stops mattering,
and the countdown shown in the UI is a reading rather than an estimate.

Two things to confirm before relying on it, one physical and one in code:

- does the wheel stay in contact when the carriage is parked at another path?
- `set_direction()` only *tells* the encoder which way to count
  (`sa_encoder.py:98`) — a single-channel optical encoder cannot sense
  direction. Anything counting during a print has to own that sign, and a
  retraction would count as feed.

## The waiting reload — use the queue that already exists

"Like we queued it up waiting on it" is already built.
`_queue_park` / `_drain_park_queue` (`autoloader.py:661-745`) polls the entry
sensor from the state monitor, serialises requests, holds them behind a
calibration, and re-checks the sensor before acting because the spool may have
been pulled back out.

It exists because `insert_gcode` is the wrong mechanism, and the reason is
written down: `RunoutHelper` only fires when `idle_timeout.state != "Printing"`,
which any gcode sets, and it consumes the edge before that check returns — two
spools inserted quickly lost the second park outright. **Do not reach for
`insert_gcode` here.** Dispatch the armed reload through this queue.

One detail: `_drain_park_queue` skips work when `_is_printing()`. Paused reads
False, so it would run — which is what we want, except it would run a plain
`SA_PARK`. The armed reload has to take priority over an ordinary park on that
path rather than racing it.

## Still open

- `runout_purge_extra` — the 50mm of new filament. A parameter, not a
  constant: old and new do not separate cleanly in the melt, so how much it
  takes to come out clean is a material property. The error is asymmetric —
  under-purge puts old colour in the print, over-purge costs a few mm into the
  bucket. Round up.
- What the hotend does while the machine holds paused waiting for a spool.
  This design deliberately parks a stationary remnant in a hot nozzle, so a
  cooldown-and-reheat policy is now required rather than optional.
- Whether `low` should exclude that tool from the toolchanger for the rest of
  the print.
- Whether the purge position is the existing `SA_CLEAN_NOZZLE` /
  `PARK_ON_COOLING_PAD` pair or something dedicated.

## Dropped from the first draft

Pausing in infill. Klipper cannot see `;TYPE:` — `klippy/gcode.py:206-208`
cuts every comment before dispatch, and the current sliced file (PrusaSlicer
2.9.4) carries 7585 of them and emits zero `SET_PRINT_STATS_INFO`, so there is
no feature type and no layer number in-process. It would have needed Moonraker
to index the file by byte offset, and it still could not hit a precise point
because of the lookahead buffer. The budget pause is simpler and does not need
any of it.
