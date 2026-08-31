# Systems test — 2026-08-30

Baseline capture taken before any further work, after the LED session.
Matching config snapshot: branch `printer-backup/known-good-2026-08-30`.

Deployed commit `77989d9` · Klipper `v0.13.0-411-g938300f3` ·
Moonraker `v0.9.3-128-g960e933` · KlipperScreen `v0.4.6-11-g6b6f63b6` ·
Mainsail `v2.14.0`. All three services active, Klippy ready.

## Verdict

**Nothing is broken.** Two behaviours were reported as failures and both
turned out to be the system correctly refusing to act on filament that is not
there. See "What actually happened" below.

---

## Machine state at capture

| | |
|---|---|
| `homed_axes` | `''` — XYZ not homed |
| selector | not homed (`current_path -1`, `selector_position -1.0`) |
| active tool | T3 |
| servo | disengaged |
| `cal_state` | empty |
| print state | standby |

## Sensors vs stored state

| Path | entry | extruder | toolhead | `path_state` |
|---|---|---|---|---|
| 0 | False | True | True | empty |
| 1 | False | True | True | empty |
| 2 | False | True | True | empty |
| 3 | False | True | True | empty |
| 4 | False | False | False | empty |
| 5 | False | False | False | empty |

Raw Klipper `filament_switch_sensor` objects were queried directly and agree
with the autoloader status object, so the reading path is correct.

**Physical explanation (confirmed by Mike):** filament was manually unloaded
and cut when the printer was moved. The cut stubs are still sitting in the
toolheads of paths 0–3; the autoloader paths themselves are genuinely empty.
Every sensor reading above is therefore accurate, and `path_state = empty` is
the correct description of the autoloader's own paths.

---

## What actually happened

### `SA_PARK` — correct refusal, not a fault

`SA_PARK TOOL=0` responds
`SA: No filament at entry of path 0 — nothing to park.`

`park_filament()` gates on the entry sensor before doing anything. With no
filament at the entry there is nothing for the drive gear to grip, so
returning is right. Feed filament into the entry and it will park normally.

### Toolhead parking — never actually blocked

Initially recorded as broken because `homed_axes` is empty and `_park()`
issues `G0` moves. That was wrong: both `do_load()` and `do_unload()` call
`_is_homed()` and run `G28` themselves before reaching `_park()`, so the
unhomed state resolves itself. `park_filament()` does not call `_park()` at
all — parking at the encoder is selector and drive work only and never needed
homing.

### `SA_LOAD` — correctly detects the orphaned stubs

`SA_LOAD TOOL=0` responds

```
SA: Sensors — entry:N extruder:Y toolhead:Y
SA: ERROR — extruder/toolhead sensor active without entry on path 0.
    Possible broken filament piece in tube.
```

That guard exists precisely for this case and fired as designed.

---

## Confirmed working

- All 6 encoders calibrated (`encoder_mpp` 1.887–1.943)
- 5 of 6 bowden lengths calibrated — `bowden_length_5` absent, path 5 falls
  back to the path-4 value
- Selector positions calibrated, evenly spaced 24.49 mm
- `drive_rotation_distance` 5.7486
- Filament profiles stored for paths 0–3 (Polymaker Panchroma PLA, with
  colours); paths 4–5 unset
- All 21 `SA_*` commands registered and dispatching correctly
- Sensor reads accurate on all 18 sensors
- Entry guards in `do_load` behaving correctly
- Klippy log clean — no autoloader errors, exceptions or tracebacks
- LED system running (`sa_led_animator`, 6 chains, 15 Hz)

## Notes, not faults

- **State model tracks the entry sensor only.**
  `_initialize_states_from_sensors()` and the runout monitor both ignore the
  extruder and toolhead sensors. For the autoloader's own purposes that is
  the right signal — its job starts at the entry — but it does mean a
  toolhead holding an orphaned stub is invisible to path state.
- **Stale docstring.** `park_filament()` says "Called by SA_PARK_FILAMENT";
  the registered command is `SA_PARK`.
- **Repo drift on the printer.** `filaments/brands/` moved to
  `filaments/brands.bak/`, leaving only `zyltech.cfg` tracked. The deployed
  `filament_profiles/` still has all 15 brands, so no runtime effect.
- **Mainsail v2.14.0** on the printer vs v2.19.0 upstream. Relevant to the
  custom-panel plugin work, which targets 2.19.

---

## To return the machine to a loadable state

1. Clear the cut filament stubs from toolheads 0–3. Until then `SA_LOAD` will
   keep refusing those paths, correctly.
2. Feed filament into the entry of each path to be used.
3. `SA_HOME` to home the selector.

## Not yet exercised

`SA_LOAD` / `SA_UNLOAD` past their entry guards, toolhead park, purge,
`SA_CLEAN_NOZZLE`, `SA_HOME`, `SA_SELECT`, `SA_ENGAGE` / `SA_DISENGAGE`,
`SA_BUZZ_*`. All blocked on the machine being reloaded rather than on any
defect.

---

# Round 2 — live load/unload testing

Machine reloaded after clearing the cut stubs. Results below supersede the
"not yet exercised" list above.

## Working

- **Auto load and unload on paths 0–2** — full cycle, no intervention
- **Auto load on paths 3–5**
- **Encoder parking** — the three-phase park runs correctly:
  retract until the encoder goes quiet, feed forward to re-acquire the edge,
  back off `park_offset` (5 mm). Verified in the path-2 unload.
- Toolchange integration, per-tool heating, heatbreak retract, post-unload
  prompt, `SA_RESPOND` flow

The earlier load/unload failure is explained: a dirty entry sensor, fixed
before the printer was put away. Not a software fault.

## Defects found

### 1. Tip forming crushes the tip against the extruder gears

Measured 2.25 mm on one axis, 1.4 mm on the other — a flattened oval, not a
blob. Volume is conserved; the tip is being squashed, not swollen. It then
jams the loader gates on reload and has to be cut off by hand.

Cause is geometry. Tracking tip height above the nozzle, with the extruder
gears at `nozzle_distance` = 50 mm:

| Step | Move | Tip ends at | Time |
|---|---|---|---|
| push | 8 mm down | nozzle | — |
| Phase 1 fast | 48 mm @ 70 mm/s | 48 mm | 0.69 s |
| Phase 2 first half | 20 mm @ 10 mm/s | 68 mm | 2 s |
| dwell 5 s | — | 68 mm | — |
| Phase 2 second half | 20 mm | 88 mm | 2 s |
| Phase 3 slow | `52.5 − 88 = −35.5` | — | never runs |

The tip crosses the gear pinch at 50 mm — 2 mm into Phase 2, roughly **0.9 s
after leaving the melt zone**, still molten. The dwell that is supposed to set
the tip happens at 68 mm, **18 mm after** the gears have already crushed it.

### 2. Phase 3 is dead code

`slow_dist = nozzle_to_sensor_dist × 1.05 − (fast_dist + heatbreak_dist)`
evaluates to −35.5, so the `if slow_dist > 0` guard always skips it.
`tip_form_slow_speed` (7.5 mm/s) therefore has no effect, and the gear transit
happens at Phase 2's 10 mm/s. Confirmed by the absence of any "Slow retract"
line in the console.

**Proposed fix for 1 and 2:** Phase 1 already parks the tip at 48 mm, 2 mm
below the gears — the right place to cool. Move the dwell to the end of Phase
1, then cross the gears at `tip_form_slow_speed`. Dwell will likely need to be
longer than 5 s; that is a config value and tunable without a reflash.

### 3. No filament tracking during a print

`_state_monitor_tick()` polls the entry sensors at 1 Hz, flips `path_states`
and persists them, with a `runout_timeout_seconds` debounce. That is all it
does. It does not check whether the affected path is the actively printing
tool, and never issues `PAUSE` or `M600`. There is no jam detection during a
print either — no comparison of encoder movement against commanded extrusion.
`slip_tolerance` applies only during load.

So a runout or jam mid-print is recorded but not acted on.

### 4. KlipperScreen menu gating is not repeatable

The post-load menu appears on the touchscreen sometimes and not others. Needs
the menu flow worked through as a whole rather than patched case by case.

### 5. Extruder page sensor rows render off-screen

The sensors listed at the bottom of the extruder page hang past the bottom
edge of the display and cannot be read.

## Hardware note

The encoder housings are candidates for a reprint, possibly a small redesign
to make them serviceable — the load/unload failure that prompted this test was
a dirty sensor that was awkward to reach.

---

# Round 3 — LED behaviour

## Hardware fault: T2 logo LED, blue element dead

The Voron logo LED on toolhead 2 renders yellow where the other toolheads
render white. Confirmed by comparison rather than inference:

- Paths 0, 1 and 2 were all in state `empty`, so `sa_led_animator` was driving
  all three logos with identical equal-RGB breathing white values
- T0 and T1 showed white, T2 showed yellow

White minus blue is yellow. Same command, same code path, one LED behaving
differently, so this is the LED, not the software.

An earlier test in this session set all three of T2's LEDs to blue and the
result looked correct, which pointed the wrong way. The nozzle LEDs are much
brighter than the logo and were what got read. Isolating the logo is what
settled it — and note that with a path in `empty` state the animator
overwrites the logo at 15 Hz, so a bare `SET_LED` on index 3 will not appear
to stick.

Index mapping on T2 was verified correct along the way: index 1 is the left
nozzle, 2 the right nozzle, 3 the logo, matching T0.

**Action:** replace the logo LED on T2. Until then that toolhead shows every
filament colour shifted toward yellow, and cannot display blue at all.

## Fixed this round

- **Logos keyed on stored colour rather than path state.** `_SA_LED_FROM_STATE`
  chose PARKED whenever a colour hex existed, so an emptied path kept showing
  the colour of whatever it last held. Now keyed on `path_states`.
- **New `_SA_LED_STAGED`** for `partial` — filament colour at 25 %, so a path
  holding filament that was never driven to the nozzle reads as neither
  loaded nor empty.
- **Active tool was indistinguishable from parked tools.** `parked_cold` was
  introduced for docked tools but the animator also used it for a mounted
  tool with a cold hotend. Added `active_cold`, same hue and brighter.
- **Profile now cleared on runout.** A path that empties has its brand,
  material, product line, colour name, hex and type wiped, in memory and in
  `variables.cfg`. Answers the "does anything clear these automatically"
  question: it does now. It also stops the next load silently inheriting the
  previous filament's brand and temperatures.
- **Runout monitor could not clear `partial`,** and **wrongly promoted to
  `loaded`** on nothing more than the entry sensor. Both corrected; promotion
  now belongs to the load and unload sequences, which are the only things
  that know how far the filament actually travelled.
