# Toolhead status LEDs — optional

The autoloader can drive per-toolhead LEDs: the Voron logo shows the loaded
filament's actual colour, the nozzle LEDs show what the printer is doing, and a
hot nozzle warns amber whether or not that head is mounted.

**It is off by default and the autoloader is fully functional without it.**
Nothing in the load, unload, or calibration path depends on LEDs. If your LED
setup already works and you would rather not touch it, skip this document.

It ships off because LED hardware is the least portable part of any build. The
chain names, the wiring order, and whether you already run
`stealthburner_leds.cfg` all differ machine to machine, and one of those
differences will stop Klipper from starting rather than merely look wrong.

---

## The installer does this for you

Run `install.sh`, pick an LED option in the menu, and it copies the right files,
fills in your chain names, and switches the include on. It also **refuses** the
option that would stop your printer from starting. The rest of this page is
what it is doing and how to change it afterwards.

## Doing it by hand

There are two example files, split on purpose:

| file | contains | collides with anything? |
|---|---|---|
| `leds_core.cfg` | filament colour on the logo, the animator, all the `_sa_`/`_SA_` macros | **no** — every name is namespaced |
| `leds_status.cfg` | the ten `STATUS_*` macros | **yes** — same names as stock Voron |

`leds_core.cfg` works on its own. Install `leds_status.cfg` **only** if you are
not using `stealthburner_leds.cfg`.

**1. Copy what you want.**

```bash
mkdir -p ~/printer_data/config/autoloader/leds && cp ~/printer_data/config/autoloader/examples/leds_core.cfg ~/printer_data/config/autoloader/leds/
```

`leds/` is yours. `post_update.sh` creates it and then never writes to it, so
your edits survive every update — which is exactly why the example does not
live there. Edit the copy, never the example.

**2. Uncomment the include** in `~/printer_data/config/autoloader/user.cfg`:

```
#[include leds/*.cfg]      ->      [include leds/*.cfg]
```

`user.cfg` is written once by `install.sh` and is not in the repository, so no
update can reach it. Re-running the installer asks before touching it, and
defaults to keeping it when there is no terminal to ask at.

**3. Adapt the copy to your hardware** — the next section. Then restart Klipper.

---

## What you must change

### LED chain names

The example builds a chain name per toolhead as `<prefix><N><suffix>`:

```
variable_led_prefix: "et"
variable_led_suffix: "_leds"
```

which gives `et0_leds … et5_leds` — this machine's naming. Find yours:

```bash
grep -rn "^\[neopixel" ~/printer_data/config/
```

A stock StealthBurner build has a single chain called `sb_leds`. **If you have
one shared chain rather than one per toolhead, per-toolhead filament colour is
not possible** — the LEDs cannot show six different colours at once. Use the
status macros only, or leave LEDs off.

### LED indexes

```
variable_logo_idx:   "3"
variable_nozzle_idx: "1,2"
```

These are chain-relative and **reversed on this build** compared to stock Voron
wiring, where the logo is index 1 and the nozzle 2,3. Do not assume. Verify
with the `_SA_LED_TEST_T0` macro at the bottom of the file before trusting
them — it lights one index at a time so you can see which is which.

### Caselight

The test macros drive `LED=caselight`. Delete them, or rename it, if you have
no such object.

---

## The one thing that will stop Klipper from starting

The example defines ten macros whose names the stock `stealthburner_leds.cfg`
also defines:

`STATUS_READY` `STATUS_PRINTING` `STATUS_HEATING` `STATUS_BUSY` `STATUS_HOMING`
`STATUS_LEVELING` `STATUS_MESHING` `STATUS_CLEANING` `STATUS_CALIBRATING_Z`
`STATUS_OFF`

The stock file writes them lowercase (`[gcode_macro status_ready]`) and this
one writes them uppercase, which looks like no conflict — but Klipper
uppercases every macro alias, so both register the same command and the second
raises `gcode command STATUS_READY already registered`. **The printer will not
boot.** Check before you restart:

```bash
grep -rli "gcode_macro status_ready" ~/printer_data/config/
```

If that finds anything other than your own copy, pick one:

### a) Keep your existing LEDs (recommended)

Install `leds_core.cfg` only — do not copy `leds_status.cfg`. Your status
system keeps the nozzle LEDs; the autoloader keeps the logo LED and paints it
with the loaded filament's colour.

This is what the installer's "Filament colour on the logo only" option does,
and it is why the files are split rather than the docs simply telling you to
delete a block: an instruction to delete something is an instruction people
skip, and skipping it here means the printer will not boot.

### b) Replace them

Comment out your `stealthburner_leds.cfg` include instead. These macros cover
the same states, with a palette that follows the upstream one closely.

---

## Optional: refresh after every toolchange

Add to the **end** of `[toolchanger] after_change_gcode:` in your toolchanger
config:

```
_SA_LEDS_INIT_ALL ACTIVE={tool.tool_number}
```

This repaints every toolhead's LEDs after each change, so docked heads show
their stored filament colour and the mounted one goes solid.

**Only add this if you enabled LEDs.** Without them the command does not exist
and every toolchange will fail.

One caution on where you put it. On a `klipper-toolchanger-easy` install, the
toolchanger config is a **symlink into that project's git checkout**, so editing
it changes their repository and conflicts on their next update. Use their
override file, `~/printer_data/config/toolchanger/toolchanger-config.cfg`,
which is included last — but note that overriding `after_change_gcode` there
*replaces* the whole block, so copy theirs across and append the line.

---

## Colour rendering

The filament-colour pipeline in `_sa_set_logo_filament` is tuned, not
arbitrary, and the reasoning is recorded in `CLAUDE.md`. In short: on a
WS2812B/SK6812 the green die is roughly 1.5–2× brighter than red or blue, and
human brightness perception is about gamma 2.2, so raw hex values render as
washed-out pastels with a green cast. The pipeline attenuates green when it is
not the dominant channel, applies gamma 2.2, and keeps very dark colours out of
the LED's quantisation noise floor by rescaling them without gamma.

If you change any of it, the three test macros
(`_SA_LED_TEST_CASELIGHT_MAX`, `_..._BROWNS`, `_..._GRAYSCALE`) are the
verification tools — keep their hardcoded values in step.

---

## Turning it back off

Re-comment the include in `autoloader/user.cfg` and restart. Your copy
under `leds/` is left alone, so turning it on again is one edit. If you added
the toolchange hook, remove that line too.
