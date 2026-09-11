# Mid-print runout — warn, finish the tail, pause somewhere safe, swap

**Status: design note. Nothing is built.** Written 2026-09-10 alongside
`docs/RECOVERY.md`, and it changes what that note is for: recovery is what
you do *after* the tail is somewhere nothing can drive it. This is how the
machine avoids getting there.

## What happens today

The entry sensor clears on a loaded path. After `runout_timeout` (10s) the
state monitor sets the path `empty` and **wipes the filament profile**
(`autoloader.py:636-645`). It does that whether or not a print is running.

Mid-print that is wrong twice over. The path still holds a Bowden length of
perfectly good filament — 1359–1517mm on this machine — and the print keeps
consuming it. And the profile it just deleted is the only record of what
material is in the head, which is exactly what the swap needs to pick a
temperature.

## The shape

```
entry clears ──► LOW  ──► keep printing, count down ──► pause ──► swap ──► resume
                 │                                       │
          flag + profile KEPT              before the tail reaches the gears
```

### 1. Flag, do not empty

A new state between `loaded` and `empty` — call it `low`. Entry clear + path
loaded + `_is_printing()` → `low`, profile **kept**. The existing wipe branch
stays exactly as it is for the not-printing case, which is a spool being
pulled by hand and is a different event.

Both UIs already render `path_states` and both already have a per-path colour
treatment, so the flag costs one state and one status field. The remaining
length goes in the status object next to it so the panels can show a countdown
rather than a binary.

### 2. Count down the tail

Remaining at the moment entry clears, along the path:

| Segment | Source | This machine |
|---|---|---|
| entry sensor → gate | **not modelled — new parameter** | unknown |
| gate → extruder sensor | `bowden_length_N`, measured | 1359–1517 |
| extruder sensor → toolhead sensor | not modelled; sensor-terminated dead zone | unknown |
| toolhead sensor → nozzle tip | `fill_nozzle_length` | 50 |

Consumption comes off the active extruder's own position, not
`print_stats.filament_used` — that is one figure for the whole print and this
is a six-extruder machine.

**The estimate predicts; the sensors referee.** The extruder sensor clearing
is a hard fact and re-zeros the countdown when it happens. Two of the four
segments above are unmeasured, so the countdown is only ever good enough to
pick a pause point early — it is never the thing that decides the path is
finished. Same split as the encoder against the ruler.

### 3. Pause — and the floor that actually matters

**Hard floor: pause no later than the extruder sensor clearing.** Past that
the tail is in the gears, and once it clears them nothing in the machine can
move it — the extruder can only push what it grips. That is the state
`docs/RECOVERY.md` exists for, and it needs an operator and a hot nozzle.

So the value of this feature is not convenience. It is that a runout stops
producing unrecoverable states at all, and `RECOVERY.md` narrows to what it
should always have been: a filament that genuinely snapped mid-tube.

**Where in the model** is the open question — see the fork below.

### 4. Swap and purge

1. `PAUSE` — parks the head, Klipper's own state capture.
2. Prompt: which tool, what was in it (from the kept profile), load a spool.
3. Blast the new roll down the Bowden at the calibrated speed.
4. Push the new tip against the remnant and purge:

   **purge = tracked_remaining + `runout_purge_extra`**, default 20mm.

   A parameter, not a constant. The old and new are not separated by a sharp
   boundary in the melt — they smear — so how much new it takes to come out
   clean is a property of the materials and wants tuning. The error is also
   asymmetric: under-purging puts the old colour in the print, over-purging
   costs a few mm into the bucket. Round up.
5. `SA_CLEAN_NOZZLE`, operator confirms the colour is clean, `RESUME`.

**The existing sensor-terminated helpers do not work here as written.**
`_sync_feed_to_toolhead_sensor` terminates when the toolhead sensor fires —
and with a remnant still in the head that sensor is *already* triggered, so it
would return instantly having fed nothing. The arriving-new-tip signal in this
scenario is the **extruder** sensor going from clear to filament. Anything
past the gears has to be driven by distance, because both sensors beyond that
point are held by filament that is already there.

## The fork — what I need decided

**Does the pause target infill, or land where it lands?**

*Land where it lands* is Klipper-only and small: pause a fixed margin before
the extruder sensor clears. Correct, robust, done in a day. The pause lands on
whatever the head happened to be printing.

*Target infill* needs the Moonraker component to index the file's `;TYPE:`
blocks by byte offset and watch `virtual_sdcard.file_position`, because
Klipper cannot see the markers (`klippy/gcode.py:206-208` strips every comment
before dispatch; the current file carries 7585 of them and Klipper receives
none). Bigger, and it cannot hit a precise point — the lookahead buffer means
a PAUSE lands seconds of motion after it is issued, so the target is the start
of a long infill block with the overshoot staying inside it.

The backbone — flag, keep the profile, count down, pause before the gears,
purge by measurement — is identical either way and does not wait on this.

## Open questions

- **entry sensor → gate distance.** Per-path, since each spool sits at its own
  distance from the carriage. Only shifts where the warning starts, never
  correctness, so a global estimate with a margin may be enough — but it is a
  number nothing currently holds.
- Whether `low` should refuse a new print start, or only warn.
- What happens if the operator ignores the pause for an hour. The hotend is
  hot with a stationary remnant in it.
- Whether a path that has gone `low` should be excluded from the toolchanger's
  available tools for the rest of the print.
