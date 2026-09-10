# TODO

Open work, and what proves each item done.

**If a check already catches it, the check is the tracker — not this file.**
`scripts/check_drift.py` goes green on its own when those items are fixed, so
they are listed here for visibility only and need no edit when they close.
Anything nothing checks needs a line here, and needs removing by hand.

---

## Blocked on hardware

The wheels and the servo are being replaced. Nothing below can be measured
until the machine is back together.

- [ ] **Re-run the calibration guide end to end** on the rebuilt hardware.
      Open with `SA_GUIDE OPEN=1`; the guide is the sequence.
      *Done when:* all eleven steps pass in order on one machine, both UIs
      following, and `SA_LOAD TOOL=0` completes.
- [ ] **Six new `mm_per_pulse` and six new `bowden_length_N`.** Every stored
      value predates the wheel reprint and the servo swap, so all twelve are
      wrong by an unknown amount.
      *Done when:* `variables.cfg` carries twelve values measured after the
      rebuild.
- [ ] **Confirm the two known faults are gone.** Wheel-to-housing rub shedding
      dust into the sensor eye, and the MG90S weakening under repeated cycles.
      Both were real; the reprint and the SX108 address one each.
      *Done when:* the six per-path ceilings come back CLOSE TO EACH OTHER.
      Before the rebuild they were 140 / 80 / 40 / 140 / 40 / 120 mm/s. Six
      similar numbers is the pass — a surviving spread means something else is
      per-path. `encoder_max_speed` is their minimum and rises on its own; it
      is not stale and must not be "fixed" by hand.

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
