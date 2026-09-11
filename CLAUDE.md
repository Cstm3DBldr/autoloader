# Autoloader — Claude Code Project Instructions

## What This Project Is
A filament auto-load and auto-unload system for a Voron StealthChanger 3D printer
with 6 independent toolheads. Each toolhead has its own filament path; this system
automates loading when a roll runs out and swapping filament color between prints.

This is a NEW original project. It is NOT a port or fork of any existing project.

**Use case:** Multi-toolhead printer. Tool changes are handled by the toolchanger
(mechanical head swap). This system only acts when:
- A roll runs out → auto-load new filament to that toolhead
- Manual swap between prints → unload old, load new filament

**NOT an MMU:** Filament never leaves the path during a tool change. No gate
selector that moves to filament. No color changes mid-print on a single toolhead.

---

## Printer Access
- SSH:         pi@192.168.1.214
- Config path: ~/printer_data/config/autoloader/
- Repo path:   ~/autoloader/

## GitHub
- Repo: https://github.com/Cstm3DBldr/autoloader.git
- Branch: main
- Commit and push after any change that works on the printer

## One-Time Manual Edits Made Outside the Repo

These printer-side edits live OUTSIDE `~/autoloader/` and are not
synced by `post_update.sh`. They're documented here so a fresh install
on a new printer (or a `git stash` / restore of `~/printer_data/config/`)
knows what manual hooks to reapply.

- **`~/printer_data/config/KlipperScreen.conf`** — carries the live
  autoloader menu entries:
  ```
  [menu __main autoloader]
  name: Autoloader
  panel: sa_home
  icon: autoloader

  [menu __print autoloader]
  name: Autoloader
  panel: sa_home
  icon: autoloader
  ```
  Note `KlipperScreen/sa_klipperscreen.conf` in this repo declares the same
  menus and is copied to `~/printer_data/config/` by `post_update.sh`, but
  **nothing includes it** — KlipperScreen.conf does not `[include]` it, so it
  is inert on this printer. The repo copy is kept in step for a fresh install;
  the file above is what actually renders. Change both, or the change appears
  to do nothing.

- **`~/printer_data/config/Toolchanger/Tool-Heads/T5.cfg`** — line 71's
  commented `detection_pin` read `et4:PB6`, T4's pin. Corrected to `et5:PB6`
  (2026-09-03). Still commented, so no functional change — but if tool
  detection is ever enabled, the uncorrected line would have pointed T5 at
  T4's board. Pre-edit file preserved as `T5.cfg.bak.<epoch>`.

  Note the pins cannot simply be uncommented: `detection_pin` and
  `[tool_probe TN] pin:` are both `etN:PB6`, and Tap already owns it, so
  enabling detection needs a different free input plus a physical dock
  switch. It is not a second Z endstop — `detection_pin` registers a button —
  but it is a pin conflict. The software route avoids the question entirely:
  `tool_probe_endstop` already identifies the mounted tool as the one probe
  not triggered.

- **`~/printer_data/config/Toolchanger/toolchanger.cfg`** — at the end
  of `[toolchanger] after_change_gcode:`, added:
  ```
  _SA_LEDS_INIT_ALL ACTIVE={tool.tool_number}
  ```
  This refreshes every toolhead's status LEDs after each toolchange.
  The macro is defined in the LED config, which is **opt-in** — only add
  this hook on a printer that enabled LEDs, or every toolchange errors on
  an unknown command. The pre-edit file
  is preserved on the printer as `toolchanger.cfg.bak.<epoch>`.

## Branching and what counts as a fix

    main         what end users install. Update Manager points here
                 (install.sh writes primary_branch: main). Fast-forwarded
                 from dev at the end of a confirmed day.
    dev          one commit per CONFIRMED fix. Forked from main, so main is
                 its ancestor and a merge is a fast-forward, not a graft.
    printer-dev  what this printer runs. Messy by design: commit whatever it
                 takes to get code onto the machine and test it.
    old-dev      the 505-commit build history from before 2026-09-07.

This printer follows **printer-dev** (`primary_branch: printer-dev` in its
moonraker.conf, a manual edit). End users follow **main**.

**The cycle, per fix:**

1. Work on `printer-dev`. Commit and push as often as it takes — Update
   Manager pulls it, so pushing IS the deploy. Nobody reads this log.
2. Verify on the machine. Measured, not assumed.
3. Transpose the confirmed change onto `dev` as ONE commit, with a message
   saying what was measured.
4. Reset `printer-dev` back onto `dev` so the two cannot drift:
   `git push -f origin origin/dev:refs/heads/printer-dev`, then on the
   printer `git fetch && git reset --hard origin/printer-dev`.

Step 4 is the one that gets skipped. Without it `printer-dev` accumulates
history that `dev` never sees, and the next transposed diff is taken against
the wrong baseline.

**A commit is a CONFIRMED fix, not an attempted one.** Deploy it, verify it on
the machine, and only then commit. The message says what was measured, not what
was intended.

This is not a style preference. On 2026-09-07 three separate "fixes" were
committed, deployed and reported before anyone checked:

- reversal slack in the encoder measurement — a take-up move was added and
  changed the reading by nothing at all
- a two-pulse quantisation theory — the arithmetic fitted both observations
  exactly and was still wrong; a longer pass showed the error tracked distance
- every KlipperScreen change for two days — `sudo systemctl restart` over ssh
  fails without a terminal, so the panels were copied and never loaded

Each one is a commit claiming a fix that was not one, and the last hid three
other bugs behind it.

`printer-dev` is what makes that rule practical: an untested change still needs
to reach the printer, and a commit is the delivery mechanism. Putting those
commits on a branch nobody reads means `dev` never carries an unconfirmed one.

**End of day:** `dev` fast-forwards into `main`. Every commit on it is
already a confirmed fix, so nothing needs squashing.

## One source of truth, and a check that proves it

Every place that restates something becomes a place that goes stale. This has
bitten the project four times, months apart, each found by hand by someone
counting:

- the calibration step list lived in `_GUIDE`, a KlipperScreen wizard, a
  Mainsail wizard and this file. When the chain grew to eleven steps both
  wizards went on showing nine, one of them clamping the extras onto the last
  page it knew.
- the macros panel kept a fifth copy, listing five of the eleven.
- this file's Calibration Sequence never mentioned `SA_CALIBRATE_ENCODER_SPEED`
  at all, and carried the encoder steps in an order the code had already
  changed.
- the command reference was missing four registered commands.

**The rule, in order of preference:**

1. **Derive, do not restate.** One place owns the fact and everything else asks
   it at runtime. `_GUIDE` is the model: the backend resolves the pages into
   the status object and every UI renders what it is given. Adding a step is
   one edit, and no UI can disagree because no UI describes it.
2. **When it cannot be derived, make it checkable.** Two copies a script can
   compare are survivable. Two copies only a human can compare are not. Add
   the comparison to `scripts/check_drift.py`.
3. **Only then write it twice** — and say in each place that the other exists,
   the way the KlipperScreen menu note does.

**Run `python3 scripts/check_drift.py` before any commit touching this file,
the guide, the command list or parameters.cfg.** No printer, no arguments,
exits non-zero on drift. It proves:

| Check | Compares |
|---|---|
| command reference | this file's GCode table against every `register_command` |
| guide step numbering | `_GUIDE`, `_STEP_TOTAL`, `_STEP_NAMES` and both lookup tables |
| parameters | every setting in `parameters.cfg` against what the code reads |

It also catches the prefix-ordering trap: `SA_CALIBRATE_ENCODER` listed before
`SA_CALIBRATE_ENCODER_SPEED` makes the longer one unreachable, and the symptom
is a step number reported wrong with nothing logged.

**Add a duplication, add its check.** Where that is not possible, say why here.
The known unchecked pairs:

- `autoloader/*.cfg` vs `installer/templates/*.cfg` — the templates carry
  `{{VAR}}` and `{% for path %}`, so they cannot be compared line by line:
  hardware.cfg has 31 sections against the template's 7. Change both.
- `~/printer_data/config/KlipperScreen.conf` vs the repo's
  `sa_klipperscreen.conf` — nothing includes the repo copy, so it is inert on
  this printer and kept only for a fresh install. Change both, or the change
  appears to do nothing.
- `scripts/verify.sh` covers the other direction, printer against repo, and
  needs the machine. `check_drift.py` is the half that does not.

---

## Operational Permissions (set by user)
Claude has full autonomous control of this printer and repository. No need to ask
before deploying or pushing — just do it and report the result.

- **Deploy after every code change** — SCP files, restart Klipper, verify it loads.
- **Commit and push to main** after every successful deploy.
- **This is a spare/test printer** — mechanical risk is acceptable for calibration and testing.
- **Update README.md** whenever commands, config parameters, or calibration procedures change.
- **Update CLAUDE.md** whenever the user adds new rules, preferences, or project context.
- **No confirmation prompts needed** for SCP, SSH restart, git commit, or git push.
- **Printer is authoritative for ALL deployed files. Always pull-first
  before modifying.** Before starting any task that touches files which
  are deployed to the printer (cfg, KlipperScreen panels, html), pull the
  printer's live copy and reconcile against the repo:
    - `~/printer_data/config/autoloader/*.cfg`, `*.html`
    - `~/printer_data/config/sa_klipperscreen.conf`
    - `~/KlipperScreen/panels/sa_*.py`, `~/KlipperScreen/sa_*.py`
    - `~/printer_data/config/autoloader/filament_profiles/`
  The printer's content wins on any divergence; pull it into the repo as
  the new default, commit, push, then make the requested change. This
  protects against losing user-tuned values, runtime calibrations, or
  edits made directly via the Mainsail config editor / KlipperScreen.

  Symlinked files (Klipper extras, Moonraker component) don't need this
  step — they read directly from the repo.

  `scripts/verify.sh` runs the parameters.cfg drift check on every run
  and exits non-zero if the printer has tuned values not in the repo.

---

## UI Preferences (locked — restore if disturbed)

### KlipperScreen Load/Unload path buttons (`KlipperScreen/panels/sa_load_unload.py`)

User-confirmed canonical look (commit `76b4f35`). If a future edit changes
any of this, restore it to match unless the user explicitly asks for a
different layout.

- **Layout:** each path button is a `Gtk.Grid` with `column_homogeneous=True`
  and 3 columns: `T#` (left), color swatch (middle), material (right). Each
  column is exactly 1/3 of the button width.
- **Swatch placement:** swatch widget has `halign=CENTER` inside its column,
  so it lands at the absolute geometric center of the button regardless of
  the T# or material label widths. Do NOT use a `Gtk.Box` + `pack_start`
  chain here — that lets label widths shift the swatch off-center.
- **Swatch size:** `sw_size = max(36, min(48, btn_h - 24))` — gives 36–48 px
  depending on button height. Don't shrink below 36 (too small to read at
  arm's length) and don't grow above 48 (overwhelms the row).
- **Button height:** `_path_btn_h()` returns `max(50, min(72, avail // rows))`
  with `avail = self._screen.height - 60 - 74 - 50`. The 72 cap is what
  prevents the 2×3 grid from pushing the action bar offscreen on a 480px
  display — don't raise it without testing on a real KS device.
- **Label alignment:** both labels `halign=CENTER` inside their columns.
  Material has `set_ellipsize(3)` and `set_max_width_chars(8)` so a long
  material name can't push past the column boundary.
- **Color-picker chips** (in the wizard color step): `60×70` button with
  `40 px` swatch (was `72×82` / `52 px` — too crowded on small screens).

### KlipperScreen Autoloader home menu (`KlipperScreen/panels/sa_home.py`)

User-confirmed canonical look (commit `b991e31`, "Concept B"). If a future
edit changes any of this, restore it to match unless the user explicitly
asks for a different layout.

- **Two-section layout:** top "hero row" (`vexpand=True` — absorbs leftover
  height, ends up ~65% of the panel on a 480 px display); bottom "utility
  row" with a fixed `set_size_request(-1, 110)` height. Outer Box is
  `spacing=8, margin=8`, `homogeneous=False`.
- **Hero tiles (top):** STATUS (`color1`, `spoolman` icon) on the left,
  LOAD/UNLOAD (`color3`, `load` icon) on the right. Each is a custom
  `Gtk.Button` containing a vertical Box (icon → label → preview line),
  built via `_build_hero_btn()`. Do NOT replace these with the standard
  `self._gtk.Button(icon, label, color)` — that one only supports
  icon + label and won't fit the preview.
- **Hero icon size:** `int(self._gtk.img_scale * self._gtk.button_image_scale * 2.0)`
  — 2× the standard KS button image scale. Don't reduce below 1.5× or the
  hero treatment is lost.
- **Hero label:** `<span font_size="large" weight="bold">…</span>`.
- **Hero preview line:** `<span font_size="small" foreground="#BDBDBD">…</span>`,
  `set_max_width_chars(32)`, `set_ellipsize(3)`. Content driven by
  `_build_status_text()` and `_build_load_text()`:
    - STATUS: `"N/M loaded · T<active> <material>"` where `<active>` is
      the currently-mounted extruder index (parsed from
      `toolhead.extruder` via `_extruder_to_tool_idx()` — "extruder" → 0,
      "extruderN" → N). Falls back to `"N/M loaded · T<active> active"`
      if the active path has no material set, `"N / M paths loaded"`
      if no extruder is detectable, or `"Autoloader idle"` if
      `total == 0`. Loaded count uses `_effective_state()` (sensors +
      stored state), NOT raw `path_states[i] == "loaded"` — sa_main
      uses the same logic so both panels agree on the count.
    - LOAD/UNLOAD: `"Selector at TN"` (with `" · drive engaged"` when
      `servo_engaged`), or `"Selector unhomed"` when `current_path < 0`.
  Always escape dynamic text via `xml.sax.saxutils.escape` before passing
  to `set_markup` — material names can contain `&`/`<`.
- **Utility row (bottom):** four standard KS buttons in
  `MACROS / CALIBRATION / SETTINGS / CONFIG` order, each
  `self._gtk.Button(icon, label, color)`, all `pack_start(True, True, 0)`
  for equal-width slots. Row spacing = 8 px. Don't change the order — it's
  alphabetical-ish AND matches the user's "frequency of use, low to high"
  reading.
- **No decorative colored bars** under the labels. Visual hierarchy comes
  from tile size + the standard KS color classes only.
- **Subscription:** `activate()` calls `_sasub.build_subscription(...)` and
  `_sasub.install_global_popup_watcher(...)` — same pattern as every other
  autoloader panel. `process_update` updates previews via `GLib.idle_add`.
  `activate()` also does a one-shot `apiclient.send_request("printer/objects/query?autoloader")`
  so the previews show real data instantly instead of `"…"`.

### KlipperScreen status panel (`KlipperScreen/panels/sa_main.py`)

- **A four-item status row sits above the table**, packed on `self.content`
  outside the scroller so it cannot scroll away: SELECTOR / DRIVE GEAR /
  ACTIVE TOOL / CALIBRATION. Same four readings, same order and same words as
  the Mainsail panel's header, so moving between the two screens needs no
  re-learning. Every empty case is decided in `_apply_status_row` rather than
  left to render stale: an unhomed selector has no position and a machine with
  no tool mounted has no temperature.
- The table below it is deliberately **richer** than Mainsail's — it also
  carries TEMP, the EN/EX/TH sensor dots and ENCODER. Do not trim it to match;
  the web panel is the one that is missing those.

### KlipperScreen Macros menu (`KlipperScreen/panels/sa_macros.py`)

User-confirmed canonical look. If a future edit changes any of this,
restore it to match unless the user explicitly asks for a different
layout. The first-render-bug history that produced these constraints
is preserved in commits `0079f41` → `d48e0f2`.

- **Three sections, top→bottom:** DAILY (4 buttons in 1 row) →
  DIAGNOSTICS (3 buttons in 1 row) → CALIBRATION (5 buttons across
  2 rows: 3 globals + 2 per-tool). Order is "frequency of use,
  highest first." Don't reorder. An earlier "QUICK RE-CAL" 4th
  section was removed because its 3 buttons (Re-cal Sel / Drive /
  Enc) were exact duplicates of the first 3 CALIBRATION buttons —
  same gcodes, just different labels. Don't add it back.
- **CALIBRATION is ONE button: `OPEN CALIBRATION GUIDE`**, which shows the
  `sa_calibration_guide` panel. It used to list five of the eleven steps, which
  made this the fourth place the calibration order was written down and the
  fourth to go stale. The guide holds every step with its live value and what
  to check when it misbehaves — a shortcut listing a subset is worse than a
  door to the whole thing, because it looks complete. Do not put step buttons
  back here.
- **DIAGNOSTICS buzzes with `SA_BUZZ_CHECK MOTOR=…`**, not the bare
  `SA_BUZZ_*`: it asks which way the motor went and flips it in software on a
  wrong answer, then buzzes again so the fix is checked. The bare commands
  remain for a console poke.
- **Button heights:** DAILY=80, DIAGNOSTICS=66, CALIBRATION one expanding row.
  DAILY keeps the larger floor so it stays the visually dominant section.
- **Outer Box:** `Gtk.Box(VERTICAL, spacing=6)`, margins
  `top=10, start=8, end=8, bottom=14`. The trailing **vexpand=True
  spacer** Box at the end of `_build_main_page` is REQUIRED — without
  at least one expanding child, the page's natural height = sum of
  fixed children, and base_panel's spanning vexpand action_bar grabs
  more vertical budget than it should on first allocation. Don't
  remove the spacer.
- **Section header:** `Gtk.Label` with markup
  `<span font="11" foreground="#9E9E9E">── %s ──</span>`. Pinned to
  fixed pt size and CSS class `.sa-section-header` (margin/padding/
  min-height all 0). NEVER use em-based `font_size="x-small"` or
  `letter_spacing` — both depend on font-metric measurement that's
  unstable across the first realize pass and produce ~4 px extra
  per header on first attach (×4 headers = the 16 px content
  overflow that stretches base_panel's left rail and clips the
  power icon off-screen).
- **CSS provider** is installed once per session by
  `_install_action_bar_css()` (module-level guard). Pins
  `.action_bar > button` margin/padding to small fixed pixel values
  AND sets `.sa-section-header` to the same. Both rules run from
  one provider at `STYLE_PROVIDER_PRIORITY_USER + 100`.
- **Page switching:** `Gtk.Notebook` with `set_show_tabs(False)` +
  `set_show_border(False)`, two pages: `main` and `tool`. Notebook
  was chosen over `Gtk.Stack` because Stack's `vhomogeneous=False`
  flag doesn't reliably take effect on the first allocation pass
  after KlipperScreen restart. Don't switch back to Stack.
- **Self.content sizing:** `vexpand=False` and
  `set_size_request(-1, _gtk.content_height)` are both pinned in
  `__init__` to override screen_panel.py's default `vexpand=True`,
  so the content widget claims exactly its slice of the grid row
  (no fight with action_bar's vexpand for leftover space).
- **Section row labels:** prefer single-line. Embedded `\n` to stack
  words is OK ONLY when the natural single-line label wouldn't fit
  the column width (the CALIBRATION row's 4 buttons are the example);
  in that case set `btn_h` larger to accommodate, and use `\n` on
  EVERY label in the row for visual consistency rather than letting
  GTK's auto-wrap pick which buttons stack.
- **Section row buttons:** `set_homogeneous(True)` for equal width;
  Pango wrap settings (`set_line_wrap(WORD_CHAR)`, `set_lines(2)`)
  let "HOME SELECTOR" stack to two lines instead of ellipsizing.
  `set_ellipsize(END)` + `set_max_width_chars(12)` is the safety
  net for any longer label that's still added in the future.
- **Subscription:** `activate()` calls
  `_sasub.build_subscription(...)` and
  `_sasub.install_global_popup_watcher(...)` — same pattern as
  every other autoloader panel.

---

## Project File Structure

| File | Purpose |
|---|---|
| `autoloader/autoloader.cfg` | Aggregator. printer.cfg pulls only this file: `[include autoloader/autoloader.cfg]`. Pulls in the others below |
| `autoloader/pin_aliases.cfg` | ONLY physical hardware pins and aliases. One [board_pins] per MCU. No polarity, no hardware config |
| `autoloader/hardware.cfg` | ONLY hardware sections: [mcu], [tmc5160], [manual_stepper], [servo], [sa_encoder], [filament_switch_sensor], [gcode_button selector_stall] |
| `autoloader/parameters.cfg` | The single `[autoloader]` section — all user-tunable values (servo angles, speeds, tip-form, park, selector cal, bowden lengths, sensor/encoder/extruder/stepper references). Klipper requires the section in one file |
| `autoloader/macros.cfg` | Thin gcode wrappers around Python backend commands |
| `autoloader/examples/leds_core.cfg` + `leds_status.cfg` | **OPT-IN, not included by default. Split in two on purpose:** `leds_core.cfg` is entirely `_sa_`/`_SA_` namespaced and cannot collide; `leds_status.cfg` holds the ten `STATUS_*` macros that share names with the stock Voron file. The installer copies core always and status only for the Full option, and refuses Full outright when it detects `stealthburner_leds.cfg`. Splitting rather than documenting a block to delete, because an instruction to delete is an instruction people skip and skipping it here means the printer will not boot. Worked example for toolhead Voron logo + nozzle LED status. The user copies it to `~/printer_data/config/autoloader/leds/` and uncomments `#[include leds/*.cfg]` in `autoloader.cfg`. See `docs/LEDS.md`. It is off by default because LED hardware is the least portable part of a build: chain names and wiring order differ per machine, and its ten `STATUS_*` macros collide with the stock Voron `stealthburner_leds.cfg` — Klipper uppercases macro aliases, so lowercase `status_ready` and `STATUS_READY` register the same command and the printer refuses to boot. State-driven (PARKED / UNLOADED / ACTIVE / LOADING / ERROR), reads filament colour from `printer["autoloader"].path_color_hexes`. **Locked filament-colour rendering pipeline in `_sa_set_logo_filament` (2026-05-06):** WS2812B/SK6812 strip — the green LED is ~1.5-2x brighter than red/blue, and human vision is roughly gamma-2.2. Pipeline: (1) parse hex → r/g/b raw 0–1; (2) if `max_ch == 0` stay off (no gamma); (3) if `max_ch < 0.15` rescale brightest channel to 0.0075 with NO gamma — at this brightness we're at the LED's quantization noise floor, gamma would crush it to zero; (4) else apply `g × 0.85` when green is not dominant, then sRGB gamma 2.2 (`channel ** 2.2`) on all three channels. The 0.85 figure was tuned with gamma in the loop — the pre-gamma 0.55 used in v5 was over-attenuating once gamma 2.2 was added, producing orange-cast browns. The test macros `_SA_LED_TEST_CASELIGHT_MAX`, `_SA_LED_TEST_CASELIGHT_BROWNS`, and `_SA_LED_TEST_CASELIGHT_GRAYSCALE` are the verification tools — keep their hardcoded values in sync if the pipeline changes. The v5 17-hue reference palette in the file header is anchor data, NOT live correction values. |
| `installer/Kconfig` + `installer/boards/` | menuconfig question set and per-board pin maps. Adding a board is one file plus one `source` line |
| `installer/detect.py` | Reads the printer and pre-fills the menu (toolhead count, extruder names, CAN UUID, LED chain family, `STATUS_*` collisions). `--check` is the hard guard that refuses an unbootable combination after the menu |
| `installer/generate.py` | `.config` + templates → `pin_aliases.cfg`, `hardware.cfg`, `parameters.cfg`. Refresh mode puts existing values back and reports dropped ones |
| `installer/templates/` | The three generated cfgs, with `{{VAR}}` / `{% for path %}` / `{% if %}` |
| `docs/INSTALL.md` | The user-facing install guide — plain language, for someone who has never seen the project. Includes the prompt flow and what is safe from updates |
| `docs/RECOVERY.md` | **Design note, nothing built.** How a path with the entry sensor clear but filament still in the head should be recovered: the new roll is the only thing that can push the remnant out, since the extruder can only move what its gears grip. Records the settled decisions — heat to the higher of the two materials, confirm the stashed profile first, never automatic — and the failure modes the encoder cannot see |
| `docs/RUNOUT_MIDPRINT.md` | **Design note, nothing built.** What should happen when a roll runs out *during* a print: flag the path `low` and keep its profile rather than wiping it empty, spend the tail on a distance budget, pause with a reserve, then **purge until the extruder sensor clears** — which pins the tail at a known point so the reload purge is a constant instead of accumulated tracking error. Records the three things that decide whether it works: `_is_printing()` reads False while paused, so the existing wipe branch would eat the profile mid-pause; the budget reserves an unmodelled entry→gate distance on top of the intended 50mm; and `sensor_to_gear` is the margin that keeps the tail in the gears and is not a parameter |
| `docs/LEDS.md` | How to turn LEDs on, what to change for your hardware, and the `STATUS_*` collision |
| `klipper/extras/autoloader.py` | Main controller — config parsing, GCode registration, status object |
| `klipper/extras/sa_motion.py` | Motion primitives (servo, selector, drive, idle timeouts) |
| `klipper/extras/sa_sequences.py` | Load and unload sequences |
| `klipper/extras/sa_calibration.py` | All calibration routines (drive, encoder, selector, bowden), **and `_GUIDE` — the one definition of the calibration guide.** Title, live status line, hint, buttons or a per-path grid, what to expect and what to check, per step. `guide_pages()` resolves it against the live status and it ships in the status object; every UI renders what it is given. There used to be three copies — this file's chain, a nine-page wizard in KlipperScreen and a seven-page one in Mainsail — and when the chain grew to eleven steps both wizards went on showing nine, one of them clamping the extras onto the last page it knew. Adding a step is one edit here |
| `klipper/extras/sa_encoder.py` | Encoder driver — pulse counting via Klipper buttons module |
| `klipper/extras/sa_led_animator.py` | Background LED animator for the toolhead LEDs, ~500 lines. One reactor timer drives two things: a slow white breathing pulse on the logo LED of each unloaded toolhead while idle, and a temp-aware nozzle colour on the active tool when not printing — red-orange while the hotend is still warm, otherwise the same load-state colours as the docked tools. Pauses cleanly during a print or any autoloader operation. Symlinked like the other extras. **Only does anything with the opt-in LED configs**, so a printer without them loads it and it stays quiet |
| `moonraker/sa_moonraker.py` | Moonraker component — REST endpoints + status broadcast |
| `web/mainsail-plugin/` | Autoloader panel as a runtime-loaded Mainsail plugin — one self-contained `.mjs`, no Mainsail fork required. Needs Mainsail with custom-panel support. See its README |
| `web/mainsail/AutoloaderPanel.vue` | Mainsail UI panel (in-tree fork variant, superseded by `web/mainsail-plugin/`) |
| `web/fluidd/AutoloaderPanel.vue` | Fluidd UI panel |
| `KlipperScreen/panels/sa_*.py` | KlipperScreen touchscreen panels |
| `KlipperScreen/addons/sa_autoloader.py` | Runs at KlipperScreen startup and starts watching, so a touchscreen that has opened no autoloader panel still follows a guide opened in Mainsail |
| `scripts/check_drift.py` | Fails when two places that describe the same thing disagree: the command reference against `register_command`, the guide's step numbering against itself, and `parameters.cfg` against what the code reads. No printer, no arguments. Run it before committing changes to CLAUDE.md, the guide, the command list or parameters.cfg — see **One source of truth** above |
| `scripts/patch_klipperscreen.sh` | Adds the `addons/` hook to KlipperScreen's `screen.py`. Generic and does not mention the autoloader — it is what we would propose upstream. Guarded: refuses unless the exact anchor matches, idempotent, backs up, byte-compiles and restores on failure, `--revert` undoes it |
| `KlipperScreen/sa_filament_db.py` | Filament profile DB loader (shared with Moonraker) |
| `filaments/brands/*.cfg` | Per-brand filament profile files |
| `References/hardware_pinouts/` | Board pinout images — local + GitHub only, NOT on printer |
| `TODO.md` | Open work, and what proves each item done. Items a check already catches are listed for visibility only — `check_drift.py` goes green on its own and the file needs no edit. Anything nothing checks needs removing by hand |
| `CLAUDE.md` | This file |

On the printer, Python extras and the Moonraker component are symlinked from the repo:
- `~/klipper/klippy/extras/autoloader.py` → `~/autoloader/klipper/extras/autoloader.py`
- `~/klipper/klippy/extras/sa_motion.py` → `~/autoloader/klipper/extras/sa_motion.py`
- `~/klipper/klippy/extras/sa_sequences.py` → `~/autoloader/klipper/extras/sa_sequences.py`
- `~/klipper/klippy/extras/sa_calibration.py` → `~/autoloader/klipper/extras/sa_calibration.py`
- `~/klipper/klippy/extras/sa_encoder.py` → `~/autoloader/klipper/extras/sa_encoder.py`
- `~/klipper/klippy/extras/sa_led_animator.py` → `~/autoloader/klipper/extras/sa_led_animator.py`
- `~/moonraker/moonraker/components/sa_moonraker.py` → `~/autoloader/moonraker/sa_moonraker.py`

KlipperScreen panels are NOT symlinked — copy directly to `~/KlipperScreen/panels/` and `~/KlipperScreen/`.

---

## Motion System Architecture

ERCF V2 mechanical concept, adapted for fixed multi-toolhead use:

One thing moves; everything else is per path and fixed. The selector carries
ONE drive gear to whichever path needs driving. The encoders do NOT ride with
it -- each path owns its own, permanently on its own filament, and each sits
**downstream of the gear**: `SA_PARK` drives forward by
`encoder_to_gear_distance` to reach the encoder, then retracts until it goes
quiet (`sa_sequences.py:302-311`).

```
 [Roll 0]         [Roll 1]         ...      [Roll N]
     |                |                         |
Entry Sensor 0   Entry Sensor 1            Entry Sensor N
     |                |                         |
     +----------------+-------------------------+
                      |
        Drive Gear on the selector carriage       -- the ONLY moving part;
        (Selector Motor positions it;                serves one path at a time
         Engage Servo grips or releases)
                      |
     +----------------+-------------------------+
     |                |                         |
 Encoder 0        Encoder 1                 Encoder N    -- fixed, one per path,
     |                |                         |           always counting
 PTFE Tube 0     PTFE Tube 1               PTFE Tube N
     |                |                         |
 Extruder Sensor N    (toolhead entry, before the gears)
     |
 Extruder Motor + gears
     |
 Toolhead Sensor N    (past the gears, before the nozzle)
     |
 Hotend + Nozzle
```

**Why it is built this way.** A shared encoder can only measure the path the
carriage is parked at. A locked one measures its path all the time, which is
what makes fast loads and unloads safe to run and what gives jam and break
detection *during a print*, when the drive is disengaged and the carriage is
somewhere else entirely.

**What its position buys.** Sitting after the gear, each encoder sees the tail
of its own roll pass by. That edge -- the encoder going quiet while the
extruder is still pulling -- is a *measured* mid-tube datum, and what remains
after it is `bowden_length_N` plus the toolhead's own fixed run. Paired with
the entry sensor it also separates the two cases that look identical from the
extruder's side: entry clear means the roll ended, entry still triggered means
a jam or a break. See `docs/RUNOUT_MIDPRINT.md`.

### Components
| Component | Klipper Object | Role |
|---|---|---|
| Selector motor | `manual_stepper sa_selector` (M2) | Positions drive carriage to active path |
| Drive motor | `manual_stepper sa_drive` (M1) | Moves filament through selected path |
| Engage servo | `servo sa_engage` | Engages (driven) or releases (neutral) drive gear |
| Path encoders | `sa_encoder 0..N` | **One per path, locked to that path and never shared.** Six independent channels, each with its own pin and its own calibrated `mm_per_pulse`. They are the reason loads and unloads can run fast, and they give jam and break detection during a print -- the counting callback is registered once at init (`sa_encoder.py:46`) and is live whatever the machine is doing, including with the drive disengaged. **A single-channel optical encoder cannot sense direction:** `_pulse_callback` adds `mm_per_pulse * _direction` and `set_direction()` only *tells* it which way to count, so the pulse COUNT is always right and the accumulated SIGN is only right if something set it. See `docs/RUNOUT_MIDPRINT.md` for what that allows and what it forbids |
| Entry sensors | `filament_switch_sensor entry_sensor_N` | Per-path; fixed position at roll end |

### Engage vs Neutral
- **Engaged** (servo at `servo_engaged_angle`) — drive gear grips filament; drive motor moves it
- **Neutral** (servo at `servo_disengaged_angle`) — drive gear releases; filament flows freely
  ("neutral" like a car transmission — no force transmitted)

---

## MCU Layout

| MCU name | Board | Role | UUID |
|---|---|---|---|
| `mcu` | BTT Manta M8P | Main printer (in printer.cfg — do not redefine) | — |
| `autoloader` | BTT MMB CAN V2.0 | All 6 paths on one board | 329ce333239a |

---

## Pin Assignments — BTT MMB CAN V2.0 (`autoloader`)

| Alias | Physical Pin | Role |
|---|---|---|
| SA_DRIVE_STEP/DIR/EN | M3: PC15/PC11/PC10 | Drive motor step/dir/enable |
| SA_DRIVE_CS | PB3 | Drive motor TMC5160 SPI chip-select |
| SA_SELECTOR_STEP/DIR/EN | M1: PD4/PD3/PD5 | Selector motor step/dir/enable |
| SA_SELECTOR_CS | PB5 | Selector motor TMC5160 SPI chip-select |
| SA_SELECTOR_STOP | PA15 (STOP1) | Selector physical endstop (switch) |
| SA_SERVO | PA1 | Engage servo PWM signal |
| SA_ENCODER_0..5 | PC7,PA9,PB12,PB10,PB1,PC5 | Per-path encoders (2x7 high pins) |
| SA_ENTRY_0..5 | PC6,PA8,PB11,PB2,PB0,PC4 | Entry sensors (2x7 low pins) |
| SA_SELECTOR_DIAG | PB9 | TMC5160 stallguard DIAG (M1 selector) — required for SA_CALIBRATE_SELECTOR via `[gcode_button selector_stall]` |
| SA_DRIVE_DIAG | PB7 | TMC5160 stallguard DIAG (M3 drive) — reserved |

**TMC5160 SPI bus** (shared M1+M2): software SPI — MISO=PB14, MOSI=PB15, SCK=PB13
`sense_resistor: 0.075` — hardware SPI (spi_bus: spi1/spi2) fails on this MCU; software SPI required.

Entry sensors use `^!` (pull-up + invert) because the sensors read HIGH when empty on this hardware.

**BTT EBB36 toolhead sensor pins (per toolhead MCU `etN`):**
| Pin | Sensor | Role |
|---|---|---|
| `^etN:PB8` | `toolhead_sensor_N` | Filament past extruder gears, entering hotend (final load confirmation) |
| `^etN:PB5` | `extruder_sensor_N` | Filament at toolhead entry, before extruder gears (Bowden calibration endpoint) |

---

## Klipper Config Rules — Strict

1. `[board_pins]` block name MUST exactly match the `[mcu name]`. Wrong name → "Unknown pin chip name" error.
2. Pin polarity (`^` pull-up, `!` invert) goes in hardware.cfg on the USE line — never in pin_aliases.cfg.
3. Last alias entry in a `[board_pins]` block has NO trailing comma.
4. Include order is fixed: pin_aliases.cfg → hardware.cfg → parameters.cfg → macros.cfg. (parameters.cfg references hardware sections so it must come after hardware.cfg.)
5. Never duplicate an `[mcu]` section — main `[mcu]` lives in printer.cfg only.
6. Step pins on secondary MCU: do NOT use `^` prefix — step pins are outputs. `^chip:pin` fails; `chip:pin` works.
7. Input pins (sensors, endstops): `^!autoloader:SA_ENTRY_0` works — `^` and `!` are stripped before chip name lookup.

---

## Python Backend — autoloader.py

Single `[autoloader]` config section, single class instance, controls everything.

### Config Parameters

| Parameter | Default | Description |
|---|---|---|
| `drive_stepper` | required | manual_stepper name for drive motor |
| `selector_stepper` | required | manual_stepper name for selector |
| `servo` | required | servo object name for engage/disengage |
| `encoder_N` | `sa_encoder N` | Per-path encoder section name |
| `num_paths` | 6 | Number of filament paths (1–32) |
| `entry_sensor_N` | none | filament_switch_sensor name for entry sensor on path N |
| `extruder_sensor_N` | none | filament_switch_sensor at extruder gear entry on path N (required for SA_CALIBRATE_BOWDEN, sensor-terminated load) |
| `toolhead_sensor_N` | none | filament_switch_sensor past gears, before nozzle on path N (final load confirmation) |
| `selector_position_N` | N×21mm | Selector position in mm from home for path N (set by SA_CALIBRATE_SELECTOR) |
| `extruder_N` | extruder / extruderN | Extruder name for heating during load |
| `bowden_length_N` | 800.0 | Per-path Bowden tube length (mm); set by SA_CALIBRATE_BOWDEN. Replaces global `tube_length`. |
| `servo_engaged_angle` | 160 | Servo angle when drive gear grips filament |
| `servo_disengaged_angle` | 10 | Servo angle when path is neutral |
| `tube_length` | 800 | Legacy fallback Bowden length used if `bowden_length_N` not set |
| `nozzle_distance` | 50 | Extruder gears → nozzle tip (mm) |
| `purge_length` | 30 | Extra extrusion after nozzle loaded (mm) |
| `load_temperature` | 200 | Min hotend temp before extruding (°C) |
| `load_park_z` | 50.0 | Z height held throughout load/unload + park (mm) |
| `engage_max_distance` | 60 | Max drive travel before expecting encoder motion (mm) |
| `slip_tolerance` | 15 | Warn if encoder vs stepper differ by > this % |
| `feed_speed` | 50 | Drive motor speed (mm/s) |
| `selector_speed` | 200 | Selector motor speed (mm/s) |
| `feed_step_size` | 10 | Drive motor step per loop iteration (mm) |
| `sensor_polling_delay` | 0.2 | Seconds between sensor checks in loops |
| `servo_move_delay` | 0.3 | Seconds to wait after servo command |
| `stepper_timeout` | 120 | Idle stepper auto-disable seconds; 0 disables auto-disable |
| `runout_timeout` | 10 | Seconds the entry sensor must read clear before a loaded/partial path is declared empty and its filament profile wiped |
| `material_select_timeout` | 60 | Seconds a profile may sit on an *empty* path with no filament before it is wiped; 0 disables. A path whose entry sensor sees filament keeps its profile until removal or a manual change |
| `cooling_pad_enabled` | True | Call `PARK_ON_COOLING_PAD` after load/unload |
| `clean_nozzle_enabled` | True | Call `SA_CLEAN_NOZZLE` before parking |
| `selector_max_travel` | 200.0 | Max sweep distance (mm) for SA_CALIBRATE_SELECTOR auto-cal |
| `selector_homing_speed` | 50.0 | Selector home approach speed (mm/s) |
| `selector_homing_backoff` | 5.0 | Back-off mm before slow re-approach in double-touch home |
| `selector_stall_current` | 0.4 | Reduced motor current (A) during stallguard sweep — bumping hard stop is harmless |
| `selector_stall_threshold` | 3 | TMC5160 SGT value for stallguard sensitivity (raise to reduce false triggers) |
| `selector_stall_speed` | 50.0 | Sweep speed (mm/s) during stallguard cal |

### GCode Commands (all registered by Python)

| Command | Description |
|---|---|
| `SA_HOME` | Home selector to physical endstop (double-touch), zero position |
| `SA_SELECT TOOL=N` | Move selector to path N (servo stays neutral) |
| `SA_ENGAGE` | Engage drive servo (grip filament) |
| `SA_DISENGAGE` | Disengage drive servo (neutral) |
| `SA_LOAD TOOL=N` | Full load sequence for path N |
| `SA_UNLOAD TOOL=N` | Full unload sequence for path N |
| `SA_STATUS` | Print state for all paths |
| `SA_BUZZ_DRIVE` | Test drive motor |
| `SA_BUZZ_SELECTOR` | Test selector motor |
| `SA_BUZZ_CHECK MOTOR=drive\|selector` | Buzz, then ask which way it went. Answering "wrong way" runs `SA_SET_DIRECTION`, saves it, and buzzes again so the fix is checked rather than taken on trust. This is what the guides call; the bare `SA_BUZZ_*` commands still exist for a quick manual poke |
| `SA_SET_DIRECTION MOTOR=drive\|selector [INVERT=0\|1]` | Flip (or set) that motor's direction and persist it to variables.cfg. Effective immediately — the sign is applied per move, not baked into the stepper config, so no restart and no rewiring |
| `SA_TEST_ENTRY_SENSORS [TOOL=N]` | Prove a path's entry sensor by hand: empty reads CLEAR, filament reads FILAMENT, and it clears again. Drives nothing. The empty check is **confirmed by the operator, not read** — every later stage needs the sensor to change, which a dead one cannot fake, but CLEAR looks identical whether the sensor works, is unplugged or is inverted. A pass is saved per path and shown in the guide's grid |
| `SA_TEST_TOOLHEAD_SENSORS [TOOL=N]` | Prove the extruder and toolhead sensors with the Bowden off and a scrap of filament. Checks all three things that matter: empty reads CLEAR, the extruder sensor sees it BEFORE the toolhead one, and both clear on the way out. The middle check is the point — crossed sensors make the Bowden blast stop on one the filament has not reached, at the gears |
| `SA_TEST_ENDSTOP [DURATION=30] [INTERVAL=0.3]` | Watch the selector endstop and report every change for DURATION seconds. Drives nothing — the operator moves the carriage by hand. Ends with ENDSTOP OK only after seeing BOTH states, so a switch stuck in either one fails rather than passing quietly |
| `SA_CALIBRATE_SERVO` | Find the engage angle. Ordered to protect the servo: arm off first, then move to the rest angle, then the arm goes back on at the end that is safe by definition (resting on the selector body, away from the drive gear), and only the far angle is searched. A `WRONG WAY` button mirrors both angles for a reversed servo — and takes the arm off again before crossing the travel |
| `SA_CALIBRATE_SELECTOR` | Auto sweep + measure total travel → calculate path positions |
| `SA_CALIBRATE_DRIVE` | Interactive drive motor rotation_distance calibration |
| `SA_CALIBRATE_ENCODER TOOL=N` | Measure mm_per_pulse for encoder N. Feeds at a fixed `feed_speed × 0.5`, which is below any aliasing threshold, so it needs nothing from the speed sweep — the sweep needs this |
| `SA_CALIBRATE_ENCODER_SPEED [TOOL=N]` | Find the fastest feed the encoder still counts reliably and save it as `encoder_max_speed`. Reports in mm/s, which is counts × mm_per_pulse, so run `SA_CALIBRATE_ENCODER` first. The saved global is the MINIMUM of the per-path ceilings — the fastest speed the slowest channel can hold — so a low value means a bad path, not a stale number |
| `SA_VERIFY_FEED [TOOL=N] [SPEED=mm/s] [DIST=mm]` | Drive one pass and check it against a ruler. The referee for a disputed encoder reading: the encoder and the stepper are the machine's only two references, and a motor losing steps looks exactly like an encoder missing counts |
| `SA_PARK TOOL=N` | Park filament at the drive encoder — load phases 0–2 only, no heat and no extruder |
| `SA_SET_CONFIG PARAM=name VALUE=val` | Stage a config value for `SAVE_CONFIG` |
| `SA_CALIBRATE_BOWDEN TOOL=N` | Measure Bowden tube length for path N |
| `SA_ENCODER_QUERY [TOOL=N] [RESET=1]` | Snapshot encoder distances |
| `SA_ENCODER_WATCH [TOOL=N] [DURATION=30] [INTERVAL=0.5]` | Live encoder delta stream |
| `SA_GUIDE [OPEN=0\|1] [STEP=n]` | Open, close or page the calibration guide on every UI at once. The printer holds `guide_open` / `guide_step` and both UIs mirror them, the same way prompts already worked — so opening the guide in Mainsail opens it on the touchscreen and either one can page it |
| `SA_RESPOND VALUE=x` | Advance active calibration to next phase |
| `SA_SET_STATE TOOL=N STATE=<state>` | Override path state (loaded/empty/partial/unknown) |
| `SA_FORM_TIP TOOL=N [MATERIAL=] [PUSH=] [SEVER=] [COOL_POS=] [COOL_LEN=] [COOL_MOVES=] [COOL_IN=] [COOL_OUT=] [TEMP=] [EASE=]` | Run only the tip-forming sequence, for tuning. Overrides are inline so no SAVE_CONFIG or restart is needed between attempts. `MATERIAL=` applies a material's row from the per-material tip table without that spool being loaded, so a material can be tuned with whatever filament is to hand. Leaves the tip past the gears — pull from the entry side and measure |
| `SA_RESTORE_PROFILE TOOL=N` | Put back the filament profile a wipe removed. Deliberately manual — a profile is a claim about what is physically in the path, and only the operator can confirm the same spool went back in. Refuses if the path already carries a profile |
| `SA_SET_MATERIAL TOOL=N MATERIAL=… BRAND=… LINE=… COLOR_NAME=… COLOR_HEX=… LOAD_TEMP=… UNLOAD_TEMP=… PURGE_SPEED=… PURGE_LENGTH=…` | Store filament profile for a path; consumed by load sequence and exposed via web/touchscreen UIs |

### Load Sequence

```
SA_LOAD TOOL=N
↓ Check entry_sensor_N — filament present?
↓ _select_path(N) → servo disengage → selector move → (update current_path)
↓ _servo_engage()
↓ encoder.set_direction(forward=True), encoder.reset_distance()
↓ Phase 1: feed +step until encoder moves (engage_max_distance limit)
↓ Phase 2: feed until encoder >= tube_length (slip check each step)
↓ _servo_disengage()
↓ TEMPERATURE_WAIT extruder_N >= load_temperature
↓ G1 E{nozzle_distance} F300 (extruder drives filament to nozzle)
↓ G1 E{purge_length} F300
↓ _CLEAN_NOZZLE → PARK_ON_COOLING_PAD
↓ path_states[N] = 'loaded'
```

### Unload Sequence

```
SA_UNLOAD TOOL=N
↓ G1 E-{nozzle_distance + purge_length} F300 (retract from nozzle)
↓ _select_path(N) → selector move
↓ _servo_engage()
↓ encoder.set_direction(forward=False), encoder.reset_distance()
↓ Drive -step until entry_sensor_N == False
↓ _servo_disengage()
↓ path_states[N] = 'empty'
```

---

## Deploy Workflow

**Routine deploys** (after committing + pushing to `origin/main`):

The printer auto-syncs through Moonraker Update Manager. Click "Update" on
the autoloader entry in Mainsail's Update Manager, OR run on the printer:

```bash
ssh pi@192.168.1.214 "cd ~/autoloader && git pull && ./post_update.sh && \
    sudo systemctl restart klipper && sudo systemctl restart moonraker && \
    sudo systemctl restart KlipperScreen"
```

`post_update.sh` is the canonical "sync everything that's not symlinked" step.
It runs automatically after every Update Manager pull and copies the .cfg/.html,
KlipperScreen panels, and `sa_klipperscreen.conf` into their live locations.

**Important — `FIRMWARE_RESTART` does NOT reload Python extras.** It only
re-parses `printer.cfg` (and any `[include]`'d cfgs) and resets the MCU.
The running klippy process keeps the in-memory copy of every Python module
it imported at startup. So a change to `klipper/extras/*.py` only takes
effect after an actual service restart:

- `sudo systemctl restart klipper` (needs sudo password), OR
- `bash ~/autoloader/scripts/klipper_service_restart.sh` — uses
  Moonraker's `/machine/services/restart` endpoint, which is wired
  to passwordless `sudo systemctl restart klipper` via PolicyKit on
  this build. **Use this for every change to `klipper/extras/*.py`
  or `moonraker/sa_moonraker.py`.**

For .cfg-only changes, `FIRMWARE_RESTART` is fine and faster.

**First-time install** on a new printer:

```bash
[ -d ~/autoloader ] || git clone https://github.com/Cstm3DBldr/autoloader.git ~/autoloader; ~/autoloader/install.sh
```

`install.sh` creates the 7 symlinks (6 Klipper extras + Moonraker component),
runs `post_update.sh` for the initial file sync, registers the repo with the
Update Manager, and restarts services.

**Restarting KlipperScreen after changing a panel:**

```bash
bash ~/autoloader/scripts/service_restart.sh KlipperScreen
```

`sudo systemctl restart KlipperScreen` over a non-interactive ssh fails with
"a terminal is required to read the password" and returns 1 — and paired with
the `2>/dev/null` that usually follows, it is a restart that reports nothing
and does nothing. KlipperScreen ran for two days on two-day-old code while
every deploy claimed to have restarted it; the symptom was a touchscreen
showing a guide that had been rewritten twice, with the old step numbering.

`service_restart.sh` goes through Moonraker like the Klipper one does, and
then **checks the process actually changed PID** — matching the real Python
process, not the unit, because KlipperScreen's MainPID is a launcher and the
process holding the imported panels is a grandchild under xinit. "The unit is
active" is true even when nothing reloaded.

**Verification** (always run after a deploy or when something feels off):

```bash
./scripts/verify.sh
```

Checks symlink state, service health, recent log errors, and scans every
on-printer location for forbidden patterns. Default scan looks for stale
`stealth_autoloader` references; pass custom patterns as args after a future
rename: `./scripts/verify.sh OLD_NAME OldName`.

### Project Surface — every place code lives on the printer

If you add a new file to the project, add its destination here AND update
`post_update.sh` (if not symlinked) or `install.sh` (if symlinked).

| Repo path | On-printer destination | Sync mechanism |
|---|---|---|
| `klipper/extras/autoloader.py` + 5 `sa_*.py` | `~/klipper/klippy/extras/` | symlink (install.sh) |
| `moonraker/sa_moonraker.py` | `~/moonraker/moonraker/components/sa_moonraker.py` | symlink (install.sh) |
| `autoloader/*.cfg` | `~/printer_data/config/autoloader/` | direct copy (post_update.sh) |
| `autoloader/examples/*.cfg` | `~/printer_data/config/autoloader/examples/` | direct copy (post_update.sh) |
| `filaments/brands/*.cfg` | `~/printer_data/config/autoloader/filament_profiles/` | direct copy (post_update.sh). KlipperScreen reads brand files from here; copied without deleting, so a user-added brand file survives |
| — (user-owned) | `~/printer_data/config/autoloader/leds/` | **created empty, never written.** The user's adapted LED config lives here so updates cannot discard it. `post_update.sh` must never copy into or delete from this directory |
| — (user-owned, untracked) | `~/printer_data/config/autoloader/user.cfg` | Written **once** by `install.sh`, never by `post_update.sh`. `autoloader.cfg` includes it **last**, and Klipper parses with `strict=False`, so any value here overrides `parameters.cfg` without editing a tracked file. Carries the `#[include leds/*.cfg]` opt-in switch. Re-running `install.sh` prompts keep / upgrade / overwrite; `SA_USER_CFG=keep\|upgrade\|overwrite` answers it unattended, and no terminal means keep |
| — (user-owned, untracked) | `~/printer_data/config/autoloader/variables.cfg` | `[save_variables]` — every calibrated bowden length, encoder mm/pulse and selector position. Not in the repo, so nothing else holds a copy |
| `autoloader/*.html` | `~/printer_data/config/autoloader/` | direct copy (post_update.sh) |
| `KlipperScreen/panels/sa_*.py` | `~/KlipperScreen/panels/` | direct copy (post_update.sh) |
| `KlipperScreen/sa_*.py` | `~/KlipperScreen/` | direct copy (post_update.sh) |
| `KlipperScreen/addons/*.py` | `~/KlipperScreen/addons/` | direct copy (post_update.sh) |
| `scripts/patch_klipperscreen.sh` | edits `~/KlipperScreen/screen.py` | **re-applied by post_update.sh on every update.** A KlipperScreen update replaces screen.py and takes the hook with it silently, so this runs every time rather than once. `install.sh --uninstall` reverts it, but only when no other add-on is left using it |
| `KlipperScreen/sa_klipperscreen.conf` | `~/printer_data/config/sa_klipperscreen.conf` | direct copy (post_update.sh) |
| `web/mainsail/AutoloaderPanel.vue` | compiled into `~/mainsail/assets/*.js` | manual rebuild from VS source — not auto-synced |
| `web/mainsail-plugin/dist/*.js` | `~/mainsail/plugins/autoloader-panel-plugin.js`; registered in the Moonraker DB | `bash scripts/deploy_mainsail_plugin.sh` — builds, copies, and rewrites the registration's `entryUrl` to carry the built file's hash. The URL was fixed, so browsers cached it forever and every update needed a manual Ctrl+Shift+R; without one a shipped change looks like a failed deploy. Runs from the dev machine (needs npm); `SA_HOST=` to retarget |
| `web/fluidd/AutoloaderPanel.vue` | depends on Fluidd host setup | user-managed |

### Rename-class changes — extra steps beyond the routine deploy

A project-wide rename (like `stealth_autoloader` → `autoloader`) needs all of
the routine sync PLUS these one-time fixups, because the routine deploy
doesn't cover compiled bundles, persistent caches, or auto-generated config
blocks:

1. **Compiled Mainsail bundle** in `~/mainsail/assets/*.js` has the old
   identifier baked in. Either rebuild from the VS source (proper) or
   sed-rewrite in place (fast — make a backup first):
   ```bash
   ssh pi@192.168.1.214 "cp -r ~/mainsail/assets ~/mainsail/_pre_rename_$(date +%s)/ && \
       for f in \$(grep -rlE 'OLD_PATTERN' ~/mainsail/assets/ ~/mainsail/index.html); do \
           sed -i 's/OLD_PATTERN/NEW_PATTERN/g' \$f; done"
   ```
2. **Moonraker SQLite cache** (`~/printer_data/database/moonraker-sql.db`)
   stores repo metadata under `namespace_store / update_manager / <name>`.
   Renames need: stop moonraker → DELETE the cached row → start moonraker.
3. **`printer.cfg` SAVE_CONFIG block** at the bottom (lines starting with
   `#*#`) contains the old section name. Rename `#*# [OLD_SECTION]` →
   `#*# [NEW_SECTION]` directly with sed.
4. **`moonraker.conf` `[update_manager …]` block** has both a section name
   and `path:` field referencing the old name — both need updating.
5. **stale `__pycache__` directories** under `~/KlipperScreen/panels/` and
   `~/KlipperScreen/`. `rm -rf` them; Python rebuilds on next start.
6. **Browser cache** — hard-refresh (Ctrl+Shift+R) Mainsail/Fluidd. JS
   bundle filenames don't change in a sed-rewrite, so the browser will keep
   serving the cached old code without an explicit refresh.

After all of the above, run `./scripts/verify.sh OLD_PATTERN` to confirm
nothing was missed.

---

## Calibration Sequence (first-time setup)

**The guide is the sequence.** `_GUIDE` in `klipper/extras/sa_calibration.py`
holds all eleven steps in order, each with its live value, what to expect and
what to check when it misbehaves, and both UIs render exactly that. Open it
with `SA_GUIDE OPEN=1`, or Autoloader → Calibration on the touchscreen.

This section used to repeat the list. That made it a fourth place the order
was written down, and it went stale like the other three: it never mentioned
`SA_CALIBRATE_ENCODER_SPEED` at all, and still had the encoder steps in the
order the guide itself had wrong until 2026-09-10. **Do not list the steps
here again.** If the order needs to change, change `_GUIDE` — every UI follows
it, and nothing else describes it.

What belongs here is only what the guide cannot cover, because it happens
before the guide or outside it:

- **Flash and connect the board**, and put its `canbus_uuid` in
  `hardware.cfg`. Find it with
  `~/klippy-env/bin/python ~/klipper/scripts/canbus_query.py can0`.
- **On a NEW build, run `SA_CALIBRATE_SERVO` before ever sending `SA_ENGAGE`.**
  An arm fitted at the wrong angle turns `SA_ENGAGE` into a hard stop, and the
  calibration is the routine that takes the arm off before anything moves.
- **Load filament on path 0, past the drive gear, before the servo step.**
  The engage-angle search is the only part that needs filament, so that step
  can be started earlier and finished once filament is in.
- **The Bowden step needs the extruder sensors**, and the toolhead sensor test
  must pass first — the guide orders those correctly, but the Bowden step also
  needs the tube physically attached, which nothing can check for you.
- **Finish with `SA_LOAD TOOL=0`.** The guide proves each step in isolation;
  a full load is the only thing that proves the sequence.

---

## Licence

GPL-3.0-or-later (LICENSE, added 2026-09-10). The repo had no licence until
then, which meant all rights reserved by default -- nobody could legally use
or redistribute it, despite `main` being what end users install.

GPL-3.0 because the whole stack already is: Klipper, Moonraker and Mainsail
are GPL-3.0, and KlipperScreen is AGPL-3.0. A Klipper extra is imported into
and runs inside Klipper's process using its internal APIs, so a permissive
licence here would have been a claim the project could not really make.

This is what makes reading Happy Hare (GPL-3.0) for reference safe. It does
NOT change the rule below -- reusing its code would still make this a
derivative of a 1000-star project rather than its own thing, and the
architectures differ. Reference, do not copy.

## Happy Hare — Reference Rules

Happy Hare (https://github.com/moggieuk/Happy-Hare) is referenced for:
- ERCF V2 mechanical topology (selector + drive gear + servo)
- Encoder calibration concept (mm_per_pulse, single encoder for all paths)
- Config file style and Python extra class patterns

Do NOT copy Happy Hare code. This project does not need:
- Gate/selector that moves encoder position
- Tip forming, spoolman, LED, servo retract sequences
- Multi-color on single toolhead (it's a multi-toolhead printer)
- Any MMU-specific logic

If code resembles Happy Hare too closely, simplify it for single-path-per-tool architecture.

---

## What Not To Do

- Do not modify printer.cfg, klipper-toolchanger, or core klipper files
- Do not put load/unload sequences in macros — they live in autoloader.py
- Do not add per-path feed motors — there is ONE drive motor for all paths
- Do not use `^` before a chip name on output pins (step pins) — only valid on input pins
- Do not define `[mcu autoloader]` in printer.cfg — it's in hardware.cfg
- Do not add trailing comma to last alias in `[board_pins]`
- Do not SCP `References/` folder to printer
- Do not create separate `[filament_feed toolN]` sections — replaced by `[autoloader]`
- Do not use blocking `reactor.pause()` poll loops to wait for SA_RESPOND — the GCode mutex blocks it. Use the state machine in SACalibration instead.
- Do not add "are you ready?" confirmation prompts — user initiated the command, that is confirmation enough.
- Do not add `insert_gcode` to the entry sensors. Auto-park is owned by the
  `[autoloader]` state monitor's park queue. Klipper's `RunoutHelper` only
  fires `insert_gcode` when `idle_timeout.state != "Printing"`, and
  `idle_timeout` reads "Printing" during *any* gcode — including an
  auto-park already running for another path. It also sets
  `filament_present` before that check returns, so the edge is consumed
  and never re-fires: two spools inserted in quick succession lost the
  second park outright.
- Do not make `SA_RESTORE_PROFILE` automatic. Restoring a stashed profile on
  re-insertion is right when the same spool goes back in and dangerous when a
  different one does — the machine would report red PLA while holding blue PETG
  and heat to PLA's temperatures for it. The monitor announces that a stash
  exists; the operator confirms.
- Do not treat the untuned rows in the per-material tip table as calibrated.
  Only the PLA row is measured. Every other row is that material's typical
  print temperature offset by PLA's measured deltas, which assumes the deltas
  transfer between polymer families — they may not, since the shear temperature
  depends on glass transition. The table is labelled accordingly; keep it so.
- Do not run `scripts/klipper_service_restart.sh` from a dev machine without
  `SA_HOST` set. It posts to `localhost:7125`, which is the printer only when
  the script runs there.
- Do not put the LED switch, or any user-editable setting, in a tracked file.
  `post_update.sh` overwrites everything it copies. The switch lives in
  `user.cfg`, which only `install.sh` writes and only after asking.
- Do not `rm -rf` `~/printer_data/config/autoloader/` in `install.sh --uninstall`.
  It holds `variables.cfg` — hours of calibration that exists nowhere else —
  plus `user.cfg` and any adapted `leds/`. Uninstall copies those aside first.
- Do not re-enable LEDs by default, and do not move the example into
  `autoloader/leds/`. That directory is the user's; `post_update.sh` overwrites
  everything it copies, so anything shipped there would discard their tuning on
  the next update.
- Do not replace KlipperScreen's subscription. Moonraker keeps one per
  connection, unions them when asking Klipper, and filters delivery back per
  connection — so a client that subscribes again with a smaller set silently
  loses everything it left out, and the symptom is the host's temperatures
  quietly ceasing to change. `install_subscription_merge` wraps
  `MoonrakerApi.object_subscription` on the class so every call sends the
  accumulated union, which also keeps `autoloader` alive when KlipperScreen
  re-subscribes after a Klippy restart. If that wrap cannot be installed we
  poll instead and never touch the subscription: our data a second late beats
  the host's data not arriving.
- Do not assume a subscription delivers a value. Moonraker sends CHANGED
  fields only, so a field that never changes again is never delivered: the
  KlipperScreen guide read a status object containing one key and silently
  fell back to step 1. `_ensure_subscription` seeds with a one-shot query
  after subscribing. The same mistake in a different shape — a watcher
  installed with nothing subscribed to — cost the previous hour. Wiring the
  pipe is not priming it, and both versions log success while doing nothing.
- Do not read a KlipperScreen panel's own state out of `printer.data` without
  seeding it. Moonraker delivers CHANGED fields only, so a field that has not
  moved since KlipperScreen subscribed has never been sent and is simply absent
  — `guide_step` sits at 1 all session until someone pages the guide, so the
  guide panel had no step number, could not follow the printer, and sat on one
  page while Mainsail walked the chain. Every autoloader panel does a one-shot
  `printer/objects/query?autoloader` in `activate()` for this reason; the guide
  was the one that did not. This is the same trap as the subscription seeding,
  one layer up, and it looks like the panel ignoring the printer.

- Do not populate a KlipperScreen panel only in `activate()`. `attach_panel`
  adds the content, calls `process_update`, THEN `activate()`, and only then
  `show_all()` — so the first construction of a panel can end up built but not
  shown, with every later activation reusing the cached object and looking
  fine. Re-render on `GLib.idle_add` after activate. Same class as the
  sa_macros first-attach history and the carousel centring fix.
- Do not reset an encoder before calling `servo_engage()`. It jitters the drive
  ±0.8mm three times to seat the gear teeth — 4.8mm of travel — and the encoder
  adds `mm_per_pulse × direction` per pulse regardless of which way the
  filament actually went, so with the direction already set forward the whole
  4.8mm counts as feed. `SA_CALIBRATE_ENCODER` did exactly this and read 1.6%
  low: its +2.0% was really +3.7%, which is what the speed sweep independently
  measured. Seat first, reset second. And `servo_engage()` on an already-engaged
  gear seats nothing — it just walks the filament ±0.8mm off whatever datum the
  operator has set by hand, so it now returns early unless `force_seat=True`.

- Do not fold repeated calibration passes into each other. Three passes are
  three samples of one quantity, so run them all at the SAME starting value and
  average the ratios. `SA_CALIBRATE_ENCODER` used to feed each pass the
  previous pass's answer, which makes a chain rather than a set: measuring 100,
  107, 95 gave 0.931 because the last pass sets the result and the 95 was 5%
  low. Show the spread as well as the mean, and refuse to save when the passes
  disagree by more than a few percent — that is measurement scatter, and
  averaging it produces a confident-looking number that is still wrong.
  Size the datum against the human error too: eyeballing a tip flush and
  reading a rule is a fixed few mm, which is 3% of a 100mm feed and 1% of a
  300mm one.

- Do not ask the operator to move filament by hand without releasing the drive
  motor first. The gear holds the filament and the motor holds the gear, so
  `servo_engage()` alone locks it solid — engage, then `drive_disable()`, and
  the knob feeds it. This has now been wrong twice in the same way, in
  `calibrate_drive` and `calibrate_encoder`. While anything is being measured,
  re-energise so nothing creeps; release again before the next reposition.
  Use the gate exit as the datum rather than a mark on the filament: it is
  already there, it needs no tape or marker, and both calibrations now share
  it — set the tip flush, feed, measure what is sticking out.

- Do not measure an encoder against the stepper when the question is about
  speed. They are the machine's only two references, so a fault present at
  every speed gets charged to whichever speed is on screen. On T0 a constant
  3.8% survived two wrong diagnoses — reversal slack (a take-up move changed
  nothing) and count quantisation (two counts fitted the numbers exactly) —
  before doubling the pass length settled it: the percent held while the
  millimetres went 3.8 → 7.0, tracking distance. A count loss does not do that.
  It was `mm_per_pulse` 3.7% low. Reference the sweep to its own slowest pass
  instead: at 25mm/s a state spans about seven 2ms samples so aliasing cannot
  happen, which makes that pass a pure measure of scale, and everything above
  it a measure of the encoder falling behind. Report the scale separately —
  it is real and wants recalibrating — but never inside the speed figure.
  Report mm alongside percent: varying the distance is what tells a fixed
  offset from a proportional one, and neither column alone can.

- Do not read a short encoder count as a drive fault without checking it
  against something outside the loop. The encoder and the stepper are the only
  two references the machine has, and a motor losing steps looks exactly like
  an encoder missing counts. `SA_VERIFY_FEED` is the referee: gate-exit datum,
  one pass at a chosen speed, operator measures what came out. There is a real
  encoder ceiling to find — Klipper's `buttons` module samples the pin every
  2ms (`QUERY_TIME` in `klippy/extras/buttons.py`) and these encoders change
  state about every 1.9mm, so above roughly 235mm/s there are fewer than four
  samples per state and counts start being missed while the filament moves
  perfectly well.

- Do not let a hand test pass on a reading alone when the reading is the thing
  under test. `SA_TEST_ENTRY_SENSORS` waits for CLEAR, then FILAMENT, then
  CLEAR again — the last two need the sensor to actually change and so cannot
  be faked by a dead or unplugged one, but the first is satisfied by anything
  reading CLEAR, including a sensor that is not connected and a path that was
  never emptied. It would then run the remaining stages on filament that was
  already there and save the result. The operator's answer is the only thing in
  the loop that is not the sensor, so the empty check asks and compares. Same
  reason `SA_TEST_ENDSTOP` confirms rather than infers.

- Do not report homed without evidence. `selector_home` set the flag at the end
  of the routine whatever had happened, and startup set it too whenever a
  position was restored from save_variables — so after any Klipper restart the
  guide said "Homed" although nothing had homed. Two checks now gate it: an
  endstop that already reads TRIGGERED is backed off first (STOP_ON_ENDSTOP
  stops the first move instantly, so Klipper reports success and zero lands
  wherever the carriage was standing), and the switch must read TRIGGERED at
  the end or homing raises instead of setting the flag. A restored position is
  kept but is NOT homed — it is a guess that nothing moved while the power was
  off, and the guide says so in those words.

- Do not add sensorless/stallguard homing — homing is physical endstop only (SA_SELECTOR_STOP / PA15). The endstop pin ships as `^autoloader:SA_SELECTOR_STOP`. This file used to claim `^!` was mandatory; it is not, and following that would have broken homing. Measured on the machine with the carriage off the switch: `^` reads open (correct), `^!` reads TRIGGERED, which makes homing stop instantly and call that zero. Which polarity is right depends on the switch wiring, so `SA_TEST_ENDSTOP` settles it per printer and writes the answer to user.cfg.

## Prompt Wording Rules

The guide explains; the prompt asks. A prompt is read standing at the machine
on a 480px screen, where the buttons leave room for three or four lines — so
anything above that is invisible, and what survives is whichever paragraph
happens to be last. That is how a yes/no question came to show only its
footnote about what to do when the answer is no.

- **Send the body as ONE `prompt_text` — unless you pass `ks_line`.**
  KlipperScreen's `prompts.py` does
  `self.text = data.replace('prompt_text ', '')` — an ASSIGNMENT — so it keeps
  only the LAST line and throws the rest away. Mainsail renders **one
  paragraph per `prompt_text`**: `MacroPromptText.vue` is instantiated per
  event and emits its own `<p>`. So sending a line each looks right on the web
  and shows one sentence on the touchscreen — a yes/no question arrived as
  "Is it?" with nothing above it.
- **`_emit_ui_prompt(..., ks_line=…)` uses that disagreement instead of
  working around it.** The body goes out a line at a time, which Mainsail
  renders as a table, and `ks_line` goes LAST — which is precisely what
  KlipperScreen keeps. One emission, both screens served, nothing to keep in
  step. The encoder speed sweep is the worked example: a row per rung on the
  web, the current pass on the touchscreen.
  **`ks_line` must stand entirely on its own.** Anything whose meaning depends
  on the lines above it must use the single-line form — that dependency is the
  bug the rule was written for.
- **Lead with the instruction**, not the reading and not the diagnosis. Nothing
  has gone wrong yet, and text about what to check when it does reads as though
  something has.
- **Budget roughly 150 characters** with two buttons, and less with four. The
  measured offenders were 483, 431, 362 and 299 — eight or nine lines each.
- **Put the reasoning on the guide page** for that step. It scrolls, it has
  room, the operator is returned to it between steps, and it says the same
  thing on both screens.
- **One line for the consequence** where it is the point of the check — "Left
  alone, this path would be recorded as proved" earns its place; three
  paragraphs explaining the mechanism do not.
- **Say what the reading means**, not just what it is. "It now reads TRIGGERED.
  That means the carriage is ON the switch." — a yes/no question needs its
  answer visible or it cannot be answered.
- **Never describe behaviour the machine no longer has.** The endstop confirm
  advertised "answering NO writes the correction" for weeks after that was
  changed to explaining the fix instead.

## Console Output Rules

- **Every command must be in its own individual code block** — never combine multiple commands in one block.
- This applies to all responses: GCode commands, bash commands, test steps, calibration sequences, deploy instructions.
- All SA_RESPOND prompts must be on their own clearly separated lines so the user can copy-paste without typos.
- Use `_prompt(gcmd, message, *commands)` helper in SACalibration — it formats commands with leading spaces on their own lines.
- Print calibration phase progress as plain text (no extra decoration needed).

## Calibration Architecture

Calibration uses a non-blocking phase state machine:
- `owner._cal_state` (str | None): current phase key, e.g. `'sel_confirm'`, cleared on Klipper restart
- `owner._cal_data` (dict): data bag passed between phases (positions, measurements, attempt counts, etc.)
- `SA_RESPOND VALUE=x` calls `calibration.respond(gcmd, value)` which dispatches to the correct `_*_respond()` handler
- Each phase runs to completion (no blocking waits) and either finishes or sets the next state + prompts
- `SA_RESPOND VALUE=abort` always cancels and clears state
- State is automatically cleared on Klipper restart — no risk of waking up mid-calibration after a power cycle

## Giving me commands to run (hard rule, every command, every session)
Assume I am NOT a developer and may paste from any shell, any window, any current
directory. Treat every command as if it will be pasted blind:
- **Paste-once.** Give ONE block I paste a single time and press Enter — never a
  sequence of "run this, then that, then check where you are."
- **Location-independent.** Never assume my current directory or which window is open.
  Use absolute paths, or make the command find things itself. Never tell me "make sure
  you're in folder X" — put the full path in the command.
- **No fragile multi-line pastes.** Multi-line pastes into PowerShell get mangled by the
  `>>` continuation. Use one physical line (joined with `;`), or have me save a script
  file and run it. Never hand me a loose multi-line block to paste line-by-line.
- **Self-checking.** Detect what you depend on instead of assuming it, and stop at the
  FIRST real failure with a clear message instead of cascading.
- **Tell me what to send back.** End with what success looks like and exactly which
  output to copy if it fails.
- **Assume non-expert.** No unstated setup steps, no jargon-only instructions.

If a command can't meet this, fix the command — don't hand me something that needs me to
already be in the right place.
