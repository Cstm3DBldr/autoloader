# KlipperScreen Autoloader UI — Audit and Redesign Plan

**Date:** 2026-09-02
**Scope:** the nine `sa_*` panels and five `sa_*` support modules.
**Verified against:** the live install on 192.168.1.214 (KlipperScreen at
`~/KlipperScreen`), display 800x480 landscape, `font_size: medium` -> 17.8.

---

## Summary

The panels were built with a private layout and styling system: fixed pixel
heights, hand-rolled arithmetic against `self._screen.height`, and a parallel
palette of hard-coded Material colours. KlipperScreen already provides the
mechanisms for all three, and stock panels use them. That gap is the root
cause of the reported symptoms — content off-screen, the oversized numpad,
inconsistent look — rather than several unrelated bugs.

Five findings below are structural. Fixing them is largely mechanical, and
removes code rather than adding it.

---

## What KlipperScreen already gives us

From `ks_includes/KlippyGtk.py` (the `self._gtk` object every panel holds):

| Provided | What it is | What we do instead |
|---|---|---|
| `content_width` / `content_height` | Usable area, already minus titlebar and action bar, **and already correct in portrait** | Subtract guessed constants from `_screen.height` |
| `font_size` | Scales with resolution *and* the user's `font_size` setting (small -> max) | Hard-code px |
| `img_scale`, `img_width`, `img_height`, `button_image_scale` | Icon sizing that tracks `font_size` | Multiply `img_scale` by our own factors |
| `Button(icon, label, style, scale, position, lines)` | Themed button, label wrapping via `format_label` | `sa_button_style.make()` with private CSS |
| `ScrolledWindow(steppers=True)` | Scrolling container | Nothing, in 4 of 9 panels |
| `Dialog(...)` | Themed modal | Hand-built |
| `color_list` | Theme's graph colours, refreshed on theme change | Hard-coded hex |

And in `ks_includes/widgets/`, unused by us:

- **`autogrid.py`** — `AutoGrid(items, max_columns, expand_last, vertical)`.
  Picks the column count from the item count, is row- and column-homogeneous
  so children size themselves to the space, and takes a `vertical` flag for
  portrait. This is the "fancy way" to stop things falling off.
- **`keypad.py`** — a numpad widget. Its constructor is temperature-specific
  (`change_temp`, `pid_calibrate`), so it is a pattern to copy rather than
  call directly, but the themed `.numpad_*` CSS classes it uses are ours to
  reuse as-is.
- **`prompts.py`** — the stock Klipper `action:prompt_*` dialog system, which
  `sa_cal_prompt.py` reimplements.
- `scroll.py`, `keyboard.py`, `flowboxchild_extended.py`.

`base.css` defines the themed classes we should be using: `button.color1`
through `color4`, `.numpad_button`, `.numpad_key`, `.numpad_left/right/top/`
`bottom/tleft/tright/bleft/bright`, `.dialog-{default,error,info,primary,`
`secondary,warning}`, `.message_popup_{error,warning,echo}`,
`.filament_sensor_{detected,empty}`, `.warning`, `.error`, `.frame-item`,
`.buttons_slim`, `.horizontal_togglebuttons`, `.title_bar`, `.content`.

---

## Findings

### F1 — Four panels have no scroll container, so content is clipped

27 of 35 stock KlipperScreen panels wrap their content in a
`ScrolledWindow`. Of ours, 5 of 9 do. Missing:

| Panel | Consequence |
|---|---|
| `sa_cal_prompt.py` | The reported oversized numpad — see F5 |
| `sa_home.py` | Hero row plus fixed 110 px utility row cannot shrink |
| `sa_macros.py` | Three sections of fixed-height rows; the CSS shims and the mandatory vexpand spacer in `_build_main_page` exist to fight this |
| `sa_post_load.py` | Fixed 56 px and 38 px rows |

Anything taller than `content_height` is simply cut off, with no way for the
user to reach it.

**The fix is not to add scroll containers.** These pages must fit — see the
Plan. The absence of a scroll container is only worth listing because it is
what turns an oversize layout from ugly into unusable; once nothing requests
fixed pixels, none of these pages exceeds its budget and the question does not
arise. `sa_settings.py` keeps its scroll, being a genuine long list.

### F2 — Screen arithmetic is guessed, and throws away real estate

Three sites compute their own idea of available height:

```
sa_load_unload.py:263   avail = self._screen.height - 60 - 74 - 50
sa_load_unload.py:566   return max(60, min(90, self._screen.height // 5))
sa_main.py:100          return max(32, (self._screen.height - 160) // (paths * 2))
```

On this 800x480 display the first gives **296 px**. KlipperScreen's own
`content_height` is **444 px**. We discard 148 px — a third of the panel —
and then add caps to compensate.

The constants also encode a landscape 800x480 assumption. `content_height`
is already right everywhere, including portrait.

### F3 — No portrait support at all

No `sa_*` panel references `vertical_mode`. KlipperScreen supports it and
changes three things when it is set: the action bar moves to the bottom
(`action_bar_height = height * .1`, `content_width` becomes the full width),
the font ratio changes from `[40, 27]` to `[28, 42]`, and `AutoGrid` takes a
`vertical` flag to re-flow columns. Every panel that subtracts its own
constants from `_screen.height` is wrong in portrait.

### F4 — A parallel palette that ignores the selected theme

`sa_button_style.py` defines `.sa-btn`, `.sa-btn-alt`, `.sa-btn-warn`,
`.sa-btn-nav` with hard-coded Material colours — `#37474F`, `#455A64`,
`#263238`, `#E65100`, `#1565C0`, `#424242`, `#9E9E9E` and more. A further
**85 hex literals** are spread across the panels:

| File | Hex literals |
|---|---|
| `sa_settings.py` | 47 |
| `sa_main.py` | 9 |
| `sa_post_load.py` | 8 |
| `sa_cal_prompt.py` | 6 |
| `sa_load_unload.py` | 5 |
| `sa_calibration_guide.py` | 3 |
| `sa_home.py`, `sa_config.py` | 2 each |
| `sa_macros.py` | 1 |

KlipperScreen ships `material-dark`, `material-darker`, `material-light`,
`colorized` and `z-bolt`. Our panels are dark-theme-only by construction: on
`material-light` they render dark buttons on a light chrome. Filament swatch
colours are legitimately literal — they represent real filament — but chrome
should come from `button.colorN` and the semantic classes.

### F6 — A CSS `min-height` was the real floor, beating every Python change

Measured on the device, not inferred. `sa_button_style.py` carried
`min-height: 62px` on `.sa-btn`, `.sa-btn-alt` and `.sa-btn-nav`.

**A CSS `min-height` cannot be undercut by `set_size_request`** — GTK takes
the larger of the two. So every button on the macros page reported a 76 px
minimum (62 + padding + border) no matter what the panel asked for, four
button rows could not go below 304 px, and the page's minimum sat at 410. The
grid then measured 494 on a 480 px screen, and because the action bar spans
both grid rows it stretched by the 14 px difference, spreading its icons.

Before and after, from the live panel:

| | before | after |
|---|---|---|
| button min | 76 | 58 |
| page min | 410 | 356 |
| content allocation | 458 | 444 |
| `main_grid` | 494 (14 over) | 480 (exact) |

The floor now derives from `_gtk.font_size` and is passed in by the panel:
`sa_button_style.apply(min_height=...)`, remembered across `reapply()` so an
accent-colour change does not silently reset it.

**The rule this establishes:** fixed pixels in the stylesheet outrank
everything in Python, and are invisible when reading the panel code. The
stylesheet needs auditing for *dimensions*, not only the colours in F4. Two
places still to check: `.sa-section-header` and the `.action_bar` overrides in
`sa_macros._install_action_bar_css`, both of which pin sizes in CSS.

**Only `sa_macros` passes a derived floor so far.** Every other panel still
calls `_sbs.apply()` bare and keeps the 62 px default, so any panel that looks
stretched has this same cause.

### F5 — The numpad cannot fit a small screen

`sa_cal_prompt.py` builds its own numpad from fixed heights:

```
entry display        48
4 rows x 52          208   + 3 row gaps x 4 = 220
SEND button          56
3 outer gaps x 4     12
                    ---
minimum              336 px
```

before the prompt message above it. Against `content_height`:

| Display | `content_height` | Numpad fits? |
|---|---|---|
| 480x320 (3.5", KS minimum) | 296 | **No — overflows by 40 px before any message** |
| 800x480 (this display) | 444 | Only 108 px left for message and title |
| 1024x600 | 556 | Fits, but the pad stays 336 px and looks lost |

With no `ScrolledWindow` (F1) the overflow is unreachable rather than
scrollable. The stock `.numpad_*` classes size from `font_size`, so they
shrink and grow correctly on their own.

---

## Target displays

KlipperScreen's minimum is 480x320, and "if a device can display a GNU/Linux
desktop, it should be compatible" — so the design has to be resolution-driven,
not tuned to three sizes. These are the ones to check against:

| Resolution | Typical hardware | `font_size` | `content` (landscape) |
|---|---|---|---|
| 480x320 | 3.5" RPi display | 11.9 | 432 x 296 |
| 800x480 | **BTT PiTFT43** (this one), BTT PI TFT50, RPi 7" official, Waveshare 4.3" DSI, Hyperpixel 4, most 5"/7" HDMI | 17.8 | 720 x 444 |
| 1024x600 | BTT HDMI7, 7" HDMI-B | 22.2 | 922 x 556 |
| 720x720 | Hyperpixel 4 Square | 18.0 | 648 x 684 |
| portrait | any of the above rotated | `[28, 42]` ratio | full width, action bar at bottom |

`font_size` values are `min(w/40, h/27)` at the default `medium`; the user's
`font_size` setting then scales it from 0.91x (small) to 1.06x (max), so every
layout must survive a further +/-10% on text without clipping.

---

## Plan — fit every screen, no scrolling

**No panel scrolls.** These are touchscreen tool pages: each one has a purpose
and everything for that purpose belongs on it, one fingertip away. Scrolling
to hunt for a button is the failure, not the fix. `sa_settings.py` is the sole
exception — it is a long list of preferences and already scrolls.

### The layouts are already right. The pixels are what break them.

Every existing layout fits at 480x320 — KlipperScreen's minimum — with rows
above a finger-usable floor. Nothing needs redesigning:

| Panel | Rows its layout needs |
|---|---|
| `sa_cal_prompt` numpad | 6 (display + 4 pad rows + send) |
| `sa_load_unload` | 5 (status + 3 path rows + actions) |
| `sa_macros` | 5 |
| `sa_post_load` | 4 |
| `sa_home` | 3 (hero counts 2, utility 1) |

Against what each display can seat, using a touch floor of
`min_touch = max(44, font_size * 2.6)`:

| Display | `font_size` | `content_height` | `min_touch` | Rows that fit |
|---|---|---|---|---|
| 480x320 | 11.9 | 296 | 44 | **6** |
| 800x480 | 17.8 | 444 | 46 | 9 |
| 1024x600 | 22.2 | 556 | 58 | 9 |
| 720x720 | 18.0 | 684 | 47 | 14 |

The worst case is the numpad on the smallest screen: 296 / 6 = **49 px per
row**, comfortably over the 44 px floor. The same numpad currently demands a
fixed **336 px** and so overflows that screen by 40 px. The layout was never
the problem.

### The rule: request shares, not pixels

`self.content` is already `Gtk.Box(VERTICAL, hexpand=True, vexpand=True)` and
`self._gtk.content_height` is the exact budget. If children ask for no height
and expand instead, GTK divides the real space and the page fits by
construction at any resolution.

1. **Pin the content to the framework's budget, once, in `__init__`:**

   ```python
   self.content.set_size_request(-1, self._gtk.content_height)
   self.content.set_vexpand(False)
   ```

   In landscape the action bar is attached spanning both grid rows
   (`base_panel.py:124`), so it negotiates height with the content row. Giving
   content an exact request stops that fight on the first allocation pass.
   `sa_macros.py` already does this — it is the correct pattern, not a
   workaround, and it belongs in every panel.

2. **Inside, no height `set_size_request` at all.** Use
   `Gtk.Grid(row_homogeneous=True, column_homogeneous=True)` with children
   set `hexpand=True, vexpand=True`, or `AutoGrid`. Rows then divide
   `content_height` evenly.

3. **Weight sections by row span, not by pixels.** A 2:1 hero-to-utility split
   is a 3-row homogeneous grid with the hero attached `height=2` and the
   utility `height=1`. Exact proportions, zero arithmetic, correct on every
   display.

4. **Size text and icons from `font_size`**, never in points or pixels:
   `img_scale`, `img_width`, `button_image_scale` all track it, and it already
   folds in the user's small-to-max preference.

5. **Guard the touch floor instead of scrolling.** Compute
   `min_touch = max(44, self._gtk.font_size * 2.6)` and
   `seats = int(self._gtk.content_height // min_touch)`. If a page ever wants
   more rows than `seats`, change the *arrangement* — more columns, or split
   across a `Gtk.Notebook` page — rather than shrinking below a fingertip or
   adding a scrollbar. On the numbers above, no current page hits this.

6. **Portrait comes free** once steps 1-4 hold, because `content_height`,
   `content_width` and `font_size` already account for it. `AutoGrid` takes a
   `vertical` flag for column re-flow.

### Order of work

Each step is independently verifiable on hardware.

1. `sa_cal_prompt.py` — the numpad, worst offender and self-contained. Proves
   the technique.
2. `sa_load_unload.py` — delete `avail = height - 60 - 74 - 50` and the 50/72
   caps; path buttons become a homogeneous grid.
3. `sa_home.py` — hero/utility as a 3-row span split, replacing the fixed
   110 px utility row.
4. `sa_macros.py` — sections as row spans; keep the fixed-pt section header.
5. `sa_post_load.py`, `sa_main.py`, `sa_config.py`, `sa_calibration_guide.py`.
6. Theme adoption (F4) last, as it touches every file and is mostly deletion.
7. Re-verify at 480x320 and 1024x600, not only on this display.

### This supersedes the locked layouts in CLAUDE.md

`CLAUDE.md` pins user-confirmed canonical layouts for `sa_load_unload.py`,
`sa_home.py` and `sa_macros.py`, and says to restore them unless a different
layout is explicitly asked for. This work is that explicit request, so the
locks are lifted for it — but the *reasons* recorded there are hard-won and
must survive the rewrite:

- **The `sa_macros` section-header font must stay a fixed pt size**, never
  em-based `x-small` or `letter_spacing`. Those depend on font-metric
  measurement that is unstable on the first realize pass and added ~4 px per
  header, which is what pushed content over and clipped the power icon.
- **`sa_macros` uses `Gtk.Notebook`, not `Gtk.Stack`** — Stack's
  `vhomogeneous=False` does not reliably apply on the first allocation after a
  KlipperScreen restart.
- **The trailing vexpand spacer in `_build_main_page` is load-bearing** while
  the page has only fixed-height children. Once `AutoGrid` and a
  `ScrolledWindow` are in, re-test whether it is still needed rather than
  deleting it blind.
- **The `sa_load_unload` swatch must sit in its own homogeneous grid column
  with `halign=CENTER`**, not a `Box`/`pack_start` chain, or label widths
  push it off-centre.
- Swatch size floor of 36 px (readable at arm's length) and the 3-column
  `T# | swatch | material` structure are user-confirmed and should be
  preserved in proportion, not in absolute pixels.

Anything restored should be expressed as a ratio of `font_size` or
`content_height` rather than the pixel value that happened to suit 800x480.

---

## Agreed build spec — the five unlocked panels

Settled with Mike across the A/B reviews. Build to this; do not re-open the
decisions without asking.

### All pages

- **Bottom padding**, `gap * 2.5` — 15 px at 800x480, 10 px at 480x320.
  Proportional because a fixed value is free on a 4.3" panel and eats most of
  the slack on a 3.5" one.
- **One gap value throughout** a page. Uneven gaps were visible in review.
- **Footers locked outside the scroll**, padding beneath them.

### sa_main — status table

- Columns: `# | STATE | TEMP | EN | EX | TH | ENCODER | MATERIAL | COLOUR`.
- **No glyph before the state word.** The colour already encodes it — amber
  partial, dim empty, blue loaded — and the width is better spent on MATERIAL
  and COLOUR, which are the cells that run out of room.
- **TEMP per channel**, read from that path's extruder. Amber above the 50 C
  `heater_fan` threshold, dim below — the same signal that drives the nozzle
  LEDs, so screen and printer agree on which heads are hot.
- **Row height** = clamp(data_area / heads, 34, font_size * 3.4), where
  data_area is the viewport **minus the table's own header row**. Forgetting
  that header is what clipped the sixth row in review. Scroll past what fits:
  5 heads on a 3.5", 9 at 800x480 and 1024x600.
- Below 800 px wide, **drop columns rather than shrink them**: the three
  sensor columns merge into one cell holding the same three dots, and COLOUR
  folds into MATERIAL as a swatch. Five columns at ~86 px beats nine at 48.

#### Active-tool indicator

A left accent stripe and a tinted row — **no marker glyph**; the moving bar is
unambiguous alone, survives the column drop, and costs no width.

Driven entirely by `toolchanger`, which needs no gcode watching:

| `toolchanger.status` | Highlight | Row |
|---|---|---|
| `ready` | solid | `tool_number` |
| `changing` | pulsing | `tool_number` — moves when it flips |
| `initializing` | pulsing | as above |
| `uninitialized` | none | nothing marked; `tool_number` is -1 |
| `error` | solid, amber stripe | last known |

**Pulse on the same 4 s breathing period as the rack logo LEDs**
(`sa_led_animator`: `breathing_period 4.0`, sine, `smoothing 0.22`), so the
screen and the printer say the same thing in the same rhythm.

`toolchanger.py` flips `active_tool` inside `_configure_toolhead_for_tool()`,
after the old head is parked and before the new one is picked up — so the bar
pulses on the outgoing head through dropoff, hops at that boundary, and
pulses on the incoming head through pickup. The target tool is never exposed
in `get_status()`, which is why this follows `tool_number` rather than trying
to jump to the destination at the T command. `initializing` and `error` are
Claude's calls, not Mike's: the first behaves like a change, and the second
keeps a stale indicator rather than none, since losing it when something is
wrong is worse.

### sa_post_load — pick-then-confirm flow

Replaces the two parallel T-rows. Nothing fires on a single tap.

1. Action row: **PURGE 60mm** (after a load) or **LOAD SAME** (after an
   unload) — already mutually exclusive by state — plus **PARK** and
   **CLEAN NOZZLE** (`SA_CLEAN_NOZZLE`, new).
2. **LOAD / UNLOAD toggle** deciding the verb.
3. **One scalable grid** of heads, 3 wide, tiles showing the material and
   colour already loaded — which the plain T-buttons never did, and which is
   what you are deciding against when changing a colour.
4. **EXIT + confirm**, locked at the bottom. The confirm is dead until a head
   is picked, and then names the action and target: "LOAD T3", not "GO".

Grid scales: 1 row at 3 heads, 2 at 6, 4 at 12, scrolling past 12 at 800x480.
**Cost to accept:** the flow's furniture is 231 px of the 296 available at
480x320, leaving one row of three, so six heads scroll there where the old
two-row design showed all six at 38 px. That trade is deliberate — 38 px is
below a reliable finger target, and the code comment admits it was chosen to
make two rows fit.

Nothing is dropped: PURGE, LOAD SAME, PARK, EXIT, load-any-path and
unload-any-path all survive; CLEAN NOZZLE is added.

### sa_config, sa_settings, sa_calibration_guide

Approved as drawn. Config already scrolls with SAVE locked outside it — it
gains only a taller row, a bigger pencil and the padding. Settings needs Back
moved outside the scroll (its own comment says the buttons scroll away today)
and the colour picker becomes a **carousel**: centre slot is the selection,
outlined, name beneath, so palette size stops being limited by screen width.
The guide needs the padding and its fixed 150 px Back/Next widths made
font-derived — on a 480 px screen those two claim 300 px between them.

**Still open:** whether the carousel snaps to the nearest colour on release,
or centres a tapped neighbour.
