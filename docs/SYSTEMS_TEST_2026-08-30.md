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
