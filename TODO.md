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

- [ ] **The tip is 1.9 x 1.8mm, not 1.75.** No string, the swell a short
      section, and the same from run to run -- it is the sequence, not
      leftovers (Mike ran it twice back to back to check). Measured
      2026-10-09 on T0, PLA, and it is the shipped baseline in
      parameters.cfg. Mike: "plenty usable".
      Ruled out, all the same day unless dated: cold shear (removed: 1.9mm
      with a string); COOL_POS 35 -> 45 and TEMP 165 -> 155 (no change,
      2026-09-12); a purge, PURGE=15 (1.85 x 1.95 when cut at 165C, so no
      smaller, ~25s slower, and it strung when cut at 170C).
      Learned: **the cut temperature is the string lever** -- 165 clean,
      170 strings -- read back from Moonraker's temperature history, not
      estimated.
      Cooling moves: 8 measured 1.9 x 1.8, no string -- identical to 4
      (cut 166.1C, same as the baseline's 166.0). Doubling them bought
      nothing. 2 measured 1.93 x 1.78, no string (cut 165.6C) -- the same
      tip again within caliper scatter, in 3.1s of moves instead of ~6s. So
      anywhere from 2 to 8 the moves do not change the tip. 0 measured
      2.0 x 1.75, no string (cut 166.1C): same area, but more oval, and the
      long axis is what has to pass back through the tube and gears. So
      the moves do round the tip, and 2 is enough -- the fastest setting
      that matches 4 (one sample each, PLA only). Not yet the default:
      PETG and ASA are being tested at 2 first, since what holds for PLA
      may not hold for the two that string more.
      **PETG** (T1, Polymaker PETG, loaded at its profile's 250C), 2 moves,
      table TEMP 192 -- cut measured at 193.0C, clear 94%: **1.9 x 2.0,
      swell 3.3mm long, no string.** ~24% over round in cross-section
      against PLA's ~12%, and the same 2.0mm long axis as PLA with zero
      moves.
      Mike: the swell is ROUND, "like it's the cold side's shape" -- melt that
      set in the cold-side bore, a casting rather than a gear squeeze. So the
      bore sets the diameter and only the volume of excess melt, i.e. the
      LENGTH, can change. Cooling moves cannot change that (they add and
      remove nothing), so PETG at 4 moves was dropped as a test.
      PETG TEMP=185 (cut measured 186.2C, clear 94%): **1.9 x 2.0, swell
      2.75mm long, no string** -- 17% shorter than at 193C, same diameter.
      The cut temperature is the length lever.
      PETG TEMP=180 (cut 181.3C; the extrude floor was lowered, 180 -> 150):
      **the clear move got 20.1 of 34.7mm (58%)**, against 94% at 193 and at
      185, and Mike heard the extruder skipping. Either 180 is too cold to
      draw the stiffer swell out of the cold-side bore, or the load was bad.
      Mike does not snip the old tip between runs; it is purged out (84mm
      through the nozzle at 250C), but it still travels back through the
      gears and the cold side on the load. Mike: it was a BAD LOAD -- the
      stepper slipped, the tip never reached the melt -- so that run formed
      nothing at 180. Snipped and re-run: clear 94%, **1.9 x 2.0, swell
      3.0mm, less string, and SHEARED rather than pulled clean.** Too stiff.
      **PETG's value is 185** -- now the table's, in parameters.cfg, with
      the ladder beside it. coPETG follows it.
      What the bad load exposed is fixed separately: a load now proves its
      fill went in (encoder), and a park cannot report "parked" for a
      filament pushed further in than it retracted.
      **ASA** (T2, PolyLite ASA, loaded at the profile's 250C, snipped start,
      fill 95%), 2 moves, table TEMP 207 -- cut measured at 208.0C, clear
      86% (lowest yet): **1.9 x 1.85, swell 2.2mm, and a 1.1mm-thick STRING
      28mm long.** Shape better than PETG's; the cut is too hot. A strand
      that size can fold or break off and jam the next load, so it is not
      cosmetic. Next: 200, then 195, until the string goes or it shears. (Zero was the
      routine before 2026-09-01 and made 2.25mm balls, but with a 48mm hot
      pull that was fixed in the same commit, so that is not the same test.)
      Each pair of moves costs about 3s, so fewer is a small speed gain.
      *Done when:* a tip under 1.75mm, or Mike calls 1.9 x 1.8 good enough
      and this line goes.

- [ ] **The filament database is behind Polymaker's catalogue.** Mike,
      2026-10-09: the Panchroma Matte line has new colours -- Seafoam Green
      among them, and more -- other lines have new colours, and there are
      whole new product lines. The database has 38 Matte colours and no
      Seafoam anywhere; `polymaker.cfg` and `polymaker_panchroma.cfg` have not
      changed since 2026-09-07 and carry 35 product lines between them.
      Where it lives: `filaments/brands/*.cfg`, copied by `post_update.sh` to
      `~/printer_data/config/autoloader/filament_profiles/` WITHOUT deleting,
      so a brand file a user added survives. The printer's copies were
      identical to the repo's on 2026-10-09; pull-first again before editing.
      HANDOFF.md's backlog item 2 and its "Research brief -- filament colour
      database refresh" already describe the job for a research pass. New
      colours need real hex codes from the product pages, same as the
      existing rows ("hex codes verified from product pages"), not guesses.
      *Done when:* every current Polymaker line and colour is in the
      database, the KlipperScreen and Mainsail pickers show Seafoam Green
      under Panchroma Matte, and the files on the printer match the repo.

- [ ] **A profile's UNLOAD temperature is stored and shown, and nothing uses
      it.** SA_SET_MATERIAL takes UNLOAD_TEMP, every UI shows "230C unload",
      and no sequence reads `path_unload_temps`: an unload forms its tip at
      the per-material `tip_form_temp_<material>` instead (PETG 192, ASA 207).
      Its sibling, LOAD_TEMP, was ignored the same way until 2026-10-09.
      Decide which is right -- the tip table (measured for PLA, derived for
      the rest) or the profile's figure -- then either use it or stop showing
      it. "Never describe behaviour the machine no longer has."
      *Done when:* the unload temperature on screen is the one the machine
      actually forms at.

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
