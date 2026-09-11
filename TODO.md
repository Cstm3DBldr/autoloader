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

- [ ] **Prove the sequence, not just the steps.** `SA_LOAD TOOL=0` — a real
      load through to the nozzle. The guide proves each step in isolation and
      nothing yet proves them in order.
      *Done when:* one full load completes and the path reads `loaded`.
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
