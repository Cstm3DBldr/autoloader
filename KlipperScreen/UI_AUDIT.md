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
user to reach it. A scroll container makes overflow survivable on every
screen instead of fatal on small ones.

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

## Plan

Ordered so each step is independently verifiable on hardware.

1. **Scroll containers first (F1).** Wrap the four panels' content in
   `self._gtk.ScrolledWindow()`. Cheap, low risk, and immediately converts
   every "off the screen" bug into a scroll. Do this before any redesign so
   the rest can be evaluated without content vanishing.
2. **Replace guessed arithmetic with `content_height` (F2).** Delete the
   `- 60 - 74 - 50` style constants and the caps that compensate for them.
3. **Adopt `AutoGrid` for button groups (F3).** Removes manual row/column
   maths in `sa_home`, `sa_macros`, `sa_load_unload` and `sa_post_load`, and
   gives portrait for free via its `vertical` flag.
4. **Rebuild the numpad on the stock `.numpad_*` classes (F5).**
5. **Retire `sa_button_style.py` in favour of `self._gtk.Button` and the
   theme classes (F4).** Largest diff, mostly deletion. Keep filament swatch
   colours literal.
6. **Re-verify on 480x320 and 1024x600**, not only this display —
   KlipperScreen can be run windowed at a given resolution for this.

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
