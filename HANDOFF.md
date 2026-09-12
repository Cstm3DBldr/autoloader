# Autoloader — Handoff / Working Backlog

Shared memory between local and cloud sessions. Local `~/.claude` memory is
invisible to cloud sessions, so anything a future session needs lives here.
Keep it current; delete items as they land.

**Last updated:** 2026-09-12

---

## Access and controls

> **Sharing the printer with another project?** `docs/PRINTER.md` is the
> project-neutral version of this section — access, how to read the console,
> which restart reloads what, and the four edges of two projects on one
> machine. It is written to be **copied into another repo verbatim**. Keep the
> two in step, or keep only that one.

**There are no secrets in this file, and none were needed.** Every route below
is key-based or unauthenticated on the LAN. No password, token or private key
was read, stored or typed during any of this work — if a future session finds
itself needing one, that is new, and it should stop and ask rather than hunt
for it.

| What | Address | Auth | Notes |
|---|---|---|---|
| Printer (the Voron, `sc350`) | `ssh pi@192.168.1.214` | SSH key, `BatchMode=yes` | The only machine this project deploys to |
| Moonraker REST | `http://192.168.1.214:7125` | none, LAN only | Console, status, gcode injection, database |
| Mainsail | `http://192.168.1.214/` | none | The panel ships as a runtime plugin |
| GitHub | `git@github.com:Cstm3DBldr/autoloader.git` | existing credential helper | `main` / `dev` / `printer-dev` / `old-dev` |
| Second printer (UI testbench) | `ssh biqu@192.168.1.75` | SSH key | An Ender — used ONLY for KlipperScreen UI work, has no autoloader hardware |

**ssh prints a post-quantum warning on every call** to this host. It is noise,
not a failure. Filter it or output gets unreadable:

```
2>&1 | grep -v "post-quantum\|store now\|may need\|^\*\*"
```

**scp needs `-O` against this printer.** OpenSSH 9+ defaults to the SFTP
protocol, which this sshd closes on — the error is `scp: Connection closed`,
which names neither the transport nor the cause and reads like an unreachable
host directly after a successful `ssh` to the same box.

### The commands that actually get used

Reading the printer's console without screenshots — by far the most useful
thing a session can do, and not obvious:

```
curl -s "http://192.168.1.214:7125/server/gcode_store?count=60"
```

It returns the whole console as JSON (`result.gcode_store[].message`). Filter
the `B:`/`T0:` temperature spam or it drowns everything.

Sending a command, same way:

```
curl -s -X POST "http://192.168.1.214:7125/printer/gcode/script?script=SA_STATUS"
```

Reading live state — sensors, path states, the resolved guide:

```
curl -s "http://192.168.1.214:7125/printer/objects/query?autoloader"
```

Live filament sensors are NOT in the `autoloader` object. They are their own
Klipper objects: `filament_switch_sensor entry_sensor_N`, `extruder_sensor_N`,
`toolhead_sensor_N`, each with `filament_detected`.

| Job | Command |
|---|---|
| Reload Python extras | `bash ~/autoloader/scripts/klipper_service_restart.sh` |
| Reload KlipperScreen panels | `bash ~/autoloader/scripts/service_restart.sh KlipperScreen` |
| Sync non-symlinked files | `cd ~/autoloader && ./post_update.sh` |
| Recover an MCU shutdown | POST `FIRMWARE_RESTART` |
| Check for drift, no printer | `python3 scripts/check_drift.py` |
| Check printer against repo | `./scripts/verify.sh` |
| Rebuild + ship the Mainsail plugin | `SA_HOST=192.168.1.214 bash scripts/deploy_mainsail_plugin.sh` |

**`FIRMWARE_RESTART` does not reload Python extras** — it only re-parses the
config and resets the MCUs. Every change to `klipper/extras/*.py` needs the
service restart. This has cost days before.

**Deploying = pushing.** The printer follows `printer-dev` through Moonraker's
Update Manager (`primary_branch: printer-dev` in its own `[update_manager
autoloader]` block — other blocks in that file say `main` and are unrelated).
The working loop is: push to `printer-dev`, then on the printer
`git fetch && git reset --hard origin/printer-dev`, then the service restart.

---

## Machine setup that measurements depend on

**Extruder tension, set 2026-09-12: unloaded, backed off to zero lash, then one
turn in — identical on all six toolheads.** Every tip-forming and toolhead
geometry number is referenced to this. Change it and they stop describing the
machine.

It earned its place the hard way: the original tip tuning produced a clean
1.75mm tip on T0 and T1, and the identical settings produced 2.02mm on T4. That
0.27mm is the gears flattening the filament — mechanical, so it survived every
shear temperature and speed tried against it. See `docs/TIPFORM_CAL.md`.

## Topology

### Hardware

**Six parallel lanes, one movable gear.** Each path is a fixed lane with its
own entry sensor, its own encoder and its own tube. Nothing about a lane moves.
The only travelling part is the drive gear on the selector carriage.

```
                    ┌── the ONLY moving part ──┐
                    │  Drive Gear on carriage  │
                    │  Selector positions it,  │
                    │  Servo grips or releases │
                    └────────────┬─────────────┘
                                 │ engages ONE lane at a time
   ┌─────────────────────────────┴─────────────────────────────┐
   ▼                                                           ▼
Roll N ─ Entry N ─[gear]─ Encoder N ─ Tube N ─ ExtSns N ─ gears ─ ThSns N ─ Nozzle N
       └ always live ─┘ └ always live ┘        └─ per toolhead, always live ─┘

  lane pitch 24.69mm   (T0 0.00 … T5 123.45, measured)
```

The encoder sits **downstream of the gear**, which is what makes the tail of a
finished roll pass it — a measured mid-tube datum. Each encoder is locked to
its lane and counts whatever moves, including while the extruder is pulling and
the drive is disengaged. That is the whole reason the machine is built this
way: fast loads, fast unloads, and jam/break detection during a print.

A single-channel optical encoder **cannot sense direction**. The pulse count is
always right; the accumulated sign is only right if something set it. So net
consumption comes from the extruder, and the encoder answers "is it moving".

### MCUs

| Name | Board | Carries |
|---|---|---|
| `mcu` | BTT Manta M8P | the printer itself (in printer.cfg — do not touch) |
| `autoloader` | BTT MMB CAN V2.0, uuid `329ce333239a` | both steppers, servo, 6 encoders, 6 entry sensors |
| `et0`–`et5` | BTT EBB36 per toolhead | extruder + `extruder_sensor_N` + `toolhead_sensor_N` |

**The `autoloader` board has no timing slack.** It bit-bangs software SPI for
two TMC5160s (hardware SPI fails on it) and polls twelve button pins every 2ms,
and reports ~41x the per-task time of the main MCU. It has shut down with
`Timer too close` when the host stalled on file I/O. Anything that blocks the
Klipper host — notably repeated `SAVE_VARIABLE`, each of which rewrites the
whole file synchronously — starves it first.

### Software, and where each piece lives

```
  repo ~/autoloader/  ──symlink──►  ~/klipper/klippy/extras/*.py   (6 extras)
                      ──symlink──►  ~/moonraker/.../sa_moonraker.py
                      ──copy─────►  ~/printer_data/config/autoloader/*.cfg
                      ──copy─────►  ~/KlipperScreen/panels/sa_*.py
                      ──generate─►  parameters.cfg, hardware.cfg, pin_aliases.cfg
                      ──build────►  ~/mainsail/plugins/autoloader-panel-plugin.js
```

Extras are symlinked, so a `git reset` on the printer changes the running code
the moment the service restarts. Panels and cfgs are **copied** by
`post_update.sh`, so they can silently run old code if it is skipped.

Three cfgs are **generated** from `installer/templates/` whenever an answer file
exists. Editing `autoloader/parameters.cfg` alone does nothing — `post_update`
regenerates it from the template and the change vanishes. Change both.

### The one definition that matters

`_GUIDE` in `klipper/extras/sa_calibration.py` is the single definition of the
twelve-step calibration guide. `guide_pages()` resolves it into the status
object and **every UI renders what it is given** — Mainsail and KlipperScreen
describe nothing themselves. Adding a step is one edit there, and
`scripts/check_drift.py` proves the numbering agrees with itself.

---

## Where things stand — 2026-09-12

`main`, `dev` and `printer-dev` are all at one commit for the first time in a
while, and the printer is on it. `printer-dev` then took KlipperScreen UI work
that Mike has not finished looking at.

**All six heads unloaded cleanly through the real `SA_UNLOAD`, no overrides.**
Verified from the log rather than claimed: every one of T0-T5 shows both the
`Cooling extruder N -> 165C for tip forming` step-down and `4 cooling moves of
10.0mm, 10 to 50 mm/s`, and all six paths finished `partial` with the tip
parked at the drive gear. That is the tip recipe measured on two heads and then
proved on six.

**The recipe, and why it was wrong before.** Shear mode had been the default
since 2026-09-02 and its branch RETURNS before the cooling moves, so this
machine had never run one. Two evenings of tips were judged without the step
that shapes a tip. Cross-sections against round 1.75mm filament (2.405mm2),
which is what separates a squash from a swell:

    shear mode            2.02 x 1.50   -1%   squashed, heavy stringing
    shear + DWELL=15  T4  2.00 x 1.70  +11%
    shear + DWELL=15  T0  2.12 x 1.70  +18%
    SHEAR=0, cooling      1.91 x 1.75   +9%   no squash, little/no string

T0 and T4 differing by 7 points on identical settings is what ruled the
toolhead out and the setting in. `tip_form_shear_temp` and
`tip_form_push_length` are both 0 now, and all eleven per-material
`shear_temp_*` rows are commented out -- that value is BOTH a tuning knob and
the mode switch (`if shear_temp > 0`), so any per-material row re-enabled a
mode the global said was off.

**`SA_RECOVER` exists and has recovered a real broken path** -- T4 in the state
no load branch handles (entry FILAMENT, extruder CLEAR, toolhead FILAMENT).
Its melt-rate ceiling and per-step jam gate were added AFTER that run and have
never been exercised.

**Do not trust the six stored geometry sets against each other.** They were
taken three different ways. All six heads are now in one identical state --
`partial`, tip at the gate, extruder tension uniform since 2026-09-12 -- which
makes this the moment to re-measure them on one method.

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

### 5. ~~Full end-to-end test sweep — Mainsail panel~~ — DONE 2026-09-11

Mike walked every one of the twelve steps through Mainsail on 2026-09-11,
and that pass is where the day's six toolhead measurements came from. The
web side of the chain is proven by use, not by inspection.

<details><summary>original plan</summary>


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

</details>

### 6. Full end-to-end test sweep — KlipperScreen — STILL OPEN

The half with the history: KlipperScreen keeps only the LAST `prompt_text`,
its guide panel once sat on step 1 all session reading a field Moonraker had
never sent, and its panels are copied rather than symlinked so they can run
old code without saying so. Checked in code so it need not be rediscovered:
`_emit_ui_prompt` collapses the body into one `prompt_text` unless `ks_line`
is passed, and step 12 does not pass it, so its prompts should arrive whole.


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
