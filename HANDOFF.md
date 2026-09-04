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

**Goal:** find filament colours released by brands already in the database
that are missing from it, and return them in the exact schema below.

**Repo path:** `filaments/brands/*.cfg`

**Current coverage** (product lines / colours):

| File | Product lines | Colours |
|---|---|---|
| `polymaker_panchroma.cfg` | 23 | 210 |
| `polymaker.cfg` | 12 | 81 |
| `bambulabs.cfg` | 9 | 74 |
| `esun.cfg` | 8 | 64 |
| `inland.cfg` | 7 | 59 |
| `creality.cfg` | 8 | 56 |
| `overture.cfg` | 6 | 55 |
| `zyltech.cfg` | 6 | 43 |
| `prusament.cfg` | 6 | 40 |
| `hatchbox.cfg` | 4 | 38 |
| `sunlu.cfg` | 5 | 38 |
| `colorfabb.cfg` | 8 | 36 |
| `voxelpla.cfg` | 6 | 36 |
| `amolen.cfg` | 6 | 34 |
| `fiberon.cfg` | 4 | 29 |

**Known gap:** Polymaker Panchroma Matte PLA has 38 colours recorded. Mike
believes the line has released colours beyond these, and that other lines are
likely stale too. Current Matte entries:

Charcoal Black, Cotton White, Muted White, Ash Grey, Fossil Grey, Army Beige,
Pastel Peanut, Wood Brown, Army Brown, Earth Brown, Pastel Peach, Sunrise
Orange, Muted Red, Lava Red, Army Red, Pastel Watermelon, Lotus Pink, Sakura
Pink, Pastel Candy, Lavender Purple, Muted Purple, Electric Indigo, Army
Purple, Pastel Periwinkle, Sky Blue, Pastel Ice, Arctic Teal, Sapphire Blue,
Muted Blue, Army Blue, Savannah Yellow, Pastel Banana, Army Light Green, Lime
Green, Pastel Mint, Muted Green, Forest Green, Army Dark Green

**Required output format** — one block per colour, appended under the correct
existing `[sa_product_line]`:

```
[sa_color <product_line_key>.<color_key>]
product_line: <product_line_key>
color_name: <Manufacturer's exact colour name>
color_hex: #RRGGBB
```

`<color_key>` is lowercase snake_case of the colour name. If a whole product
line is missing, add it in the existing shape:

```
[sa_product_line <key>]
brand: <brand key>
display_name: <Manufacturer's exact line name>
material: PLA | PETG | ABS | ASA | TPU | …
description: <one line>
load_temp: <°C>
unload_temp: <°C>
purge_speed: 5
purge_length: 30
bed_temp: <°C>
```

**Rules:**

1. **Hex codes must come from the manufacturer** — their own swatch, product
   page, or official spec sheet. Do not eyeball a hex from a product photo;
   lighting makes those wrong, and these values drive physical LEDs.
2. **Cite a source URL for every colour added.** No claim without a citation.
3. Use the manufacturer's exact colour name, including accents and ™.
4. Flag any colour you cannot find a first-party hex for, rather than guessing.
5. Note discontinued colours separately — do not delete anything unilaterally.
6. Temperatures should come from the manufacturer's published range; if a line
   gives a range, take the midpoint and say so.

**Deliverable:** a per-brand list of additions in the schema above, plus a
short summary of which lines were already complete.
