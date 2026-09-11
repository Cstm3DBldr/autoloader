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
entry sensor clears
  └─► LOW: flag it on both UIs, KEEP the profile. Warning only.
        └─► keep printing
              └─► ENCODER GOES QUIET while the extruder is still pulling
                    │        the tail has passed this path's encoder -- MEASURED
                    │        (entry still triggered here = jam or break, not a
                    │         runout: different event, do not run this routine)
                    └─► budget = bowden_length_N, spend it minus the reserve
                          └─► PAUSE  ── reserve left: 50mm + sensor_to_gear
                                └─► go to purge position
                                      └─► purge until the EXTRUDER SENSOR
                                          CLEARS -- MEASURED, tail pinned
                                            └─► entry sensor?
                                                  ├─ triggered ─► park, normal
                                                  │   load, purge remaining + 50
                                                  │     └─► prompt: clean /
                                                  │         purge / resume /
                                                  │         cancel
                                                  └─ clear ────► HOLD. Arm the
                                                      reload on the sensor edge.
                                                      Filament goes in, the load
                                                      starts immediately.
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

## The things that decide whether this works

### 1. The pause must not let the monitor eat the profile

`_is_printing()` reads `print_stats.state == 'printing'`
(`autoloader.py:746-759`). During a `PAUSE` that state is `paused`, so
**`_is_printing()` returns False the moment we pause** — and the existing wipe
branch fires 10s later, deleting the profile we are standing there waiting to
reload against.

So `low` must be excluded from that branch **unconditionally**, not gated on
the print state. Gating on `_is_printing()` is the obvious fix and it is the
wrong one.

### 2. ~~The budget reserves more than 50mm~~ — SOLVED by where the encoder sits

**Confirmed 2026-09-11: the encoders are locked to their paths and cannot be
shared.** That is the reason the machine is built this way — fast loads, fast
unloads, and jam/break detection — and it removes this problem rather than
mitigating it.

Each encoder sits **downstream of the drive gear** (`SA_PARK` drives forward by
`encoder_to_gear_distance` to reach it, then retracts until it goes quiet,
`sa_sequences.py:302-311`). So the tail of a finished roll **passes its own
encoder on the way to the toolhead**, and the encoder going quiet while the
extruder is still pulling is a measured event.

That is a mid-tube datum nobody has to estimate:

```
entry sensor clears      ── roll ended. Rough warning only; the distance from
                            here to the gate is not modelled and no longer
                            needs to be.
      ↓
ENCODER GOES QUIET       ── MEASURED. The tail has passed the encoder.
                            Remaining = bowden_length_N + sensor_to_gear
                                        + nozzle_distance
      ↓
spend bowden_length_N minus the reserve, then PAUSE
      ↓
purge until the EXTRUDER SENSOR CLEARS   ── MEASURED again. Tail pinned.
                            Remaining = sensor_to_gear + nozzle_distance
```

Two measured datums and no unmodelled term. `bowden_length_N` is already
calibrated per path (1359–1517mm) and is already stored in that same encoder's
counts, so the budget and the measurement share one scale.

**Trigger the budget on the encoder going quiet, not on the entry sensor
clearing.** The entry sensor is the warning; the encoder is the clock.

### 3. `sensor_to_gear` is the safety margin, and nothing holds that number

The purge-to-clear must stop **on the sensor edge**. What is left after it is
`sensor_to_gear + nozzle_distance`, and only the first of those keeps the tail
in the gears. Overshoot it and the tail clears the gears, at which point
nothing in the machine can move it — that is `RECOVERY.md`, needing an
operator and a hot nozzle.

`nozzle_distance` is 50 and `fill_nozzle_length` is 50. `sensor_to_gear` is
not a parameter. It is now the only unmeasured distance left in this design.

## What the encoder can and cannot be asked

The counting callback is registered once at init (`sa_encoder.py:46`) and is
live whatever the machine is doing. But `_pulse_callback` adds
`mm_per_pulse * self._direction`, and `set_direction()` only *tells* it which
way to count — a single-channel optical encoder cannot sense direction.

**So the pulse COUNT is always right and the accumulated SIGN is only right if
something set it.** That divides the work cleanly:

| Question | Ask | Why |
|---|---|---|
| How much filament has the print used? | the **extruder's own position** | Signed and exact. The encoder cannot answer: with direction pinned forward every retraction counts as feed, so a retract/unretract pair adds ~2× the retract distance. At PrusaSlicer's default on thousands of retractions that is thousands of phantom mm — more than the whole tube. |
| Has the filament stopped moving? | the **encoder** | Direction-agnostic. With direction pinned, `get_distance()` accumulates *total absolute motion*, which is exactly the quantity to compare against the extruder's total absolute motion. |
| Is this a runout, or a jam or break? | the **entry sensor** | Encoder quiet while the extruder pulls means the filament is not moving. Entry clear → the roll ended, expected, run this routine. Entry still triggered → filament is present and not moving, which is a jam or a break, and is a different event. |

That last row is the jam/break detection the locked encoders exist for, and it
needs no new hardware — only the comparison.

Do **not** try to track net consumption by flipping `set_direction()` per move.
It would have to follow the extruder thousands of times a second and would lag
the motion it is trying to describe.

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
- **`sensor_to_gear` needs measuring.** It is the last unmeasured distance in
  the design and it is the one that keeps the tail inside the gears.
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
