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

- [ ] **Re-measure all six toolheads on one method.** Step 12 works and the
      code now uses its per-path figures, so the stale 50.0 defaults no longer
      decide anything. But the six stored sets were taken three different ways:
      T0-T3 and T5 with 5-10mm coarse overshoot, T4 after the midpoint
      correction, and none with the hot-shear change. That is why the guide
      flags T2 as the outlier — T2 did not move, T4 moved under it.
      *Done when:* all six are measured on the current build finishing on
      +1mm, and the gear-to-tip spread is a property of the hardware rather
      than of how each was taken.

- [ ] **`SA_CALIBRATE_BOWDEN`'s own blast at 160 is still untested.** That
      routine measures the lengths everything else is referenced against, so
      it wants its own run rather than inheriting confidence from the load's.
      The other two changes that sat beside it here are resolved: the hot-pull
      shear drop was tested on 2026-09-11 and disabled because it made the tip
      worse, and the retract stopping at the encoder ran on 2026-09-12
      ("Encoder quiet 2x after 93mm retract — filament cleared").
      *Done when:* it has run on the machine.

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

- [ ] **`generate.py`'s refresh mode can write a config that lies.** It puts
      existing VALUES back, which is right — it protects calibration from an
      update. But it adopts the template's new COMMENTS, so changing a comment
      and a value together produces a live file where the two disagree. On
      2026-09-12 the printer read `tip_form_shear_temp : 150.0` directly above
      a comment saying `OFF`. Third time this class has fired; the
      `tip_form_hot_shear_drop` instance cost an evening of tips formed at
      125C while the config said 0.
      *Done when:* refresh either carries the old comment with the old value,
      or reports the disagreement the way it already reports dropped settings.

- [ ] **`shear_temp` is a tuning value AND a mode switch.** The code branches
      on `if shear_temp > 0`, so a per-material row does not tune the mode, it
      RE-ENABLES it — and the global cannot turn it off. A real unload on
      2026-09-12 ran the shear because `tip_form_shear_temp_pla` said 150
      while the global said 0. The eleven per-material rows are commented out
      as a patch; there is still no way to express "tune PLA's shear
      temperature, leave the mode off".
      *Done when:* the mode has its own switch, separate from the value.

- [ ] **The shear branch returns before the cooling moves**
      (`sa_sequences.py`, the `return` after `_clear_past_gears`). That is why
      shear mode produced squashed, stringy tips for two evenings while the
      cooling-move path produces good ones. Shear mode is disabled rather than
      fixed, because disabling it was measured and fixing it was not.
      *Done when:* the shear path runs the cooling moves and a measured tip
      says whether the mode is worth having at all.

- [ ] **The tip-form warning blames the wrong thing.** "encoder saw 0.0mm of
      40.0mm. The tip is probably gripping and the extruder is stripping it.
      Raise SHEAR." fired twice on T4 when the real cause was no filament at
      the extruder sensor — the gears had nothing to grip. Following it would
      have meant walking a shear ladder that could never work.
      *Done when:* it checks the extruder sensor before blaming the shear.

## Never verified

- [ ] **The status table fits by measurement, not by construction.** `_row_h`
      predicts the status row, the table header, the button bar and the
      padding before any of them exists, and each prediction has been wrong
      once. It is now set from a real allocation log and carries `_FIT_SLACK`,
      which is a margin rather than a fix. A panel that measured itself after
      the first allocation and sized the rows from that would not need either.
      *Done when:* the table fits any head count and font size without a
      constant that had to be tuned by looking at it.

- [ ] **Walk the twelve-step CALIBRATION GUIDE on KLIPPERSCREEN.** The
      load/unload side of the touchscreen IS now proved: Mike ran T0-T5
      through the panels on 2026-09-12, which is what shook out the selection
      border that never rendered, the toggle that could not change colour, the
      duplicated swatch and the sizing. The GUIDE is the part still unwalked.
      Mainsail is done --
      Mike ran every step through it on 2026-09-11, which is what the whole
      day's measurements came out of, so the web side of the chain is proven
      by a full pass rather than by inspection.

      The touchscreen has not been walked since the guide grew to twelve, and
      it is the side with the history: KlipperScreen keeps only the LAST
      prompt_text, its guide panel once sat on step 1 all session because it
      read a status field Moonraker had never sent, and its panels are copied
      rather than symlinked so they can silently run old code.

      Checked in the code, so it does not need discovering at the machine:
      `_emit_ui_prompt` collapses the body into one prompt_text unless
      `ks_line` is passed, and step 12 does not pass it -- so its prompts,
      including the three-button nozzle hunt, should arrive whole.

      *Done when:* one pass from step 1 to step 12 on the touchscreen without
      dropping out of the guide, with step 12's grid showing millimetres and
      its three-button prompt readable.

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

- [ ] **Tip-forming calibration is designed but not built** —
      `docs/TIPFORM_CAL.md`. The last autoloader calibration still done by
      hand-editing a config. Form a tip, let the operator score it, save it
      **per product line** in `variables.cfg` — the tracked brand files are
      overwritten by `post_update.sh`, so a measured value written there is
      lost on the next update. Adds one link to the chain `cfg()` already
      resolves. One panel carrying the knobs, FORM TIP, and LOAD/UNLOAD, so a
      tuning session does not need a second screen.
      *Worth it because:* the shipped table has ONE measured row. PETG, ABS
      and ASA all carry PLA's -15C shear delta applied to a different print
      temperature, which assumes the delta transfers across glass
      transitions. Measuring PLA, PETG and one styrenic settles whether the
      table can honestly keep deriving.
      *Done when:* three materials are measured through it, saved to their
      product lines, and survive a reload — and the table either keeps
      deriving with evidence or stops claiming to.

- [ ] **Unloading a path parked BEFORE the encoder always errors.** The park
      leaves the tip ~5mm short of the encoder, so the encoder reads 0.0mm and
      the grip check trips — measured on path 1: "900mm driven, 0.0mm
      encoder". The filament IS there and the retract IS valid; the encoder
      simply cannot see it yet. Same blind-spot as the end of a retract, at
      the other end.
      *Done when:* a parked path unloads without a false jam.

- [ ] **Try a lower drive current for the wiggle check.** Mike's read from
      watching it: the drive is strong enough to rip filament out of the
      extruder gears rather than ease it. `selector_stall_current` already
      shows the pattern for a temporarily reduced current.
      *Done when:* a Branch B unload eases the tip out rather than snatching
      it, judged by watching the idler.

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
