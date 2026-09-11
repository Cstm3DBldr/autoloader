# Systems test — 2026-09-10

First full run of the eleven-step guide on rebuilt hardware, start to finish
through the Mainsail panel. Every value below was measured on the machine.

## What changed in hardware

- **All six encoder wheels reprinted** in ASA (unchanged material) on a better
  printer. The old ones rubbed their housings, wore thin and shed dust into
  the optical slot, which blocked the eye intermittently — the wheel reads as
  stopped while it is turning.
- **Engage servo replaced**: TowerPro MG90S → Spektrum SX108. Both analog;
  +37% stall torque (30.55 → 41.8 oz-in at 6V) and dual bearings instead of a
  bushing. The MG90S was weakening under repeated cycles, which let the drive
  gear slip on the filament under load.

Both faults were real. Neither alone explained the readings.

## The result

**Encoder speed ceiling, per path** — the question the rebuild existed to
answer. `variables.cfg` stores the 80% safe speed; the maxima are given here.

| Path | Before | After | |
|---|---|---|---|
| T0 | 175 | **200** | |
| T1 | 100 | **200** | |
| T2 | **50** | **200** | 4x |
| T3 | 175 | **200** | |
| T4 | **50** | **215** | 4.3x |
| T5 | 150 | **200** | |

Spread went from **3.5x** (50–175) to **1.075x** (200–215). The pass criterion
written down before the rebuild was "six ceilings close to each other, not any
single number" — that is what happened, and the two paths that were worst are
now indistinguishable from the rest.

Shared speed is the slowest path's: **160mm/s** safe, up from 40mm/s. That
figure is the minimum of the six by design and rises on its own; it was never
stale.

T4 reaching 215 while the rest stop at 200 is the finer ladder earning itself.
The rungs used to jump 200 -> 250, so anything in that band was recorded as
200 and the real edge was invisible.

## Saved values

```
                     mm/pulse    safe speed    bowden (mm)   selector (mm)
  T0                  0.96555        160.0        1516.56        0.00
  T1                  0.95825        160.0        1487.52       24.69   (re-run, see below)
  T2                  0.96155        160.0        1453.22       49.38
  T3                  0.96706        160.0        1430.93       74.07
  T4                  0.96881        160.0        1390.24       98.76
  T5                  0.95892        172.0        1359.11      123.45

  drive_rotation_distance  5.6911
  servo_engaged_angle      100.0     (was 160.0 with the MG90S)
  servo_disengaged_angle    10.0
  encoder_max_speed        160.0     shared = slowest path
  encoder_edges_0..5           2     both edges counted
```

All twelve sensor checks and the endstop check pass and are recorded:
`endstop_ok`, `entry_sensor_ok_0..5`, `toolhead_sensor_ok_0..5` all True.

**The servo angle moved 160 -> 100.** The numbers in the config are not
degrees — `maximum_servo_angle: 180` against a 1000-2000us pulse range is
Klipper's default mapping, not either servo's real travel. They are scale
points, and a different servo lands somewhere else entirely. This is why
`SA_CALIBRATE_SERVO` has to run on a servo swap.

## Open, from this run

- ~~T1's `mm_per_pulse` looks 1.4% low~~ **RESOLVED same day.** It was the
  outlier at 0.94334 against 0.95892–0.96881. `SA_VERIFY_FEED TOOL=1 SPEED=25
  DIST=200` gave commanded 200.0 / ruler 198.0 / encoder 195.3, predicting
  0.9564 once scaled. Re-running `SA_CALIBRATE_ENCODER TOOL=1` produced
  **0.95825** — inside 0.2% of that, and inside the family. Spread across the
  six went 2.7% -> 1.1%. `bowden_length_1` was re-measured after it
  (1451.49 -> 1487.52), which is required: Bowden length is stored in encoder
  counts, so a changed scale invalidates it.

  **The calibration is not circular** and cannot be fooled by a wrong starting
  value. With n counts, stored m and true M: the encoder reports n·m, the
  ruler measures n·M, ratio = M/m, and new = m × M/m = M. One pass lands on
  the truth however wrong it started — which is why all three passes run at
  `original_mpp` rather than feeding each other.

  So the error was the one thing in the loop that is not arithmetic: the
  datum. For the result to come out LOW the ruler must read short, which is a
  tip sitting inside the gate when it was called flush — 1.6% of a 300mm datum
  is 4.8mm. All three passes agreed (the >4% spread check passed), so it was
  systematic rather than scatter: something about judging flush at that gate,
  or a diagonally cut tip. This is the known floor of the method, already
  written down in CLAUDE.md — "eyeballing a tip flush and reading a rule is a
  fixed few mm, which is 3% of a 100mm feed and 1% of a 300mm one".

- **That verify's own verdict is wrong and should be softened.** It reported an
  "ENCODER ceiling … counts start going missing around 25mm/s". At 25mm/s a
  state spans about 0.94mm, so 37ms, which is ~19 of Klipper's 2ms samples —
  aliasing cannot happen there, and the sweep's whole design rests on that
  being true. Its derived "0.05mm active window" also contradicts the wheel
  geometry measured off the STL (12 slots, 45% open). The residual is far more
  likely scale error plus ruler scatter: eyeballing a tip flush is a fixed
  ±1mm, which is ±0.5% on a 200mm datum, and two such readings differ by
  about the 1.4% seen.

- **`drive_rotation_distance` is unchanged at 5.6911.** Either step 7 was not
  re-run or it landed on the same figure. The ruler read 198.0 against a
  commanded 200.0 in the verify above, which is 1% and worth a second look —
  if several paths report the same residual it is the drive, one fix rather
  than six.

- **All six paths are in `partial` state** after the run, since step 8 now
  parks each one as it finishes.

## The sequence, proved — 2026-09-11

Two full loads through to the nozzle. `SA_LOAD TOOL=0` first, then
`SA_LOAD TOOL=1` on the faster blast.

**T1, blast at the calibrated 160mm/s** (`encoder_max_speed`, no second
derate). Every figure below is off the console.

| Stage | Encoder | Against | |
|---|---|---|---|
| grip confirmed | 6.71 | — | |
| blast commanded | 1451.1 | `(1487.52 x 0.98) - 6.71` = 1451.06 | exact |
| blast complete | 1442.2 | 1457.77 expected | -1.07% |
| at extruder sensor | 1481.5 | `bowden_length_1` 1487.52 | **-0.40%** |
| sync feed to toolhead sensor | 40.0 | — | new measurement |

**The Bowden calibration holds at 160mm/s to 0.40%.** It was measured at a
slower speed, so this is the figure that says the faster blast did not
invalidate it.

**The 1.07% at blast end is the encoder under-reading, and the approach phase
absorbs it.** That is what the approach is for: the blast is deliberately cut
at 98% of the Bowden and the last stretch runs to a *sensor*, not to a count.
An encoder that reads 1% light at speed changes how far the approach has to
go and nothing else. Terminating the load on an encoder count instead would
have made this a 15mm error.

**New: extruder sensor to toolhead sensor is 40.0mm** — the sync feed drove
that far before the toolhead sensor fired. Granularity is `feed_step_size`
(10mm), so the true figure is 30-40mm. The extruder gears sit between those
two sensors, which **bounds `sensor_to_gear` below 40mm** — the last
unmeasured distance in `docs/RUNOUT_MIDPRINT.md`.

Blast time: 9.1s for 1451mm. The load ran 12:10 to 12:13 including homing, a
toolchange, heating to 200C, a 60mm extra purge and a park.
