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

- [ ] **Two advice fixes are in `main` but have never printed on the machine.**
      Both landed in 4e48d38, whose message describes only the HTML deletion
      they rode along with — recorded here because a commit message nobody
      re-reads is not a record.
      `SA_VERIFY_FEED` now names SCALE rather than a sampling ceiling below
      ~4 samples per encoder state. The arithmetic is verified (the threshold
      lands on 235mm/s, exactly the boundary CLAUDE.md documents) and the
      branch parses, but it has not EXECUTED: it fires only inside a failure
      the machine has to actually be in. (The second fix, the shear warning,
      went with cold shear on 2026-10-09.)
      *Done when:* a short `SA_VERIFY_FEED` pass prints the scale verdict.

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

- [ ] **The cooling-move tip is 1.9mm across a SHORT section, not 1.75.**
      It is the sequence, not leftovers: two identical `SA_FORM_TIP TOOL=0
      MATERIAL=PLA` runs back to back on 2026-10-09 gave the same size, so it
      is not material carried over from the shear run before them (Mike's
      test, run so nobody has to wonder again). No string either time.
      Tried, changed nothing: COOL_POS 35 -> 45, TEMP 165 -> 155.
      `PURGE=15` -- fresh filament through just before forming -- first ran
      clean on 2026-10-09 at 1.5mm/s: encoder 14.5 of 15mm (97%), back to
      165C before the sever, ease 20mm, clear 95%. Mike: **1.85mm, smaller
      than the baseline's 1.9, but it strings again.** (Its first attempt
      was not a valid test -- see the commit that fixed the purge's offset
      and temperature.)
      Likely why it strings: `_hold_temp_for_forming` stops waiting at
      tip_form_temp + 5 on the way DOWN. Without a purge the run then
      travels ~5s to the purge position before the sever, so it cuts near
      166C; after a purge it is already there and cuts at once, near 170C,
      still falling. 185 is known to string and 165 not, so a few degrees
      at the cut is the obvious difference between the two tips.
      Next test, overrides only: `PURGE=15 TEMP=160` -- the wait then ends
      at 165, where the baseline effectively cut. If the string goes and the
      size holds, make the purge path settle at the target instead.
      *Done when:* a tip under 1.75mm, or Mike calls 1.9mm-short good enough
      and this line goes.

- [ ] **`wget ... | bash`, the install line in the README, never shows the
      setup menu.** stdin is the pipe, so `[ -t 0 ]` is false and every
      question takes its default. That is now at least CORRECT -- before
      2026-10-09 an unattended install read every unanswered question as "no"
      -- but the person following the README is never asked anything, and the
      KlipperScreen add-on question in docs/INSTALL.md is never put to them.
      `bash <(wget -qO- URL)` or clone-then-run would keep the terminal.
      Not changed without Mike: it is the first command every user types.
      *Done when:* the README's install line reaches the menu, or the README
      says plainly that it does not and how to get it.

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

- [ ] **Mid-print runout stage 1 is built but the `low` branch is UNVERIFIED.**
      *Note, 2026-09-29:* from 2026-09-12 to 2026-09-29 this code was not on
      any branch at all — 91f15b2 deleted it while its message described
      adding it (see CLAUDE.md, the cycle, step 3). Restored and re-checked:
      `SA_SET_STATE TOOL=1 STATE=low` is accepted and the monitor returns it
      to `loaded`. That is the same half as before; the creating branch is
      still the unverified one.
      What has been exercised is only the recovery half: `SA_SET_STATE TOOL=1
      STATE=low` was accepted and the monitor returned the path to `loaded`
      within a second because its entry sensor still read FILAMENT. The branch
      that CREATES the state has never run, because it needs
      `print_stats.state == 'printing'` -- a real print job, not
      `idle_timeout`, which reads "Printing" for any gcode and is the bug this
      path works around. Commit 91f15b2 said "verified on the machine"; that
      claim covered the recovery branch only and Mike caught it.
      *Done when:* a print is running, the filament is pulled clear of a
      loaded path's entry sensor, and after the debounce the path reads `low`
      with its profile intact -- then feeding it back returns it to `loaded`.

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

- [ ] **Try a lower drive current for the wiggle check.** Mike's read from
      watching it: the drive is strong enough to rip filament out of the
      extruder gears rather than ease it. `selector_stall_current` already
      shows the pattern for a temporarily reduced current.
      *Done when:* a Branch B unload eases the tip out rather than snatching
      it, judged by watching the idler.

- [ ] **Make the Vue panel the end-user path, and polish it.** Mike's call
      2026-09-28, after checking what upstream is actually doing: the plugin
      needs Mainsail with custom-panel support, that support lives only in
      Lyx52's abandoned #2602 (bot-closed 2026-07-24, author never returned),
      and meteyou's system-panel refactor -- the likeliest route to a merged
      mechanism -- has **no branch, no issue and no timeline**. The repo has
      exactly three branches and none of them is it.
      So `main` currently ships a Mainsail panel that loads on this printer
      and nowhere else. `web/mainsail/AutoloaderPanel.vue` works on stock
      Mainsail at the cost of a rebuild per release, which is a real cost
      paid by us rather than a silent failure paid by the user.
      Keep `web/mainsail-plugin/` -- it is strictly better the day a
      mechanism lands, and it is the artifact that makes the case upstream.
      *Done when:* a fresh install on stock Mainsail shows a working panel,
      the rebuild step is documented or scripted, and the plugin is labelled
      as needing custom-panel support rather than presented as the default.

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
## Deferred by decision

*(nothing deferred right now)*

---

*Add an item when something is left undone. Delete it when the thing it names
proves itself — not when it feels finished.*
