# Autoloader — Handoff / Working Backlog

Shared memory between local and cloud sessions. Local `~/.claude` memory is
invisible to cloud sessions, so anything a future session needs lives here.
Keep it current; delete items as they land.

**Last updated:** 2026-09-02

---

## Where things stand

Working and verified on the printer (192.168.1.214):

- **Tip forming** — the cold-shear approach lands a clean 1.75 mm tip with
  minimal stringing on both T0 and T1. Tuned values are in
  `autoloader/parameters.cfg` (`tip_form_temp: 165`, `tip_form_shear_temp: 150`,
  `tip_form_shear_speed: 40`). Full load + unload verified on both channels.
- **Filament profile retention** — the three rules hold: removal wipes the
  profile, a profile selected on an empty channel is wiped after
  `material_select_timeout` (60 s), and a channel whose entry sensor sees
  filament keeps its profile until removal or a manual change.
- **Entry-parked state** — filament at the entry sensor promotes the path to
  `partial` and holds there.
- **Auto-park queue** — owned by the `[autoloader]` state monitor, not the
  sensors' `insert_gcode`. Bursts of insertions all park, in order.
- **LEDs** — hot nozzles warn amber whether or not the head is mounted; every
  waiting slot in the rack pulses, tinted by its stored filament colour; only
  a fully loaded path goes solid.
- **Mainsail panel** — ships as a runtime plugin on the Mainsail fork.
- **KlipperScreen panels** — the design pass is done. All five panels are
  rebuilt against KlipperScreen's own sizing (`content_width`/`content_height`,
  `font_size`), fit one screen with no scrolling except settings and configured
  values, scale with toolhead count, and follow the active theme. Buttons take
  KlipperScreen's own `colorN` classes so a theme change carries; the autoloader
  accent overrides only `border-bottom-color`. Titles read "Autoloader X".
  Calibration prompts are native `action:prompt_*`, so one call serves both
  Mainsail and KlipperScreen.

---

## Installer — built and proven on hardware (2026-09-04)

`install.sh` opens **menuconfig** (Klipper's own vendored kconfiglib, already on
every Klipper printer because `make menuconfig` uses it — no new dependency)
and the answers *generate* `pin_aliases.cfg`, `hardware.cfg` and
`parameters.cfg` from templates in `installer/templates/`.

The point is not the menu. Those three files stop being shipped and start being
generated, so `post_update.sh` no longer copies over them — it regenerates in
refresh mode, which rebuilds from the new template and puts back every value
the user had, reporting anything the new version no longer uses. That is the
fix for the clobbering this project worked around twice before (the pull-first
rule, then `user.cfg`).

`installer/detect.py` reads the printer first, so the menu is mostly
confirmation: toolhead count, extruder naming, toolchanger, CAN UUID, LED chain
family, and existing `STATUS_*` macros. `--check` runs after the menu and
**refuses** an LED choice that would stop Klipper starting.

**Verified end to end on both printers.**

Ender (`biqu@192.168.1.75`) — different user, Python 3.11, single extruder, real
`stealthburner_leds.cfg`: detection correct, guard refused Full and named all
ten colliding macros, config scaled to one path, every file parsed under
Klipper's own parser with zero empty aliases, re-install a no-op, uninstall
clean. Machine restored to exactly its prior state afterwards.

Voron (`pi@192.168.1.214`) — full wipe and reinstall, twice:
`uninstall → install → Klipper ready`, with the CAN UUID recovered from the
uninstall backup and all 101 calibrated values put back automatically. **A
config generated entirely from menuconfig answers boots on real hardware.**

Bugs the hardware testing found that sandboxes had not:

- `verify.sh` chose which printer to check by hostname (`!= sc350`), so on any
  other printer it queried the developer's Voron by IP and reported that
  machine's health as if it were yours.
- `verify.sh` reported six-toolhead defaults as drift on a correct
  single-toolhead install, advising the user to copy the developer's file over
  their own.
- Uninstall discarded `hardware.cfg`, the only place the CAN UUID lives — and a
  powered, configured board does not answer `canbus_query`, which is exactly
  its state during a reinstall.
- Uninstall preserved calibration but nothing restored it, so a reinstall came
  up correct except for every bowden length at its 800 mm default.

A third pass — a true bare-metal install with every recovery source deleted —
found three more:

- **The filament database was never deployed by anything.** KlipperScreen reads
  brand files from `config/autoloader/filament_profiles`, and no script put them
  there; the fifteen files survived only because nothing had deleted them. The
  wipe took them and left the filament picker silently empty.
- **The unset-UUID warning never fired.** It grepped the answers file, but
  `detect.py` only writes that key when it finds a UUID, so on a first install
  the key is absent and `CHANGE_ME` arrives from the Kconfig default at generate
  time. It checks the generated `hardware.cfg` now — the artifact Klipper reads.
- **The backup script's own self-check cried wolf**, running after the checkout
  back to the original branch when `printer_snapshot/` was already gone from the
  working tree. It declared a good backup incomplete. It asks the committed
  branch now.

A first install with no UUID now ends with instructions rather than a cryptic
`mcu 'autoloader': Invalid CAN uuid` after the next restart, and supplying it
through `user.cfg` was verified to override the generated file.

A fourth pass — Mike driving the menu interactively for the first time — found
the last five, all of which only appear when a real person runs it:

- The menu's key hints were wrong (written from memory, not from kconfiglib's
  own bindings: back is left-arrow, backspace OR Esc, and `/` searches).
- **The CAN scan had never once run.** `canbus_query` imports python-can, which
  lives in klippy-env, not system python3. It died with ModuleNotFoundError on
  every printer and that was reported as "no nodes answered".
- The generated CAN-list fragment was written relative to the caller's working
  directory, so running `~/autoloader/install.sh` from `~` put it in
  `~/installer/generated` where nothing sources it. The list silently never
  appeared.
- **Refresh mode preserved `CHANGE_ME` over a real answer.** Supplying the UUID
  through the menu generated the correct value, then reapply put the
  placeholder back over it and reported the file unchanged.
- `autoloader/hardware.cfg` shipped the developer's own `canbus_uuid`, and that
  file is the fallback for an install that never ran `installer/` — so a manual
  install silently pointed at someone else's board.

A placeholder means unanswered, everywhere: that same assumption was wrong in
three separate places (detect's answer-file check, the unset-UUID warning, and
generate's refresh).

The menu now also distinguishes no CAN interface / interface down / nothing
unassigned answered, instead of calling all three "normal".

**Installer status: done and hardware-proven, interactively included.**
The curses TUI itself is unexercised — that needs a human at a terminal.

---

## Backlog

Ordered roughly by value. Items 1–3 are features; 4–5 are the test sweep;
6 is the bug list.

### 1. ~~Tip forming should follow the loaded filament profile~~ — BUILT

Any `tip_form_<name>` can carry a per-material variant —
`tip_form_shear_temp_asa`, `tip_form_temp_petg` — and the loaded profile's own
`material` string selects the row. Resolution order is `SA_FORM_TIP` override →
per-material row → the tuned globals, so a material with no row forms exactly
as it did before. `SA_FORM_TIP MATERIAL=ASA` applies a row without that spool
being loaded, so a material can be tuned with whatever is to hand.

**Only the PLA row is measured.** It repeats the tuned globals. Every other row
is that material's typical print temperature offset by the deltas the PLA
measurement produced (ram = print − 48, shear = print − 63), and that those
deltas transfer between polymer families is an assumption — the temperature at
which filament fractures rather than stretches follows glass transition, which
PLA (~60 °C) and ASA (~105 °C) do not share. **The table needs tuning per
material before it can be trusted.** PETG and TPU are the ones to distrust
most: PETG is the classic stringer, and TPU may never go stiff enough to shear
at all — if it stretches, set `tip_form_shear_temp_tpu: 0` to put it back on
the sever/ease/cooling-move path.

### 2. Filament colour database refresh (research task)

See **Research brief** below — self-contained, hand it to a research agent.

### 3. Buffer / feed-assist system

Filament feed assistance for the **active toolhead**, driven by a filament
tension/compression sensor on each channel — the same idea as the buffer in
Bambu's AMS.

**How it works.** During a print the toolhead extruder pulls filament through
the whole path: spool → entry sensor → drive gear (neutral) → Bowden →
extruder. All the drag in that path shows up as pull force at the extruder.
Feed assist engages the drive gear and feeds forward to cancel it, using the
channel's tension sensor as the trigger.

**Scope is smaller than it first looks.** Only one toolhead is mounted at a
time, so only one channel ever needs assist. The selector parks at the active
channel and moves on tool changes, which happen between extrusion rather than
during it.

**Still true constraints:**

- One drive motor and one selector serve all six paths, so while assist is
  armed the autoloader cannot do anything else. Decide what happens if a
  runout or a load request arrives mid-print.
- The selector has to follow every toolchange, so assist must disarm,
  reposition and re-arm cleanly each time — and fail safe if it cannot.
- The servo would hold the drive gear engaged for a whole print rather than
  the seconds it holds today. Check the servo's duty cycle and heat.

**Pin budget — checked against the BTT MMB CAN V2.0 pinout**
(`References/hardware_pinouts/BTT_MMB_CAN_V2.0_pinout.png`).

Free headers, each with its own GND, so a switch-to-ground with a `^` pull-up
works on any of them regardless of the rail:

| Header | Pin | Rail |
|---|---|---|
| STOP2 | `PA10` | 3.3 V |
| STOP3 | `PD9` | 3.3 V |
| STOP4 | `PD8` | 3.3 V |
| MOT2 | `PA0` | 5 V |
| Sensor | `PC2` | 5 V |
| RGB | `PC3` | 5 V |

Six free inputs for six channels — **one switch per channel fits exactly**,
with no board changes and nothing displaced.

A separate tension *and* compression switch per channel needs 12 inputs. The
unused M2 and M4 stepper slots add nine more usable pins (`PD2, PC9, PB8, PB4`
and `PC14, PC13, PC12, PB6, PD6`), so 12 is reachable out of 17 available —
but those are stepper connectors, so the harness is awkward. Settle the sensor
design before committing to wiring.

Also unresolved: is the trigger a single switch (feed until slack returns), or
does compression need its own signal to stop overfeeding? The per-path encoders
already measure actual filament movement and could cross-check the feed rate
without any new sensor.

#### Resistor ladder on one ADC pin — the chosen approach

All six channels share a single analog pin. Each switch closes through its own
distinct resistor to ground, an external pull-up sits on the line, and the
measured resistance says which switch closed.

**Stock Klipper already decodes this — no custom extra needed.**
`klippy/extras/buttons.py` has `MCU_ADC_buttons`, exposed through
`[gcode_button]`:

```
[gcode_button sa_tension_0]
pin: autoloader:PA0
analog_range: <min_ohms>, <max_ohms>
analog_pullup_resistor: <ohms>     # default 4700
press_gcode: ...
release_gcode: ...
```

`buttons.py` converts the raw reading to **resistance**
(`value = pullup * adc / (1.0 - adc)`), so ranges are given in ohms rather
than volts — which is what a ladder naturally produces, and it makes the
design tolerant of supply variation.

**Pin cost: one.** `PA0` (MOT2 header) is free and is the one free header pin
that is ADC-capable on this chip. Nothing existing moves, and no multiplexer
is needed. `PA10`, `PD8`, `PD9`, `PC0`-`PC3` all stay spare.

**The hard limit: one closure at a time.** The decoder takes the first band
the resistance falls into:

```python
for i, (min_value, max_value, cb) in enumerate(self.buttons):
    if min_value < value < max_value:
        btn = i
        break
```

Parallel closures sum conductance, so two switches give a resistance that
either lands inside some other switch's band — misreporting the wrong channel
— or outside every band, reading as nothing at all.

For tension sensing that is acceptable, and the mechanics guarantee it rather
than merely making it likely: **the buffer is sprung on both sides, so it
self-centres.** Once the selector servo releases that channel the filament is
free to release its tension and the lever returns to neutral on its own. An
idle channel therefore closes no switch, single-closure is the normal case,
and there is no sustained state for a ladder to misread.

A lever held off-centre by a genuine jam still has its own unique resistance,
so it remains identifiable, and feeding or retracting that channel should
clear it. Worth a startup self-test that walks each channel and confirms it
reads neutral, since a channel that will not centre after its servo releases
is a real mechanical fault rather than a sensing artefact.

**Do not put the entry gates on a ladder.** All six read `filament_detected`
at the same time in normal operation — six independent booleans, which a
first-match ladder cannot represent. Binary-weighted conductances (R, R/2,
R/4 …) could encode all 64 combinations in principle, but the smallest
increment must stay distinguishable against 63x that value, roughly 1.6%
steps, against 1% resistor tolerance stacking across six parts. It would need
0.1% parts and would still be fragile — on the sensor that drives runout
detection and profile wiping. The entry gates are fine where they are, and
with the ladder taking only `PA0` there is no pin pressure left to relieve.

**Electrical notes:**

- **Use an external pull-up of a known value, not the MCU's internal one.**
  The STM32G0 internal pull-up is roughly 30-50 kOhm with wide tolerance and
  drifts with temperature, and `analog_pullup_resistor` has to be an accurate
  figure for the resistance maths to land in the right band. A 1% part is
  cheap insurance; the default the module assumes is 4700 ohm.
- **Feed the pull-up from 3.3 V, not 5 V.** The MOT2 header carries 5 V
  alongside `PA0`, and a G0 pin in analog mode is not 5 V tolerant. 3.3 V is
  available on the STOP headers, the 2x7 header and the I2C headers.
- Space the ladder values geometrically rather than linearly. The divider
  compresses the high-resistance end, so evenly spaced resistances do not give
  evenly spaced readings; widen the bands as resistance rises.
- Klipper samples for 39.5 ADC clock cycles at 16 MHz (2.47 us), supporting
  roughly 100 kOhm source impedance, so the whole ladder should stay well
  under that. `ADC_DEBOUNCE_TIME` is 25 ms and `ADC_REPORT_TIME` 15 ms, which
  is ample for a mechanical lever.
- An out-of-band reading is diagnostic: a disconnected line reads open and a
  shorted one reads zero, neither of which is a valid band, so the wiring can
  detect its own failure. Reserve bands for those rather than letting them
  alias onto a real channel.

**Reference for the G0 ADC pin list:** Klipper builds G0 from
`src/stm32/stm32f0_adc.c`, **not** `src/stm32/adc.c` — the latter is the
F1/F2/F4 table and lists `PC0`-`PC3` as analog, which is wrong for this board.
On G0 the analog pins are `PA0`-`PA7`, `PB0`, `PB1`, `PB2`, `PB10`, `PB11`,
`PB12`, `PC4`, `PC5`. Of the free headers only `PA0` qualifies.

### 4. Spool rewind during unload

Today an unload pushes filament back out of the path and it piles up loose —
Mike rewinds every spool by hand. Needs a way to take up that slack as it is
produced.

**Pin budget — it fits, with nothing added.** Rewind only ever runs in one
direction, so each channel needs a single on/off output driving an external
MOSFET or motor-driver module; the MCU pin only carries signal, never motor
current. Free digital pins after the tension ladder claims `PA0`:

`PA10` (STOP2), `PD8` (STOP4), `PD9` (STOP3), `PC0`, `PC1` (I2C),
`PC2` (Sensor), `PC3` (RGB) — **seven free, six needed.**

Wire them as `[output_pin]`s and drive them from the unload sequence. Note
`PC2` and `PC3` sit on 5 V headers, which is fine for a signal into a driver
module but must not be fed back into the MCU.

**What will not work:**

- **Six more steppers.** The MMB has only two unused stepper slots (M2, M4).
  Six proper stepper-driven rewinders means a second controller board.
- **An I2C GPIO expander** on `PC0`/`PC1`. Klipper has no generic I2C GPIO
  expander output driver, so this would mean new MCU firmware rather than
  configuration. Not worth it when six pins are already free.

**How much has to be respooled.** The calibrated Bowden lengths are
1270–1461 mm (`parameters.cfg`, `bowden_length_0..5`), plus `nozzle_distance`
and purge. So an unload pays back roughly **1.3–1.5 m per channel**, and a
rewinder has to take up all of it.

**Springs are almost certainly out.** Mike's call, and the reasoning holds:

- 1.5 m is a lot of take-up. On a full ~200 mm spool that is about 2.4 turns;
  on a nearly empty one it is 5–8 turns depending on core diameter. The *same*
  spring has to cover a roughly 3x range of required turns, at usable force
  across all of it — which is exactly what a constant-force spring is bad at.
- **Removing the roll releases everything the spring has stored.** A wound
  spring holding 1.5 m of take-up is stored energy pointed at whoever unclips
  the spool.
- A nearly empty roll that jumps its track has the same problem, and is more
  likely precisely when the spring is most wound.
- A printed spring will not survive the cycle count; a steel one makes the
  release hazard worse.

**Direction: active rewind.** Mechanism not yet chosen. Parked until the
items above are done — recorded here so the spring option is not re-proposed
without the reasoning that ruled it out.

**Options to weigh when it comes up:**

1. **Six small DC gearmotors**, one per spool, low-torque, driven only while
   the unload retracts. Uses the six free pins above. Needs a slip clutch or a
   current-limited driver so a taut spool cannot keep pulling — overwinding
   risks snapping filament at the entry, or dragging the path backwards
   against the drive gear.
2. **One shared rewind motor** engaged per channel by a mechanism riding the
   selector. Cheapest electrically, but the spools are remote from the
   selector carriage, so the mechanics are the hard part.

**Open questions:**

- What stops the rewind? There is no encoder on the spool, so it is time- or
  current-based: simplest is to run while the drive motor retracts and stop
  shortly after the entry sensor clears.
- The section 3 buffer sits between the drive gear and the toolhead, so it
  cannot see slack on the spool side. Closed-loop rewind would need its own
  sensor — either eating the remaining free pins, or sharing the tension
  ladder if a per-channel rewind switch can be added to it, subject to the
  same one-closure-at-a-time limit.
- Does rewind ever need to run during a print, or only during unload?

### 5. Full end-to-end test sweep — Mainsail panel

Run every command from the Mainsail panel rather than the console, and log
both UI bugs and any hardware faults that surface:

- All calibrations: `SA_CALIBRATE_SELECTOR`, `_DRIVE`, `_ENCODER_SPEED`,
  `_ENCODER TOOL=N`, `_BOWDEN TOOL=N`
- Self-tests / diagnostics: `SA_BUZZ_DRIVE`, `SA_BUZZ_SELECTOR`, `SA_HOME`,
  `SA_ENCODER_QUERY`, `SA_ENCODER_WATCH`
- Full load and unload on every path that has filament
- Profile selection and clearing through the UI

Capture: anything that misreports state, any dialog that strands the user,
any control that fires the wrong tool number.

### 6. Full end-to-end test sweep — KlipperScreen

The **design pass is complete** (see "Where things stand"). What is left here
is the same functional sweep as item 5, driven from the touchscreen: every
calibration, every self-test, a full load and a full unload, watching for
behaviour that only shows on the small screen.

All four issues originally logged under this item are resolved: the numpad
rendering past a 480 px display, sensor rows falling off the extruder page,
post-load offering options it should not, and panels not being visually
uniform.

**Before changing any panel, read the locked-UI sections in `CLAUDE.md`.**
`sa_load_unload.py`, `sa_home.py`, `sa_macros.py`, `sa_main.py`,
`sa_post_load.py` and `sa_settings.py` all have user-confirmed canonical
layouts with the reasoning recorded, including several first-render and
first-allocation bugs that specific constants and retries exist to prevent.
Restore rather than redesign unless Mike asks for a new layout.

### 7. Known open bugs

| Bug | Detail |
|---|---|
| Unload retract slips | In `do_unload`, the `toolhead:N + extruder:Y` branch retracts with the drive motor only and never syncs the extruder. Measured 40 mm driven vs 5–11 mm at the encoder. |
| `Timer too close` | 6 events, 4 on `et0`. CAN link is clean (`bytes_retransmit=0`, `srtt` 0.001–0.002, zero bus errors). All six toolheads share identical MAX31865 SPI config. Confound: nearly every test ran on T0. A clean T1 run since suggests `et0` is the marginal board, but this is not yet conclusive. |
| Coloured pulses read dim | The logo pulse runs through the locked gamma pipeline, so a mid-tone colour peaks around 0.13 while white peaks at 0.38. Correct hue, uneven apparent brightness across the rack. Normalising is a design decision Mike has not made. |
| ~~Active tool disagrees before initialization~~ — CLOSED, won't fix | **Decision 2026-09-03 (Mike): leave it.** It is toolchanger code, it works, and the autoloader does not depend on it — `_switch_tool` issues `T<n>`, which self-initialises from the tool probe correctly. Revisit only if the project turns out to need it. Filed originally as a three-way disagreement and twice escalated by me to a crash risk; both escalations were wrong, see `87b6bde`. What is real and remains unfixed by choice: between a Klipper restart and the first initialize, `toolhead.extruder` reads T0 whatever is mounted, so a UI reading it names the wrong tool in that window. Verified live that a single `INITIALIZE_TOOLCHANGER` clears it, and both G28 and PRINT_START already call one. |
| T2 logo LED | Not lighting. Hardware, not yet diagnosed. |
| Encoder housing | Needs a reprint. |

### 7a. Fixed since this list was written

- **Auto-park ignored a pull-and-reinsert, and lied when it failed** (2026-09-04).
  Two bugs in the same area, found by watching the machine rather than reading
  the code.

  A park was queued only when the path state was `empty` or `unknown`, and a
  path only reaches `empty` after the entry sensor reads clear for
  `runout_timeout` (10 s). Remove and replace filament inside that window and
  nothing moved at all -- the path went on claiming filament was parked at the
  drive gear while it sat at the entry sensor. The state machine watched a
  level where the real event is an edge. Parks now also fire on the sensor's
  low->high transition, with the baseline dropped during a load or unload
  because those drive the sensor clear and back deliberately.

  Separately: when the encoder never fired, the park printed
  "WARNING ... Parking anyway" and then "Filament parked", and the caller set
  the path to `partial` regardless -- byte-identical output to a park that
  worked. That is why 100 mm fed into thin air on two paths went unnoticed. It
  now reports failure plainly and refuses to write a state it did not earn.

  Verified: six paths, encoder movement 3.7-9.7 mm on every one, where paths 2
  and 3 previously registered 0.0.

  **Lesson worth keeping:** three separate theories were argued from logs and
  code (dead encoder channels, stepper auto-disable, insertion depth) and all
  three were wrong. One observation at the machine found it. The log said
  "Filament parked" six times and four of them were true -- a success message
  that cannot fail is worse than no message.


- **Profile wipe is no longer destructive.** A wipe now stashes the profile
  first, to `sa_lastprofile_<N>` in the variables file, so it survives a
  restart. `SA_RESTORE_PROFILE TOOL=N` puts it back and refuses to overwrite a
  path that already carries one. When a path with no profile sees filament
  again, the monitor says once that a stash exists and why it was cleared.
  Restoring is deliberately manual: automatic restore is right when the same
  spool goes back in and actively dangerous when a different one does — the
  machine would claim red PLA while holding blue PETG and heat for PLA.
  Verified end to end on the printer through the real `material_select_timeout`
  path. The underlying 10 s `runout_timeout` is unchanged — this makes the wipe
  recoverable rather than making it rarer.

### 7b. Portability — running on other StealthChanger builds

**Requirement (Mike, 2026-09-03): the autoloader should work with multiple
StealthChanger systems, not just this printer's.**

Surveyed 2026-09-03:

| Project | What it is | Verdict |
|---|---|---|
| `viesturz/klipper-toolchanger` | what this printer runs | baseline |
| `jwellman80/klipper-toolchanger-easy` | packaging fork of the above | **Python interface is clean — no code change needed** |
| `DraftShift/StealthChanger` | the hardware project: CAD, STLs, manual | not a software variant; its reference configs use the same `[tool TN]` / `[tool_probe TN]` sections and it points at viesturz |

Our entire dependency surface on the toolchanger is five things: the
`toolchanger` object's `get_status` fields (`status`, `tool`, `tool_number`,
`detected_tool_number`), the `T<n>` gcode, `tool_probe_endstop`'s
`active_tool_number`, the `after_change_gcode` hook, and core Klipper extruder
naming. Checked against the fork: `get_status` does not appear in the diff at
all, the config-option set is identical, all six gcode hooks keep their names,
and `T%d` registration is unchanged. The fork's 252 changed lines are all in
motion and gcode-offset internals (`_set_toolchange_transform`,
`_position_with_tool_offset`, `_save_state`, `_restore_axis`, `get_position`,
`move`) — nothing we read.

**The one real gap is the LED hook, and it is an install problem, not a code
problem.** CLAUDE.md tells the operator to hand-edit `after_change_gcode` in
`~/printer_data/config/Toolchanger/toolchanger.cfg`. On an easy-install that
file is at `~/printer_data/config/toolchanger/readonly-configs/toolchanger.cfg`
(lowercase directory) and is **a symlink into the user's git checkout**
(`install.sh:87`), so editing it modifies their repo and conflicts on update.
Their supported route is `toolchanger/toolchanger-config.cfg`, copied with
`cp -n` and included last — but overriding `after_change_gcode` there *replaces*
the block, so we would have to reproduce theirs plus our one line, which then
goes stale when they change theirs.

Worth building if portability is pursued:

1. Make the LED refresh self-installing rather than a documented hand edit —
   e.g. have `[autoloader]` subscribe to the toolchanger's change event, or
   register a `_SA_AFTER_TOOLCHANGE` wrapper, so no foreign file is touched.
2. `install.sh` should detect which layout is present rather than assuming this
   printer's paths.
3. `sa_sequences._current_tool()` returns -1 when no `toolchanger` object
   exists and `_switch_tool` then issues `T<n>` regardless, which errors on a
   single-head machine. Fine on all three targets above; only matters if
   single-toolhead support is ever wanted.

### 8. Worth doing, not yet requested

- **No automated tests exist for the Python extras.** `_clear_material_profile`
  was called but never defined anywhere, and every state-monitor tick threw
  `AttributeError` into a broad `except` that logged and moved on — so a whole
  feature was dead for an unknown length of time with no visible symptom. A
  small pytest suite with a fake printer object would have caught it on the
  first run. This is the highest-value item on this list that nobody has
  asked for.
- **Broad `except Exception` blocks hide exactly that class of failure.**
  Consider surfacing repeated tick failures in the `[autoloader]` status object
  so the UI can show that something is silently broken.
- **Print-time runout / jam response** — nothing currently happens if filament
  runs out mid-print.
- **Stub-clearing routine** — no way to clear a short stub left in a path.
- **`SA_FORM_TIP PRIME=1`** — prime before forming, for tuning convenience.

---

## Research brief — filament colour database refresh

Moved to **`docs/FILAMENT_REFRESH_BRIEF.md`** — a self-contained handoff a
research agent can work from without the repo. It carries the schema, the
sourcing rules, and a full inventory of all 893 existing colours so the agent
can tell missing from present. Regenerate it from `filaments/brands/*.cfg` if
the database changes; the inventory appendix is generated, not hand-written.

Two gaps to close, not one:

1. Colours released since the database was built. Polymaker Panchroma Matte is
   the known-stale line; assume others are too.
2. **Multi-colour entries stored as single hexes.** The loader has supported
   `color_type` / `color_hex_2` / `color_hex_3` all along and not one of the 893
   entries uses them, so every dual-tone and tri-colour filament in the database
   is currently flattened to one hex.
