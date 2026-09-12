# Tip-forming calibration — per product line, measured instead of guessed

**Status: design note. Nothing is built.** Written 2026-09-11, after a night
in which every tip judged was formed at the wrong temperature and nobody could
tell, because there is no routine that forms one, scores it and saves the
answer.

This is the last autoloader calibration that still has to be done by hand
editing a config.

## The gap it closes

CLAUDE.md already says it, in the "What Not To Do" list:

> Do not treat the untuned rows in the per-material tip table as calibrated.
> Only the PLA row is measured. Every other row is that material's typical
> print temperature offset by PLA's measured deltas, which assumes the deltas
> transfer between polymer families — they may not, since the shear temperature
> depends on glass transition.

So the table ships with one measured row and four guesses:

```
tip_form_temp_pla    165.0     tip_form_shear_temp_pla    150.0   MEASURED
tip_form_temp_petg   192.0     tip_form_shear_temp_petg   177.0   derived
tip_form_temp_abs    202.0     tip_form_shear_temp_abs    187.0   derived
tip_form_temp_asa    207.0     tip_form_shear_temp_asa    192.0   derived
```

Every derived row carries PLA's `-15 °C` shear delta, which is an assumption
about polymer behaviour, not a measurement.

And a filament profile carries `load_temp`, `unload_temp`, `purge_speed` and
`purge_length` — but **nothing about tip forming**. So there is nowhere for a
measured answer to live even if someone found one.

## What already exists

Most of the loop is built. This is a wrapper, not a new mechanism.

- **`SA_FORM_TIP TOOL=N [PUSH=] [SEVER=] [TEMP=] [MATERIAL=] …`** already runs
  only the tip sequence with **inline overrides**, so no `SAVE_CONFIG` and no
  restart between attempts. `MATERIAL=` applies a material's row without that
  spool being loaded, so a material can be tuned with whatever is to hand.
  It leaves the tip past the gears — pull from the entry side and look at it.
- **`cfg()` in `form_tip` already resolves a chain**: inline override first,
  then `owner.tip_form_<name>`. Adding "the profile's measured value" is one
  more link, not a new design.
- **The guide framework** renders per-path grids, live values and prompts on
  both UIs from one definition in `_GUIDE`.
- **`filaments/brands/*.cfg`** carries per-brand, per-product-line profiles,
  and `SA_SET_MATERIAL` puts one on a path.

## The shape

**Scored by eye, because nothing else can see a tip.** Same as step 12's
`toolhead sensor -> nozzle tip`: the operator is the sensor. The routine's job
is to make each attempt cheap, keep the settings in front of them, and save
the answer where it will be found again.

```
  pick the product line   ── from the filament DB, not free text. The answer
                             belongs to "Polymaker Panchroma Matte PLA", not
                             to "PLA" and not to path 4.
        ↓
  seed the settings       ── measured values for that line if it has any,
                             else the material row, else the globals
        ↓
  form a tip  ─────┐         SA_FORM_TIP with the current values inline
        ↓          │
  operator looks   │         smushed? strung? fat? clean taper?
        ↓          │
  adjust ONE knob ─┘         one at a time, or the result cannot be attributed
        ↓
  good              ── save to the product line, not the path
```

### Where the answer is saved

**Per product line, in `variables.cfg`.** Not per path: a spool moves between
paths and the tip behaviour belongs to the filament. Not in
`filaments/brands/*.cfg`: those are tracked and `post_update.sh` overwrites
what it copies, so a measured value written there is lost on the next update —
the same trap as the LED switch and for the same reason.

`variables.cfg` is the established home for measured calibration and is never
overwritten. Key shape something like
`sa_tipform_<brand>_<line>_<material>`, normalised the way `_material_key`
already normalises material names.

### The resolution chain

Four links, most specific first:

1. inline override on `SA_FORM_TIP` — a live experiment, saves nothing
2. **measured values for this product line** — new
3. the per-material row (`tip_form_shear_temp_pla`) — ships guessed except PLA
4. the global default

A path with no profile still behaves exactly as it does today.

### One panel

Mike's requirement, and it is the right one: the settings to adjust, the
FORM TIP button, and LOAD / UNLOAD together in one place. Tuning a tip means
forming, looking, adjusting, and periodically proving it survives a real
unload — and sending the operator to another screen for that last part is how
a tuning session gets abandoned halfway.

## What gets measured, and why 3-4 materials

Mike's call: measure three or four across polymer families and see whether the
relationship holds well enough to derive the rest.

That is the right experiment because the current table already assumes one:
every derived row is PLA's shear delta applied to a different print
temperature. Measuring PLA (already done), PETG, and one styrenic (ABS or ASA)
tests whether the delta transfers across glass transitions or whether each
family needs its own.

If the deltas hold, the table can keep deriving and say so honestly. If they
do not, the table should stop pretending and mark unmeasured rows as unknown.
Either answer is worth having; the current state — guesses labelled as though
they were data — is the one that is not.

## Why this is worth building, from tonight

Every tip judged on 2026-09-11 was formed at 125 °C, because a `25.0` left in
`parameters.cfg` overrode a code default of `0.0` and nothing on screen said
which temperature was in force. Hours of "still a bit smushed, still stringing"
were spent on a setting nobody could see.

A calibration that shows the value it is about to use, forms a tip with it, and
records what the operator thought would have caught that in one attempt.

## Extruder tension is a confound, and it has to be controlled

**Set on this machine 2026-09-12: unloaded, backed off to zero lash, then one
turn in — identical on all six.** Record any change to that, because every tip
measurement is referenced to it.

This is not housekeeping. It is the first thing that actually explained a bad
tip, and it was found by measuring the tip rather than reasoning about the
routine:

- the original tuning produced a clean **1.75mm** tip on **T0 and T1**
- the same settings, same filament, same temperature produced **2.02mm** on
  **T4**

0.27mm of permanent flattening is the gears squashing the filament, which is
mechanical and so survives every shear temperature and speed — and it did
survive all of them, across a whole evening of changing the wrong variable.

Two consequences for this calibration:

1. **A saved tip-form value is only valid for the tension it was measured at.**
   If the calibration saves per product line and someone re-tensions, the saved
   number silently stops describing the machine. Whether that wants recording
   alongside the value is an open question below.
2. **Cross-toolhead comparison needs equal tension or it is measuring the
   wrong thing.** T4 was the outlier in tip diameter AND in step 12's
   `toolhead sensor -> nozzle tip` (41.16mm, lowest of six). Filament squashed
   to 2.02mm does not feed the same distance per gear rotation as round
   1.75mm, so one mechanical cause plausibly produced both — which is why the
   geometry numbers taken before this tension pass should be treated as
   provisional.

## Open questions

- **How is "good" recorded?** A pass/fail, or a score against the specific
  faults (smush / string / diameter)? A score is more useful for deriving
  across materials, and more work to ask for.
- **Which knobs are exposed?** `shear_temp` and `shear_speed` are the two that
  moved tip quality tonight. `push_length`, `sever_dist`, the cooling moves and
  `ease_speed` all exist and all matter, but a panel with nine sliders is not a
  calibration, it is a config editor with extra steps.
- **How many attempts before it is trusted?** One good tip could be luck. The
  encoder calibration refuses to save when three passes disagree by more than a
  few percent; there is no equivalent here because the judgement is not
  numeric.
- **Does the toolhead matter?** Step 12 found real per-path geometry
  differences. Whether tip forming differs between nominally identical
  toolheads is unknown and worth checking before the answer is saved per
  product line and assumed to travel.
