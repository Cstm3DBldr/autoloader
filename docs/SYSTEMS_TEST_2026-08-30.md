# Systems test — 2026-08-30

Baseline capture of what works and what doesn't, taken before any further
work. Backup of the printer at this moment is on branch
`printer-backup/known-good-2026-08-30`.

Deployed commit: `77989d9`
Klipper `v0.13.0-411-g938300f3` · Moonraker `v0.9.3-128-g960e933` ·
KlipperScreen `v0.4.6-11-g6b6f63b6` · Mainsail `v2.14.0`
All three services active, Klippy reports ready.

---

## Machine state at capture

| | |
|---|---|
| `homed_axes` | `''` — **XYZ not homed** |
| selector | not homed (`current_path -1`, `selector_position -1.0`) |
| active tool | T3 |
| servo | disengaged |
| `cal_state` | empty (no calibration in flight) |
| print state | standby |

## Sensors vs stored state

| Path | entry | extruder | toolhead | `path_state` | `filament_loaded` |
|---|---|---|---|---|---|
| 0 | False | True | True | empty | False |
| 1 | False | True | True | empty | False |
| 2 | False | True | True | empty | False |
| 3 | False | True | True | empty | False |
| 4 | False | False | False | empty | False |
| 5 | False | False | False | empty | False |

Raw Klipper `filament_switch_sensor` objects were queried directly and agree
with what the autoloader status object reports, so the sensor *reading* path
is correct. The disagreement is between the sensors and the stored state, not
within the software.

`variables.cfg` has `sa_state_0..5 = 'empty'` persisted.

---

## Confirmed working

- All 6 encoders calibrated (`encoder_mpp` 1.887–1.943)
- 5 of 6 bowden lengths calibrated (`bowden_length_5` absent, path 5 falls
  back to the path-4 value)
- Selector positions calibrated, evenly spaced 24.49 mm apart
- `drive_rotation_distance` 5.7486
- Filament profiles stored for paths 0–3 (Polymaker Panchroma, PLA, with
  colours); paths 4–5 unset
- All 21 `SA_*` gcode commands registered
- Klippy log clean — no autoloader errors, exceptions or tracebacks
- LED system deployed and running (`sa_led_animator`, 6 chains, 15 Hz)

## Confirmed broken

### 1. `SA_PARK` returns immediately on every path

Tested live: `SA_PARK TOOL=0` responds
`SA: No filament at entry of path 0 — nothing to park.`

`park_filament()` in `sa_sequences.py:445` gates on the entry sensor:

```python
if not owner._entry_sensor_active(path):
    gcmd.respond_info("SA: No filament at entry of path %d — nothing to park." % path)
    return
```

All six entry sensors read `False`, so this returns before any motion. Whether
this is a fault depends on what is physically at the entry — see Open
questions.

### 2. Toolhead parking cannot run

`_park()` issues `G0 Z<load_park_z>` and then `PARK_ON_COOLING_PAD`, which
itself issues `G0 X/Y` moves. With `homed_axes` empty both fail with
"Must home axis first". This is a consequence of the unhomed printer, not a
defect in the park routine.

## Observations, not necessarily faults

- **State model only tracks the entry sensor.** `_initialize_states_from_sensors()`
  infers state from the entry sensor alone, and only for paths still
  `unknown`. The runout monitor likewise reconciles against entry only.
  Nothing consults the extruder or toolhead sensors, so a path with filament
  loaded to the nozzle but nothing at the entry reads as `empty` — which is
  exactly the current state of paths 0–3.
- **Stale docstring.** `park_filament()` says "Called by SA_PARK_FILAMENT";
  the registered command is `SA_PARK`. Wiring is correct, comment is not.
- **Repo drift on the printer.** `filaments/brands/` has been moved to
  `filaments/brands.bak/`, leaving only `zyltech.cfg` tracked. The deployed
  `~/printer_data/config/autoloader/filament_profiles/` still has all 15
  brands, so this has no runtime effect.
- **Mainsail is v2.14.0** on the printer, while upstream is v2.19.0. Relevant
  to the custom-panel plugin work, which targets 2.19.

---

## Open questions

1. **Is there physically filament at the entry sensors of paths 0–3?**
   If yes, the entry sensors are faulty and that is the real defect. If no,
   `SA_PARK`'s gate is behaving as designed and the filament simply needs
   feeding in before it can be parked. Everything about finding 1 depends on
   this answer.

2. Homing the printer is a prerequisite for testing load, unload and toolhead
   parking. Not done yet.

## Not yet tested

Blocked on homing: `SA_LOAD`, `SA_UNLOAD`, toolhead park, `SA_CLEAN_NOZZLE`,
purge. Untested regardless: `SA_HOME`, `SA_SELECT`, `SA_ENGAGE` /
`SA_DISENGAGE`, `SA_BUZZ_*`.
