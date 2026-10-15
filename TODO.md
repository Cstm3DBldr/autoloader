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
      (Zero was the routine before 2026-09-01 and made 2.25mm balls, but
      with a 48mm hot pull that was fixed in the same commit, so that is not
      the same test.) Each pair of moves costs about 3s, so fewer is a small
      speed gain.
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
      cosmetic.
      ASA TEMP=200 (2026-10-11; the first try wedged short of the melt, fill
      24%, and was recovered by SA_FORM_TIP's new recovery branch; the end came
      back clean, then the same spool loaded at 93%): cut 199.5C, clear 89%,
      **1.85 x 2.0, swell 3.5mm, and a 0.33mm string 25mm long.** Colder
      thinned the string from 1.1 to 0.33mm but barely shortened it, and the
      swell grew 2.2 -> 3.5mm -- the opposite of PETG, where colder shortened
      it until it sheared.
      ASA TEMP=195 (cut 195.1C, fill 93%, clear 89%): **1.9 x 2.0, swell
      3.0mm, and a 0.2mm string 62mm long.** Thinner again, but more than
      twice as long -- about the whole distance the tip travels after the
      sever (ease 20mm + 2 cooling moves + 36.9mm clear), so at 195 the thread
      no longer breaks at all and is drawn the length of the retract. Colder
      trades a thick short string for a fine long one rather than removing
      it.
      ASA TEMP=195 SEVER=38 (Mike's proposal: pull fast as far as the
      toolhead allows, then back down and cool; 5746a07 lets the sever pass
      the cooling zone, capped 10mm short of the toolhead sensor): cut
      195.3C, back down 3mm, clear 89%: **1.95 x 1.85, swell 3.5mm, NO
      STRING.**
      **Standardised 2026-10-11 (Mike: "id rather standardize the unload then
      need a bunch of settings"):** the 38mm sever and 2 cooling moves are now
      the default for every material; per material only the temperature
      varies (PLA 165, PETG 185, ASA 195). *Next:* plain `SA_FORM_TIP TOOL=N`
      with no overrides on T0 PLA, T1 PETG and T2 ASA, measured against their
      15mm-sever results. A material that gets worse is the evidence for a
      per-material override -- not before.
      **Done 2026-10-11, all three string-free on the standard:** T0 PLA
      1.85 x 1.95 with no swell section (better than 15mm's 1.93 x 1.78 with
      one); T1 PETG 1.85 x 2.0, swell 3.0mm (2.75 before -- held); T2 ASA
      1.75 x 2.0, swell 3.5mm (repeats). No material needs its own move.
      **Repeatability (Mike: no promote until a formed tip loads and unloads
      well repeatedly).** `SA_TIP_CYCLE` (c827c67) reloads one UNSNIPPED tip
      over ~100mm instead of the Bowden. T0 PLA, 5 cycles, 2026-10-11: in at
      98.6 / 109.7 / 109.3 / 108.9 / 109.8mm (100 back + the ~10mm the pull
      overshoots the sensor), fill 93 / 91 / 91 / 93 / 93%, clear 93 / 93 /
      90 / 93 / 93%, extruder sensor clear after 30mm every time. No failure.
      Then recovery with the standard calls on that tip (left 'unknown',
      ~1400mm in, 100mm behind the sensor): `SA_LOAD TOOL=0` skipped the park
      (271050c -- the park would have pulled 800mm, said PARK FAILED and
      refused), blasted until the sensor stopped it after 100.6mm, filled 91%;
      then `SA_RESPOND VALUE=unload:0` formed a tip (clear 95%), retracted
      the Bowden and parked 5.0mm before the encoder.
      T1 PETG, 5 cycles: in 110-111mm, fill 94/94/95/94/94%, clear
      91/91/88/91/91%, sensor clear after 30mm each time; Mike: "tips looked
      good". The standard SA_UNLOAD from there then called a false jam
      ("encoder stopped after 1371.3mm") -- the loop only knew "past the
      encoder" beyond a full Bowden. Fixed (a0c3ebe): re-run, it said "Tip is
      past the encoder after 1390mm" and parked, but crawled 10mm at a time for
      114s. Mike: far too slow. a80d5c5 makes an unload from 'unknown' find the
      extruder sensor first (fast, sensor-stopped) and then unload normally;
      the crawl is only the fallback. (A first attempt was emergency-stopped
      during its G28 when Mike had to leave, 2026-10-11 23:35; no filament had
      moved.) **Run 2026-10-12:** one more cycle (in 98.5mm, fill 94%, clear
      91%), then `SA_UNLOAD TOOL=1` from 'unknown': found the extruder sensor
      after 110.4mm in 2.6s, blasted back 1413mm in 9.6s, parked (quiet after
      83mm, re-acquired after 16mm -- clear of the 4mm snag check). 27s from
      "position unknown" to parked, against ~130s for the crawl. Saved
      'partial'.
      T2 ASA, 2026-10-12: cycles 1-3 clean (in 98.5/109.9/110.2mm, toolhead
      sensor after 50mm each, fill 93/93/94%, clear 89% each). **Cycle 4
      wedged: toolhead sensor after 40mm -- 10mm early -- then fill 34%.**
      Something sat ahead of the tip: tripped the sensor first, then blocked
      the melt. Fill check failed it, heater off, test stopped, unload not
      run. Leading guess: a piece of cycle 3's tip (ASA's swell is the
      longest, 3.5mm) broke off and stayed in the toolhead -- but T2 also
      wedged on 10-10 from a clean snipped end, and Mike notes these are the
      OLD extruders. Separating them: the cycle test with ASA on a head that
      passed, or PLA on T2 -- Mike is swapping the T0 and T2 rolls for that.
      Recovered with `SA_FORM_TIP TOOL=2`: recovery branch, unload (clear 60%,
      expected -- the wedged tip sat ~20mm above where the clear move assumes),
      sync retract, blast back, parked (re-acquired after 20mm), saved
      'partial', and **cal_state empty afterwards -- 6da7e2a's dialog close
      seen working.**
      **Swap test (Mike swapped the T0 and T2 rolls, ends snipped, looked
      fine).** ASA on T0, 195C + 38mm sever: fills 97/96/96/95%, clears
      101/95/95/95%, but Mike saw a "decent length string" on cycles 1, 3 and
      4 -- and **cycle 5 wedged: fill 16%** (toolhead sensor at the normal
      50mm this time, so the tip itself, not something ahead of it). ASA has
      now failed a reload on two different heads, so it follows the material,
      not T2's extruder; 195C is on the edge -- clean twice on T2, strings on
      T0. Next: 190C (SA_TIP_CYCLE TEMP=, 1dcd44d), watching for strings and
      for shear, which PETG hit 5C under its best.
      PLA on T2: cycles 1-4 clean (fill 91/92/91/92%, clear 86/86/83/86%),
      **cycle 5 stopped before the toolhead sensor**: the encoder says the tip
      went ~41mm past the extruder sensor (the toolhead sensor is 49mm on)
      and no further, while the sync feed drove its full 200mm and left T2 at
      205C (both fixed in def47ed). So T2 also
      fails with PLA, in a different place -- the zone between its gears and
      its toolhead sensor, where T2's ASA wedge tripped that sensor 10mm early.
      Reading: T2 likely has debris or a fault in that zone (Mike then said
      the extruders are probably already his new printed ones, so debris is
      the stronger suspect), AND ASA strings/wedges on its own (T0).
      T2 recovered with a plain `SA_UNLOAD TOOL=2` -- **the first run of
      c89d00b's fast Branch B ending:** wiggle 4.81mm, extruder sensor clear
      after 40mm, sensor-stopped zero 8.0mm, blast 1381mm, park (re-acquired
      after 16mm). 28s from "filament confirmed" to parked, against 63-66s for
      the stepped retract. The tip came back freely, so whatever stopped it
      is ahead of it, not holding it. Mike: the T2 PLA tips were "perfect no
      string on any test", so **stringing is ASA's alone**.
      T0's ASA recovered with `SA_FORM_TIP TOOL=0` -- **the first run of
      c89d00b's fast Branch A ending:** pull-out 3.5s (sensor clear after
      30mm) instead of 8.3s, sensor-stopped zero 0.5s (9.7mm) instead of
      10.9s; heater off to parked 31s against 46s on T2's recovery that
      morning. Clear 61% (the stuck tip sat high, as on T2).
      **ASA at 190C on T0, snipped end, 5 cycles: all clean.** Cycle 1 came
      straight from the gate in one sensor-stopped move (1508.1mm against
      1516.6 calibrated -- d546565's single sensor hit, seen); fills 94 / 94
      / 94 / 95 / 94%, clears 93 / 95 / 95 / 98 / 98% (195C gave 95%),
      toolhead sensor at 50mm every time. Then the fast unload from the tube:
      found at 116.0mm, blast, parked. **But it strung every cycle (Mike):**
      cycle 1 a tiny string; 2 worse, "a blob on a string"; 3 the same; 4
      and 5 "long skinny string" -- getting worse as the run went on, which
      fits heat soak building over back-to-back cycles. So colder does not
      cure ASA either: 208, 200, 195 and 190C all string with the standard
      pull. Mike: "maybe asa is to elastic and needs a tip melt" -- the
      skinny dip, built 2026-10-12 (tip_form_dip_len, DIP=).
      **Dip test 1, 2026-10-13, T0, snipped: TEMP=190 DIP=20** (tip from the
      35mm cooling zone to 15mm above the nozzle, at 30mm/s, out at 70):
      strings on cycles 1, 3, 4 and 5, none on 2 (Mike). All five loaded,
      none failed: fills 96 / 95 / 96 / 95 / **86%**, clears 95 / 98 / 98 /
      98 / 95%. 20mm is not enough -- probably short of the heat. Cycle 5's
      fill fell to 86% after four at 95-96, the fifth cycle again: more
      weight on heat soak.
      **Dip test 2, same day, T0 snipped: TEMP=190 DIP=28 DIP_PAUSE=0.5**
      (7mm above the nozzle for half a second): strings on 1 and 3, NONE on
      2, 4 and 5 (Mike). Fills 95 / 95 / 94 / 94 / 97% (cycle 5 back up),
      clears 98 / 98 / 101 / 98 / 95% -- no sign of a re-melted tip. So far:
      no dip 0/5 clean, DIP=20 1/5, DIP=28 + 0.5s 3/5. Better, not cured.
      Both dip runs alternated string / none at first, which suggests each
      cycle inherits something from the one before. Next: the exit speed --
      the clear move leaves the melt at 8mm/s, slow enough to draw a string;
      `EASE=` now sets only that exit and the 3mm back-down, so
      `SA_TIP_CYCLE TOOL=0 TEMP=190 EASE=50` tests it with no code change.
      **Prusa's ASA cooling moves (docs/MATERIAL_PLAN.md), 2026-10-14, T0,
      snipped: TEMP=195 COOL_MOVES=3 COOL_LEN=15 COOL_IN=5 COOL_OUT=2.5** --
      three slow moves instead of two fast ones, nothing else changed. All 5
      loaded (fills 94 / 91 / 84 / 94 / 95%, clears 95 / 101 / 95 / 95 / 95%),
      no failures, fast unload parked it. **Mike: cycles 3, 4 and 5 NO string**
      (1-2 not seen) -- the first ASA run clean on every cycle observed. One
      reload (cycle 3, the 84%) skipped a couple of times and pushed through.
      ~30s more per cycle. Next: repeat on T0 with every cycle watched, then
      T2; if it holds, ASA's own rows: tip_form_cooling_moves_asa 3,
      tip_form_cooling_len_asa 15, tip_form_cool_speed_in_asa 5,
      tip_form_cool_speed_out_asa 2.5 (Mike: per material, "temp and cooling
      moves unless ... they need more work").
      **Second Prusa run, 2026-10-14 23:08 (T0, from a Prusa tip at the gate):**
      cycles 1-4 loaded at 94% with clears of 95%, at only 13-16s at 250C
      before each fill -- the same gap as the 20% failures earlier that
      night, so a short soak alone is NOT what failed those. Mike: cycles
      1-3 no string, **cycle 4 a string**. Cycle 5 then found the toolhead
      sensor "already active", skipped the push, and the fill read 0.0mm:
      **the string had left a piece in the toolhead sensor** (Mike saw it).
      SA_RECOVER pushed it out (70mm at 101%, then a 103mm purge). The next
      Prusa tip formed cleanly (clear 98%) and **left another piece in the
      sensor**. So a string is not cosmetic: when it snaps it can lodge in
      the toolhead sensor and block the next load. 2 of the last 7 Prusa
      tips did it. Both are now caught (9cf788e: the load stops and names
      SA_RECOVER; the unload warns), but the cause -- the string -- is not.
      **Mike found the mechanism (2026-10-14):** the toolhead sensor is a
      ball type, and tiny string debris lodged in the BALL passage held the
      ball triggered -- the filament path was clear. He also pulled a
      decent string out of the filament passage, not enough to trip the
      sensor: the likely wedge behind the 20% fills (a ~2mm tip plus a
      string in a 2mm bore).
      **Run 2, cold, 2026-10-14 23:58 (the decider):** after a 25min pause,
      nozzle 25.7C, passage and sensor cleaned, RECOVER=0. Cycle 1 loaded
      at 94% with only 14s at 250C -- the conditions of the 22:09 failure
      -- then cycles 2-3 at 94% / 95% (clears 101 / 95 / 93%), no strings
      seen. **So it was never the cold nozzle or the soak: it was string
      debris.** Heat soak and the slowed fill are dropped; loads stay full
      speed. Cycle 4 stopped BEFORE the fill on the new check -- the ball
      stuck again, after tips with no visible string. Third stuck ball of
      the night, all T0 on ASA, in about 12 tips.
      *Open:* (1) the ball sensor is now the weakest link -- a hardware
      question for Mike (a passage debris cannot settle in, or another
      sensor type); (2) check the toolhead sensor reads clear right after
      every pull-back, so a stuck ball is reported then, not at the next
      load; (3) SA_FORM_TIP's retract re-formed a second tip when the stuck
      sensor said "loaded" -- after an encoder-confirmed clear it should
      believe the encoder.
      **EASE=50, same day: ruled out, and worse.** Strings on 2, 3 and 5 (1
      not seen); cycle 4 a bad load (fill 62%) -- **the first real failure
      the auto-recovery met, and it worked:** recovered to the gate, cycle 5
      reloaded from there (1509.4mm in one sensor-stopped move, fill 94%).
      Then cycle 5's pull-back moved the filament 120mm by the encoder with
      the extruder sensor still reading: most likely the tip, pulled out of
      the melt at 50mm/s still soft, snapped at the gears and left a piece
      at the sensor. (That stop left T0 'loaded'; fixed to 'unknown'.)
      Next: DIP=30 DIP_PAUSE=1, the deepest dip, held a second.
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

## Requested, not built

- [ ] **A high-speed switch, and a last guide page that turns it on.** Mike,
      2026-10-12, after the 27s unload: "we should have a mode for testing
      for slow loads and unloads for first time users to ensure everything
      works, but otherwise we run full speed". Shape agreed:
      - a setting, `high_speed_moves`, OFF on a fresh install and stored in
        variables.cfg (a user setting, so never in a tracked file). Off, the
        blast and the unload blast run at `feed_speed` instead of
        `encoder_max_speed`; nothing else changes, so a first load is the
        same sequence, only watchable.
      - a final guide page in `_GUIDE`: load and unload every channel at the
        slow speed; when all of them work, flip the switch on that page --
        which finishes the guide. The page says the switch also lives in
        Settings, for troubleshooting.
      - the switch in both UIs' settings. The guide page renders itself on
        both (it is derived), but the settings screens are not.
      This machine is already proven, so it would ship ON here.
      *Done when:* a fresh install loads slowly, the last guide page turns
      on full speed, and Settings can turn it back off.

- [ ] **Recover a failed load automatically, and retry -- three tries,
      slower each time.** Mike approved "one retry then stop" (2026-10-12),
      then 2026-10-14: "try 3 times but slow down progressivly on each retry
      to see if its a speed problem and we monitor length so we know to abort
      when it doesnt sense movement". SA_LOAD: a failure at the nozzle unloads
      to the gate, waits 5s, and retries at 50% then 25% of the nozzle-stage
      speed (sync push + fill + purge; the blast is sensor-stopped and keeps
      its speed); a load that only went in slowed down is reported as a speed
      limit at that head. The fill is now checked every 10mm and stops after
      two pieces with almost no encoder motion, instead of extruding all of
      it and checking at the end. **3-try version BUILT 2026-10-14, not yet
      deployed or seen.** The Branch A purge-only check now counts as a
      nozzle failure too, so it retries like the others.
      **Seen 2026-10-14, T0 ASA at 250C:** three full-speed fills failed in a
      row at 19-22%, the third with a fresh snipped end -- so not the tip. The
      new 10mm check stopped the third after 40mm instead of 88. Try 2 at 50%
      (sync 25mm/s, fill 124mm/min = ~5mm3/s) loaded at 94%, and the console
      said so. Then, loaded and hot, 30mm at the FULL rate (249mm/min): drive
      motor off 97%, drive motor on and holding 93%; at half rate 97%. So it
      is not the drive gear holding the filament and not the nozzle's
      steady-state flow: **it is the first ~20mm into a just-reheated
      nozzle at full rate** (the fills began 6-14s after the thermistor read
      250). *Proposed, awaiting Mike:* fill (toolhead sensor -> tip) at half
      rate, purge at full, sync at 25mm/s -- about +13s a load; or a soak
      before the fill. Not separated yet: whether the sync speed or the fill
      rate is the one that matters -- one load each way would say.
      **Soak test, same night (Mike: Rapido 2 Plus UHF, PT1000, big heater --
      "the heater absolutly could heat fast then reach temp quick and the
      plastic still not be fully melted"):** unload, cool T0 below 120C, heat
      to 250 and hold, then a FULL-speed SA_LOAD: 93s at 250 before the fill
      -> **94%, first try.** Against 8-15s -> 19-22% on the three failures.
      Our wait is already Klipper's M109 rule (SET_TOOL_TEMPERATURE WAIT=1:
      within 1C and < 0.1C/s), releasing ~4-5s after first touching target;
      PRINT_START differs in time, not rule (M109 150, then target-30 and a
      clean, G28, mesh, then target). *Catch:* heating at load start alone
      adds no soak -- 100->250C is ~34s, park + blast ~24s. *Proposed:* heat
      at load start + the first ~20mm of the fill at half rate (~19s faster
      than today, untested), fallback a hold-at-temperature timer.
      *Found on the way:* the profile's PURGE_SPEED is stored and shown but
      the load never reads it -- same as UNLOAD_TEMP.
      *Fixed on the way (8c26f4a):* a load from `unknown` whose grip check
      put the filament on the extruder sensor refused with "will not blast
      blind"; the sensor reading IS the datum, so it now carries on. SA_TIP_CYCLE: recovers
      and carries on, two in a row stop it. *Done when:* a real failure is
      seen recovering and retrying -- the original request follows. Mike,
      2026-10-12, after T0 and T2 both failed their 5th reload: "shouldn't we
      build in an auto recover when we sense an error so we don't fail a print
      and or make sure testing finishes (forward thinking for mmu use)".
      The recovery is proven: the unload brought a wedged load back to the
      gate every time it was asked (T2 on 10-11 and twice on 10-12, T0 once).
      As proposed and approved:
      - a load that fails the fill check or stalls short of the toolhead
        sensor unloads itself to the gate, waits, and tries once more;
      - a second failure stops and asks (a pause, under a print) instead of
        retrying into a grind;
      - `SA_TIP_CYCLE` recovers and CONTINUES, counting failures, so a test
        always finishes with a rate ("5 cycles, 1 recovered").
      This is the mechanism an in-print colour swap (multi-channel heads)
      will need, which is why it is worth building before that.
      *Also open -- why the 4th/5th cycle:* **every SA_TIP_CYCLE load
      failure to 2026-10-13 came on cycle 4 or 5, none on 1-3, across ~10
      runs (~50 cycles):** T2 ASA c4 (34%), T0 ASA c5 (16%), T2 PLA c5 (stall
      short of the toolhead sensor), T0 ASA EASE=50 c4 (62%). ASA is in 5 of
      the 7 filament failures to date; the failures follow the material,
      not the head. Leading theory: heat soak into the cold side over
      back-to-back heating with 20s holds. Test: `SA_TIP_CYCLE TOOL=2
      HOLD=120` with PLA, which keeps ASA's strings out of it.
      **Seen 2026-10-13:** the auto-recovery on a real failure (T0 c4, 62% ->
      recovered -> c5 loaded 94%).

- [ ] **Toolhead LEDs: dark colours breathe to black, and half the heads
      sometimes do nothing.** Mike, 2026-10-12. Two separate things:
      1. *Dark colours go fully dark.* Why, in the code: the pulse is the
         filament colour times an envelope that runs from `min_brightness`
         (0.0) to `max_brightness` (0.40). A colour whose brightest channel is
         under 0.15 is first rescaled to 0.0075 (`_hex_to_logo_rgb`, mirroring
         the LOCKED pipeline in `_sa_set_logo_filament` -- see CLAUDE.md's
         LED row). Black #0D0D0D therefore peaks at 0.0075 x 0.40 = 0.003,
         under one 8-bit step, and the trough is exactly off. Mike's fix:
         an absolute floor just above off; the colour's own brightness as the
         top of its pulse; and the SAME period for every head, so a dark
         colour takes proportionally smaller steps (his example: 25 levels
         against 255, so each step is 25/255 of the others') -- it fades in
         time with its neighbours and never switches off when they do not.
         This changes the locked pipeline, by Mike's request; change the
         macro and the animator together, and re-run the
         `_SA_LED_TEST_CASELIGHT_*` checks.
      2. *Sometimes only T0-T2 light, T3-T5 not.* Not seen recently -- all six
         were breathing correctly at the time of the report -- so it may be
         intermittent or already gone. Worth checking first whether it lines
         up with a restart, a toolchange or one MCU group.
      *Done when:* black and other dark filaments visibly breathe on the
      same beat as the rest without ever going dark, and the half-dark case
      is either reproduced and fixed or seen not to happen over a few days.

- [ ] **More than one channel per toolhead (MMU-style, later).** Mike,
      2026-10-12: "not something i need now but people are crazy and i know
      it will get asked for" -- Happy Hare runs 4-16 lanes into one toolhead.
      First step he described: 6 toolheads, 7 channels, the 7th tied to a
      chosen toolhead during calibration.
      - *Hardware:* a splitter in the PTFE AFTER both channels' encoders, so
        each channel keeps its own entry sensor, encoder and park; the
        extruder and toolhead sensors are per toolhead and become shared.
      - *Gating:* never load a channel while another channel on the same
        toolhead is past the splitter -- the two would meet in it. A load
        requires every sibling channel parked; an unload parks behind the
        splitter, not just at the gate.
      - *Calibration:* a channel -> toolhead map, set in the guide, and a
        Bowden length per channel (each one's route to the shared extruder
        sensor differs). Splitter position per channel, to know "parked
        behind the splitter".
      - *Slicer:* virtual tools (T6...) mapped to (toolhead, channel). A
        virtual tool change on the mounted head is an in-print swap: form a
        tip, unload to behind the splitter, load the other channel, purge.
        That is where today's tip work stops being about spool changes and
        becomes per-colour-change, so its reliability numbers matter.
      - *State:* per toolhead, which channel is loaded.
      - *Then:* generalise from 2 to 3-4 channels per toolhead, with the
        hardware and calibration each needs.
      CLAUDE.md's "NOT an MMU" now says this is planned. Reference Happy Hare
      for the ideas; do not copy it.
      **Second use of the same hardware: auto-refill (Mike, 2026-10-14).**
      Group channels on one toolhead with the SAME profile and the group is
      one slicer tool that never runs out -- "the roll could be completely
      used". Shape:
      - *Grouping* set in the guide, any channels the user's tubing joins:
        pairs (T0+T1, T2+T3, ...), fours on a 4-way splitter, or whatever
        stacked units line up.
      - *Two modes per group.* Multi-colour: each channel its own slicer tool
        (T0 = T0A, T6 = T0B, T7 = T0C, ...). Auto-refill: one tool; switch
        channels automatically ONLY when the profiles match exactly
        (material, brand, line, colour -- all logged). A separate opt-in
        "use-up" mode relaxes that to the same chemistry, for emptying
        part rolls into prints where colour does not matter.
      - *Detection chain* (most of it designed in docs/RUNOUT_MIDPRINT.md):
        entry sensor clears -> `low`, profile kept; the encoder going quiet
        while the extruder still pulls confirms it (a measured datum); the
        extruder sensor clearing is the runout trigger -> pause -> load the
        matching channel, whose filament pushes the old tail through (the
        SA_RECOVER mechanism) -> purge, fill check, resume.
      - What already exists for it: the sensor-stopped blast (a splitter
        cannot be overrun), the fill check with retries, `low`, recovery.
      - *Mike, 2026-10-14:* the splitter layout is fixed hardware, but the
        mapping is software -- set in the guide or Settings and changeable
        there. The slicer only ever says T0, T1, T2 ..., so the extra
        channels are emulated as tool numbers, and **a T number with no
        channel behind it must pause or error** (T9 on a machine set up for
        T0-T6). This matters because **Klipper does not stop on it by
        itself**: an undefined command goes to `cmd_default`, which ends in
        `respond_info('Unknown command:"%s"')` -- an info line -- and the
        print carries on with whatever tool is mounted
        (klippy/gcode.py L221, L316 at 9cb9975; virtual_sdcard only stops
        on a gcode.error). Best caught before the print starts: Happy Hare's
        Moonraker component scans the file for T<n> and its start check
        pauses on an empty gate (presence only; material/colour checks are
        listed there as "Future").
      - *Research, 2026-10-14 (sources in the session; summary):*
        - **Toolhead fallback ships today on toolchangers and needs no
          splitter**: Prusa XL Tools Mapping ("If Tool 1 runs out of
          filament, then Tool 4 will be used"), Snapmaker U1 auto-refill
          (same brand, material, colour; ascending tool order), AFC's runout
          lane on another extruder. klipper-toolchanger already remaps at
          runtime (`ASSIGN_TOOL TOOL=<name> N=<n>`; the vacated number is
          left unassigned). Prusa's join: heat the new head while the old
          one unloads, park, purge, return in nozzle coordinates, resync E.
          Reported weak spot: an oozy layer at the join.
        - **Runout vs jam by the upstream sensor** -- entry clear = runout,
          entry still full = jam/break -- is what AFC, Happy Hare and Bambu
          AMS Lite all do. Our chain matches.
        - **Pushing the old tail through the nozzle is the risky step.**
          Happy Hare, AFC and MMU3 pull the tail back and eject it instead;
          Bambu flushes it only when the tail has already left the feeder;
          U1 owners report jams from exactly the butt-to-butt push. Our
          drive can still grip the tail only until it passes the gear, so
          "pull back" means acting at the entry sensor and wasting what is
          in the tube (~1.5m, ~4-5g); "consume" means the push. A choice
          for when this is built, not now.
        - Matching rules elsewhere: Bambu brand + type + colour + temp
          "exactly the same"; Anycubic refuses same colour, other material.
        - Staging the next lane DURING a print is likely out: a
          manual_stepper move with SYNC dwells the toolhead for its length
          (a reading of manual_stepper.py, not measured).

## Never verified

- [ ] **Recovery from a stopped load, unload or park (54b88a6).** Four power
      losses on 2026-10-10 brought every path back as whatever the monitor
      last wrote, because the sequences only set states in memory; T2 came
      back 'partial' (parked at the gate) with its filament wedged past the
      toolhead sensor from a failed fill. *Verified 2026-10-11:* the boot
      turned that 'partial' into 'unknown' on disk and in memory, named
      SA_UNLOAD once, and queued no park. Then `SA_FORM_TIP TOOL=2` on it took
      the recovery branch: homed, toolchanger found T2 by its probe, unloaded
      (clear move 91%, extruder sensor cleared at 60.6mm), parked at the gate,
      formed nothing, and variables.cfg read 'partial' afterwards. The
      unload's own "what next?" dialog appeared at the end, and its LOAD would
      reload the end that jammed before it is snipped; the recovery now closes
      it (not yet seen). *Not yet run:* a load or park
      interrupted by a Klipper restart (the path
      should come back 'unknown', not 'partial'); `SA_PARK` with filament
      past the extruder sensor (should refuse). *Done when:* each has been
      seen on the machine.

- [ ] **The load blast stops on the extruder sensor (a1f186c).** Each
      extruder sensor pin is shared with an endstop on the drive motor, and
      the blast is a homing move capped at 110% of bowden_length_N, reporting
      fed length against calibrated. *Verified 2026-10-11, no motion:* Klipper
      came up with endstops on all six paths after its own automated MCU
      restart (CRC mismatch, expected -- the boards' config changed), and the
      filament sensors still report. First load (T2, 2026-10-11, after
      ea85c12 fixed an import that shut Klipper down before the first blast
      moved): **stopped at the sensor after 1440.6mm against 1448.4mm
      calibrated (-7.8mm), encoder 1453.9mm, no homing timeout.** The sync
      feed to the toolhead sensor then took 50mm instead of 40, because the
      polled approach used to overshoot the sensor by up to one 10mm step.
      The same load started from 'unknown' and parked first, as intended.
      Then T0-T2 back to back (2026-10-11): **T1 -2.7mm, T2 -8.3mm, and T0
      stopped 333mm EARLY** -- 1174.0mm against 1506.9mm calibrated, encoder
      1189.6. T0's own 10-09 loads blasted to ~1505mm on the encoder, so the
      calibration is right and the filament was 333mm further in than its
      park said. T0 had not moved since an auto-park on 10-09 -- the old park,
      before ba6400c, that could report "parked" with the filament still on
      the encoder. The polled blast would have driven those 333mm into T0's
      gears at 160mm/s, as it did to T1 on 10-10; this one stopped at the
      sensor and said why. No homing timeouts on any of the three boards.
      *Done when:* a
      load stops at the sensor and its fed length sits within a few mm of
      calibrated, on more than one path -- and the multi-board stop has not
      raised "Communication timeout during homing".

      Seen in passing 2026-10-11 (ba6400c, the park that escalates): T2's
      filament went back in further than a fresh insert, the auto-park said
      "still at the encoder after 50mm of retract -- further in than a fresh
      insert", retracted it back past the encoder and parked it 5.0mm before.

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
