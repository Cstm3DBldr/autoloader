# sa_button_style.py — shared button CSS for all Autoloader panels

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk
import os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sa_ui_prefs as _prefs

_provider = None
# Last min-height applied, so a later reapply() for an accent change
# does not silently reset the floor back to the default.
_last_min_h = None


# Every sa-* style rides on one of KlipperScreen's own button classes, so it
# inherits whatever that theme gives a button -- surface, corner radius,
# padding, pressed state. Themes differ enormously here: z-bolt's colorN sets
# only a border colour, while colorized's also swaps the background to a
# lighter base and rounds the corners to 1em. Hand-rolling a surface matched
# one theme and clashed with the next.
#
# We override exactly one property: the bottom border colour, so the accent
# picker still works.
_KS_BASE = {
    'sa-btn':      'color1',
    'sa-btn-alt':  'color3',
    'sa-btn-warn': 'color2',
    'sa-btn-nav':  'color4',
}


def _build_css(accent, hover, active, min_h=62):
    """Accent colour and touch height. Nothing else.

    No background, no radius, no padding: those come from the theme's own
    `button.colorN` rule, which is the whole point. Selectors are written as
    `button.sa-btn.color1` so they carry more specificity than the theme's
    `button.color1` and the accent actually lands.
    """
    return ("""
button.sa-btn.color1      {{ border-bottom-color: {accent}; }}
button.sa-btn-warn.color2 {{ border-bottom-color: #E8A33D; }}

.sa-btn, .sa-btn-alt, .sa-btn-warn {{ min-height: {min_h}px; }}
.sa-btn-nav {{ min-height: {nav_h}px; }}

.path-selected {{ border: 3px solid #8BC34A; }}
""".format(accent=accent, min_h=int(min_h), nav_h=int(min_h * 0.68))).encode()


def apply(min_height=None):
    """Install the shared button CSS.

    `min_height` is the floor every button gets, in px. Pass a value derived
    from the framework font size -- `max(40, _gtk.font_size * 2.4)` is what
    the panels use -- so it tracks resolution and the user's font_size
    preference.

    It matters more than it looks. A CSS min-height is a hard floor that
    set_size_request cannot go under, so a fixed value here silently sets the
    minimum height of every page built from these buttons. At the old 62 px
    the macros page could not request less than 410 px of content, which
    overflowed the grid and stretched the action bar -- and no amount of
    sizing work in the panel could have fixed it, because the floor was here.

    Defaults to 62 only so an un-updated caller keeps its old look.
    """
    global _provider, _last_min_h
    if min_height is None:
        min_height = _last_min_h if _last_min_h is not None else 62
    _last_min_h = min_height
    p = _prefs.load()
    css = Gtk.CssProvider()
    css.load_from_data(_build_css(
        p.get("accent_color",  "#1565C0"),
        p.get("hover_color",   "#1976D2"),
        p.get("active_color",  "#0D47A1"),
        min_h=min_height,
    ))
    screen = Gdk.Screen.get_default()
    if _provider is not None:
        Gtk.StyleContext.remove_provider_for_screen(screen, _provider)
    Gtk.StyleContext.add_provider_for_screen(
        screen, css, Gtk.STYLE_PROVIDER_PRIORITY_USER)
    _provider = css


def reapply(accent, hover=None, active=None):
    """Change accent color, derive hover/active if not given, persist and reapply."""
    # Simple brightness shift for hover/active if not explicit
    if hover is None:
        hover = _lighten(accent, 0.1)
    if active is None:
        active = _darken(accent, 0.15)
    _prefs.save({
        "accent_color": accent,
        "hover_color":  hover,
        "active_color": active,
    })
    apply()


def make(label, style="sa-btn"):
    """A button that is a KlipperScreen button first, ours second.

    The KS class carries the theme's whole appearance; our class contributes
    only the accent underline. Change theme and these follow it, because they
    are not styled independently of it.
    """
    btn = Gtk.Button(label=label)
    ctx = btn.get_style_context()
    base = _KS_BASE.get(style)
    if base:
        ctx.add_class(base)
    ctx.add_class(style)
    return btn


def _lighten(hex_c, amt):
    r, g, b = _parse(hex_c)
    r = min(255, int(r + 255 * amt))
    g = min(255, int(g + 255 * amt))
    b = min(255, int(b + 255 * amt))
    return "#{:02X}{:02X}{:02X}".format(r, g, b)


def _darken(hex_c, amt):
    r, g, b = _parse(hex_c)
    r = max(0, int(r - 255 * amt))
    g = max(0, int(g - 255 * amt))
    b = max(0, int(b - 255 * amt))
    return "#{:02X}{:02X}{:02X}".format(r, g, b)


def _parse(hex_c):
    h = hex_c.lstrip('#')
    if len(h) == 3:
        h = ''.join(c*2 for c in h)
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


# ── Progress dots ────────────────────────────────────────────────────────────
# Shared horizontal dot strip used by sa_calibration_guide (and any future
# multi-step wizard). Returns a Pango markup string suitable for
# Gtk.Label.set_markup().
#
# step_idx : 0-based current step
# total    : total step count
# name     : optional human-readable step name appended to the right
#
# Colors:  done = green     ●
#          current = blue   ●  (bold)
#          upcoming = grey  ○

_DONE   = "#388E3C"
_NOW    = "#1565C0"
_UPCOME = "#424242"
_LINE   = "#424242"


def progress_dots(step_idx, total, name=None):
    # Dots are deliberately at "medium" size (was "x-large" — that
    # combined with the step name pushed the nav-bar natural width past
    # the 720 px content area on a 480 px display, which cascaded into
    # other widgets in the same wrapper Box being clipped on the right
    # edge). The page already has a visible step header, so the name
    # arg is now ignored unless the caller really wants it appended.
    parts = []
    for i in range(total):
        if i < step_idx:
            parts.append(
                '<span foreground="%s" font_size="medium">●</span>' % _DONE)
        elif i == step_idx:
            parts.append(
                '<span foreground="%s" font_size="medium" weight="bold">●</span>'
                % _NOW)
        else:
            parts.append(
                '<span foreground="%s" font_size="medium">○</span>' % _UPCOME)
    sep = '<span foreground="%s">━</span>' % _LINE
    dots = sep.join(parts)
    suffix = "Step %d of %d" % (step_idx + 1, total)
    return '%s   <span font_size="small">%s</span>' % (dots, suffix)

