# TODO

Open work, and what proves each item done.

**If a check already catches it, the check is the tracker — not this file.**
`scripts/check_drift.py` goes green on its own when those items are fixed, so
they are listed here for visibility only and need no edit when they close.
Anything nothing checks needs a line here, and needs removing by hand.

---

## Blocked on hardware

The rebuild is done and measured — see `docs/SYSTEMS_TEST_2026-09-10.md`.
Ceilings went from 50–175 (3.5x spread) to 200–215 (1.075x), and the shared
speed from 40 to 160mm/s. Both diagnosed faults were real and both fixes held.

- [ ] **`SA_VERIFY_FEED`'s verdict logic overstates.** It called a 1.4%
      residual an "ENCODER ceiling … counts going missing around 25mm/s". At
      25mm/s a state lasts ~37ms against 2ms sampling — about 19 samples —
      so aliasing cannot happen there, and the speed sweep's whole reference
      design depends on that. It should attribute a low-speed residual to
      scale or to ruler scatter, not to sampling.
      *Done when:* the verdict names scale first at speeds where aliasing is
      impossible.
- [ ] **`drive_rotation_distance` unchanged at 5.6911** through the rebuild,
      and the verify's ruler read 198.0 against a commanded 200.0.
      *Done when:* the same check on two more paths says whether that 1% is
      the drive (one fix) or per-path scatter (nothing to fix).

## Confirmed bugs, not yet fixed

- [ ] **Guide step 12: toolhead geometry, measured by the encoder.** The four
      toolhead distances are guesses today and one of them is provably wrong.
      The encoders are locked to their paths and count whatever the filament
      does -- including while the EXTRUDER is moving it and the drive gear is
      disengaged. That is what makes these measurable without a ruler, and what
      makes first power-up self-configuring.

      Measure three, derive two:

      | Distance | How |
      |---|---|
      | extruder sensor -> toolhead sensor | **already happens.** `_sync_feed_to_toolhead_sensor` runs drive+extruder until the toolhead sensor fires and throws the number away. Record it, with a step finer than `feed_step_size` -- the 40.0mm reading on 2026-09-11 was quantised to 10mm |
      | toolhead sensor -> nozzle tip (`fill_nozzle_length`) | hot nozzle, extrude slowly from the toolhead-sensor edge, operator presses a button when filament appears at the tip. Operator-confirmed because nothing senses the tip |
      | extruder sensor -> gear nip (`sensor_to_gear`) | **retract, never push.** Drive DISENGAGED, retract with the extruder: the path encoder still counts because it is fixed on the lane. It stops the instant the tip leaves the nip -- extruder turning, nothing moving. Then drive back until the extruder sensor clears; that gap is the answer |
      | `nozzle_to_sensor_dist` | **derived** = toolhead-to-nozzle + sensor-to-toolhead |
      | `nozzle_distance` (gears -> tip) | **derived** = (sensor-to-toolhead - sensor-to-gear) + toolhead-to-nozzle |

      **Pull, do not push, for the gear nip.** Feeding a tip into stationary
      gears would locate them too, and would buckle filament in the tube on
      overshoot. Losing grip on a retract is harmless.

      Per-path, like `bowden_length_N` -- toolheads can differ, the guide
      already renders per-path grids, and the three scalars it replaces are
      global only because nobody measured them.

      Step 12, after Bowden length: it needs filament reaching the extruder
      sensor and the toolhead sensors already proved. Touches `_GUIDE`,
      `_STEP_TOTAL`, `_STEP_NAMES` and both lookup tables -- `check_drift.py`
      covers all five.
      *Done when:* a fresh machine runs the guide end to end with the four
      distances measured rather than defaulted, and an unload clears the
      extruder sensor without the fallback firing.


- [ ] **`nozzle_to_sensor_dist` is wrong and the machine compensates.** The tip
      former's Phase 3 targets `nozzle_to_sensor_dist x 1.05` = 52.5mm to put
      the tip past the extruder sensor. On the 2026-09-11 T1 unload it reported
      `past gears, tip at 52mm` and the very next line was `Extruder sensor
      still active — sync drive+extruder to pull filament clear`. The fallback
      works, so nothing fails — it just does an extra retract every unload.
      Rebuilt from the unload's own moves the span is nearer **110mm**
      (33.5 shear + 17.5 clear + 59.4 retract-to-clear, two of the three
      encoder-measured). An earlier ~90 estimate here added the measured 40mm
      sensor-to-sensor span to the `fill_nozzle_length` default; this is better
      evidence and supersedes it. All three of
      `nozzle_to_sensor_dist`, `fill_nozzle_length` and `nozzle_distance` sit
      at their 50.0 default and describe different spans, so none of them has
      been measured.
      *Done when:* the three are measured on one toolhead and an unload clears
      the extruder sensor without the fallback firing.


- [ ] **Three installer questions are asked and the answers discarded.**
      `REGISTER_UPDATE_MANAGER` — `install.sh` writes `autoloader.ini`
      unconditionally. `KLIPPERSCREEN_ADDON_HOOK` — `post_update.sh` applies
      the patch regardless. `ADD_TOOLCHANGE_LED_HOOK` — nothing reads it and
      the `toolchanger.cfg` hook is still a manual edit.
      Worse than documentation drift: the operator makes a choice and the
      machine ignores it silently. Either wire each up in `install.sh` /
      `generate.py`, or drop the question.
      *Done when:* `scripts/check_drift.py` passes all five checks. It is red
      today for exactly this. Confirming a change here means running
      `install.sh` on a machine that has never seen the project — the reason
      it was reported rather than guessed at.

## Never verified

- [ ] **Walk the eleven-step chain start to finish on both UIs.** Individual
      steps have all run; the chain as a whole has not since the guide was
      consolidated from three definitions into one. This is the thing that
      would waste a rebuild evening.
      *Done when:* one pass from step 1 to step 11 without dropping out of the
      guide, on Mainsail and on the touchscreen.

- [ ] **Mid-print runout is designed but not built** — `docs/RUNOUT_MIDPRINT.md`.
      Today a roll running out mid-print sets the path `empty` and wipes the
      profile after 10s (`autoloader.py:636-645`) while the print carries on
      consuming the ~1400mm still in the tube. Designed: a `low` flag that
      keeps the profile, a budget clocked off **the encoder going quiet** (the
      tail passing it is measured, not estimated), a pause with a reserve, a
      purge to the extruder sensor to pin the tail, then reload and
      `purge = remaining + runout_purge_extra`.
      **This is what stops runouts producing the state `RECOVERY.md` exists
      for.** Two traps written up: the profile wipe fires while paused because
      `_is_printing()` reads False, so `low` must be excluded unconditionally;
      and net consumption must come from the extruder, never the encoder —
      direction is told, not sensed, so every retraction would count as feed.
      *`sensor_to_gear` is now bounded below 40mm* by the 2026-09-11 T1 load
      (sync feed ran 40.0mm from the extruder sensor to the toolhead sensor,
      and the gears are between them), so the reserve after the purge-to-clear
      is 50-90mm. An exact figure still wants a ruler on one toolhead.
      *Done when:* a real mid-print runout warns, pauses with the tail still
      short of the gears, swaps and resumes with no colour carry-over.

- [ ] **Runout recovery is designed but not built** — `docs/RECOVERY.md`.
      A path with entry clear and filament still in the head is currently
      refused by both load and unload. Settled: the new roll pushes the
      remnant out (the extruder cannot move what it no longer grips), heat to
      `max(old, new)`, confirm the stashed profile first, explicit
      `SA_RECOVER TOOL=N` rather than automatic.
      *Done when:* the routine exists AND a real broken-filament path recovers
      to a normal loaded state, verified by all three sensors.

## Repo hygiene

None of this changes behaviour. It is what makes the repo followable.

- [ ] **17 remote branches for a project with three.** Delete what is spent:
      - `backup/pre-history-rewrite-2026-09-07` is the SAME COMMIT as
        `old-dev` (`f9eecd8a`). One of the two is pure duplication — keep
        `old-dev`, which CLAUDE.md documents, and drop the other.
      - five `claude/*` session branches, all five months old
      - six `printer-backup/known-good-*` snapshots, the newest six days old
      - `backup/2026-05-04-stable`, four months old
      *Done when:* `git ls-remote --heads origin` lists `main`, `dev`,
      `printer-dev`, `old-dev` and whichever backups you consciously keep.
- [ ] **Two dead HTML mockups**, 2290 lines between them, referenced by
      nothing: `autoloader/autoloader_panel.html` (1478) and
      `autoloader/autoloader_ui.html` (812). `post_update.sh` copies
      `autoloader/*.html` to the printer, so both ship to every install.
      *Done when:* deleted, or moved somewhere that says they are mockups.
- [ ] **`web/mainsail/AutoloaderPanel.vue`** (357 lines) is marked superseded
      by `web/mainsail-plugin/` and referenced only by the line saying so.
      Decide: delete, or keep and say why in one sentence.
- [ ] **Two untracked files in the printer's checkout** —
      `KlipperScreen/sa_ui_prefs.json` and `klipperscreen`. They show as dirt
      in every `git status` on the machine. Find out what writes them, then
      either gitignore them or move them out of the repo.
- [ ] **Test harnesses live in a scratch directory**, not the repo. The drift
      checks are committed; the ad-hoc ones that verified the guide fixes and
      the KlipperScreen add-on loader are not.
      *Done when:* the ones worth keeping are under `tests/` and runnable.

## Deferred by decision

- [ ] **KlipperScreen PR #1770 lands** → four files here need updating,
      because the add-on hook will ship **off by default** and
      `addons/sa_autoloader.py` will stop loading on a fresh install:
      `scripts/patch_klipperscreen.sh` (detect that upstream already has the
      hook and skip), `install.sh` (turn `enable_addons` on, or prompt),
      `docs/INSTALL.md`, and CLAUDE.md's project surface row.
      Deliberately not started — review could still change the shape.
      *Done when:* the PR is merged AND all four are updated together. A
      partial job leaves a silent failure.

---

*Add an item when something is left undone. Delete it when the thing it names
proves itself — not when it feels finished.*
