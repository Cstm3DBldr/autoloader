import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk, GLib
import logging
import os
import subprocess
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import sa_button_style as _sbs
import sa_ui_prefs     as _prefs
from ks_includes.screen_panel import ScreenPanel

logger = logging.getLogger('klipperscreen.sa_settings')


def _autoloader_version():
    """Best-effort `git describe` against the deployed autoloader repo so
    the About section can show what build is actually running. Falls back
    to a hard-coded label if the git invocation fails (no git binary, no
    repo, or timeout). Computed once at module import; safe to cache for
    the lifetime of the panel — the only way it changes is by pulling new
    code, which requires a Klipperscreen restart anyway."""
    repo = os.path.expanduser("~/autoloader")
    try:
        out = subprocess.check_output(
            ["git", "-C", repo, "describe",
             "--tags", "--always", "--dirty"],
            stderr=subprocess.DEVNULL, timeout=2.0)
        return out.decode().strip() or "unknown"
    except Exception:
        # Fallback: try just the short HEAD sha.
        try:
            out = subprocess.check_output(
                ["git", "-C", repo, "rev-parse", "--short", "HEAD"],
                stderr=subprocess.DEVNULL, timeout=2.0)
            return out.decode().strip() or "unknown"
        except Exception:
            return "unknown"


_VERSION = _autoloader_version()

_COLORS = [
    ("Blue",        "#1565C0", "#1976D2", "#0D47A1"),
    ("Teal",        "#00695C", "#00897B", "#004D40"),
    ("Green",       "#2E7D32", "#388E3C", "#1B5E20"),
    ("Purple",      "#6A1B9A", "#7B1FA2", "#4A148C"),
    ("Indigo",      "#283593", "#303F9F", "#1A237E"),
    ("Deep Orange", "#BF360C", "#D84315", "#870000"),
    ("Red",         "#B71C1C", "#C62828", "#7F0000"),
    ("Pink",        "#880E4F", "#AD1457", "#560027"),
    ("Brown",       "#4E342E", "#5D4037", "#3E2723"),
    ("Grey",        "#37474F", "#455A64", "#263238"),
    ("Amber",       "#E65100", "#F57C00", "#BF360C"),
    ("Cyan",        "#006064", "#00838F", "#004D40"),
]


class Panel(ScreenPanel):
    # -- Sizing derived from the framework, never hard-coded ------------------

    def _touch(self):
        return int(max(44.0, self._gtk.font_size * 2.4))

    def _gap(self):
        return int(max(4.0, self._gtk.font_size * 0.34))

    def _pad_bottom(self):
        """Breathing room under the locked footer, proportional so it does not
        eat the slack on a small screen the way a fixed value would."""
        return int(self._gap() * 2.5)

    def __init__(self, screen, title):
        super().__init__(screen, title or "Autoloader Settings")
        _sbs.apply(min_height=self._touch())

        self._last_sa = {}

        self._stack = Gtk.Stack()
        self._stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
        self._stack.set_transition_duration(150)
        # See sa_macros.py for the rationale — Gtk.Stack defaults to sizing
        # to its largest child page, which stretches base_panel's left
        # action bar and clips the bottom power icon.
        self._stack.set_vhomogeneous(False)
        self._stack.set_hhomogeneous(False)

        self._stack.add_named(self._build_main_page(), "main")
        self._stack.add_named(self._build_detail_page(), "detail")

        self.content.pack_start(self._stack, True, True, 0)

    # ── Main settings page ────────────────────────────────────────────────────

    def _build_main_page(self):
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_overlay_scrolling(False)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin=10)

        # NOTIFICATIONS section removed — the popup-on-complete toggle is
        # now unconditional default behaviour. See sa_subscription.py
        # for the matching cleanup of the _prefs lookup that gated it.

        # -- Accent colour: a carousel, not a grid --------------------------
        #
        # A fixed grid can only ever show as many colours as the width allows
        # -- three on a 3.5 inch panel -- so the palette size was limited by
        # the screen. A carousel decouples them: the strip scrolls, the centre
        # slot is the selection, and it snaps to the nearest chip when
        # released so the choice is always a whole colour rather than a
        # halfway scroll position.
        outer.pack_start(self._section("BUTTON ACCENT COLOR"), False, False, 0)

        self._accent_btns     = {}
        self._accent_name_lbl = Gtk.Label(halign=Gtk.Align.CENTER)
        self._selected_hex    = _prefs.get("accent_color", "#1565C0")
        self._snap_id         = None

        chip = int(max(48.0, self._gtk.font_size * 3.1))
        self._chip_px   = chip
        self._chip_gap  = self._gap()
        self._chip_step = chip + self._chip_gap

        caro = Gtk.ScrolledWindow()
        caro.set_policy(Gtk.PolicyType.EXTERNAL, Gtk.PolicyType.NEVER)
        caro.set_size_request(-1, int(chip * 1.45))
        caro.set_kinetic_scrolling(True)
        self._caro = caro

        strip = Gtk.Box(spacing=self._chip_gap)
        self._strip = strip

        # Three copies of the palette laid end to end. Scrolling is kept in
        # the middle copy: when it drifts into the first or last, the
        # adjustment jumps by exactly one copy width, which is invisible
        # because the pixels either side are identical. That is what makes it
        # endless -- you never reach a first or last colour.
        self._reps  = 3
        self._chips = []
        for rep in range(self._reps):
            for idx, (name, hex_c, hover, active) in enumerate(_COLORS):
                btn = Gtk.Button()
                cls = "sa-accent-%d" % idx
                if rep == 0:
                    css = Gtk.CssProvider()
                    css.load_from_data((
                        # margin:0 matters as much as the colour. base.css gives
                    # every button `margin: .2em`, so each chip was occupying
                    # chip + 2*margin while the snap arithmetic assumed
                    # chip + spacing -- an error of ~7 px that ACCUMULATED,
                    # putting the snap a whole chip out by the far end of the
                    # strip and selecting the wrong colour.
                    ".{c} {{ background: {bg}; border-radius: {r}px; "
                        "min-width: {w}px; min-height: {w}px; padding: 0; "
                        "margin: 0; border: 0; }}"
                        ".{c}:hover {{ background: {hv}; }}"
                        ".{c}:active {{ background: {ac}; }}"
                    ).format(c=cls, bg=hex_c, hv=hover, ac=active,
                             r=chip // 2, w=chip).encode())
                    Gtk.StyleContext.add_provider_for_screen(
                        Gdk.Screen.get_default(), css,
                        Gtk.STYLE_PROVIDER_PRIORITY_USER + 1)
                btn.get_style_context().add_class(cls)
                btn.set_size_request(chip, chip)
                btn.set_valign(Gtk.Align.CENTER)
                btn.connect("clicked", self._on_chip, hex_c, hover, active, idx)
                strip.pack_start(btn, False, False, 0)
                self._chips.append((btn, idx, hex_c, hover, active))
                if rep == 1:
                    # The middle copy is the one positions are measured from.
                    self._accent_btns[hex_c] = btn

        caro.add(strip)

        marker = Gtk.DrawingArea()
        marker.set_size_request(chip + 10, chip + 10)
        marker.set_halign(Gtk.Align.CENTER)
        marker.set_valign(Gtk.Align.CENTER)
        marker.connect("draw", self._draw_marker)

        stack = Gtk.Overlay()
        stack.add(caro)
        stack.add_overlay(marker)
        stack.set_overlay_pass_through(marker, True)
        outer.pack_start(stack, False, False, 0)

        caro.get_hadjustment().connect("value-changed", self._on_caro_scroll)
        caro.connect("size-allocate", self._on_caro_size)

        self._accent_name_lbl.set_markup(
            '<span font_size="small" foreground="#9E9E9E">%s</span>'
            % self._color_name_for(self._selected_hex))
        outer.pack_start(self._accent_name_lbl, False, False, 0)

        # ── Configured values — scrolls with the page, uses accent color ──────
        detail_btn = _sbs.make("Autoloader Configured Values \u2192", "sa-btn")
        detail_btn.connect("clicked", lambda w: self._stack.set_visible_child_name("detail"))
        detail_btn.set_margin_top(8)
        outer.pack_start(detail_btn, False, False, 0)

        cv_hint = Gtk.Label(halign=Gtk.Align.START)
        cv_hint.set_markup(
            '<span font_size="small" foreground="#9E9E9E">'
            '  Read the speeds, distances, bowden lengths, and encoder '
            'mm/pulse currently in use.</span>')
        outer.pack_start(cv_hint, False, False, 0)

        # ── Material profiles ─────────────────────────────────────────────────
        outer.pack_start(self._section("MATERIAL PROFILES"), False, False, 0)

        reset_btn = _sbs.make("Reset All Material Profiles", "sa-btn-warn")
        reset_btn.connect("clicked", self._reset_materials)
        outer.pack_start(reset_btn, False, False, 0)

        # ── About / version ───────────────────────────────────────────────────
        # Cached at module import via _autoloader_version(). Tap-to-copy
        # would be nice but isn't a normal Gtk.Label gesture; keeping it
        # display-only for now. If you ever need to roll back, the version
        # string here matches what `git describe --tags --always --dirty`
        # prints in ~/autoloader on the printer.
        about_hdr = self._section("ABOUT")
        about_hdr.set_margin_top(12)
        outer.pack_start(about_hdr, False, False, 0)

        ver_row = Gtk.Box(spacing=6)
        ver_lbl = Gtk.Label(halign=Gtk.Align.START)
        ver_lbl.set_markup(
            '<span foreground="#E0E0E0">Autoloader </span>'
            '<span foreground="#90CAF9">%s</span>'
            % GLib.markup_escape_text(_VERSION))
        ver_row.pack_start(ver_lbl, False, False, 0)
        outer.pack_start(ver_row, False, False, 0)

        repo_lbl = Gtk.Label(halign=Gtk.Align.START)
        repo_lbl.set_markup(
            '<span font_size="small" foreground="#9E9E9E">'
            '  github.com/Cstm3DBldr/autoloader</span>')
        outer.pack_start(repo_lbl, False, False, 0)

        scroll.add(outer)
        return scroll

    # ── Detail page ────────────────────────────────────────────────────────────

    def _build_detail_page(self):
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_overlay_scrolling(False)

        self._detail_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL,
                                   spacing=6, margin=10)
        scroll.add(self._detail_box)
        outer.pack_start(scroll, True, True, 0)

        back_btn = _sbs.make("\u2190  Back", "sa-btn-alt")
        back_btn.set_margin_start(10)
        back_btn.set_margin_end(10)
        back_btn.set_margin_bottom(self._pad_bottom())
        back_btn.connect("clicked", lambda w: self._stack.set_visible_child_name("main"))
        outer.pack_start(back_btn, False, False, 0)

        return outer

    def _populate_detail(self, sa):
        box = self._detail_box
        for child in box.get_children():
            box.remove(child)

        num               = sa.get("num_paths", 0)
        bowden_lens       = sa.get("bowden_lengths", [])
        sel_pos           = sa.get("selector_positions", [])
        enc_mpp           = sa.get("encoder_mpp", [])
        feed_speed        = sa.get("feed_speed",              "\u2014")
        selector_speed    = sa.get("selector_speed",          "\u2014")
        purge_length      = sa.get("purge_length",            "\u2014")
        nozzle_dist       = sa.get("nozzle_distance",         "\u2014")
        nozzle_to_sensor  = sa.get("nozzle_to_sensor_dist",   "\u2014")
        drv_rot_dist      = sa.get("drive_rotation_distance", "\u2014")
        enc_max           = sa.get("encoder_max_speed",       0)

        def row(label, value, fg="#FFFFFF"):
            r = Gtk.Box(spacing=8)
            ll = Gtk.Label(label=label, halign=Gtk.Align.START, xalign=0.0)
            ll.set_hexpand(True)
            vl = Gtk.Label(halign=Gtk.Align.END)
            vl.set_markup('<span foreground="%s">%s</span>' % (fg, str(value)))
            r.pack_start(ll, True,  True,  0)
            r.pack_start(vl, False, False, 0)
            return r

        # ── Speeds ────────────────────────────────────────────────────────────
        box.pack_start(self._section("SPEEDS"), False, False, 0)
        box.pack_start(row("Feed Speed",        "%s mm/s" % feed_speed),     False, False, 0)
        box.pack_start(row("Selector Speed",    "%s mm/s" % selector_speed), False, False, 0)
        if enc_max and enc_max > 0:
            blast = enc_max * 0.75
            box.pack_start(row("Encoder Max Speed",
                               "%.1f mm/s" % enc_max), False, False, 0)
            box.pack_start(row("Blast Speed (75%)",
                               "%.1f mm/s" % blast),   False, False, 0)
        else:
            box.pack_start(row("Encoder Max Speed", "\u2014 (run CAL ENCODER SPEED)"),
                           False, False, 0)

        # ── Distances ─────────────────────────────────────────────────────────
        box.pack_start(Gtk.Separator(), False, False, 4)
        box.pack_start(self._section("DISTANCES"), False, False, 0)
        box.pack_start(row("Purge Length",
                           "%s mm" % purge_length),       False, False, 0)
        box.pack_start(row("Toolhead Sensor \u2192 Nozzle",
                           "%s mm" % nozzle_to_sensor),   False, False, 0)
        box.pack_start(row("Extruder Gears \u2192 Nozzle",
                           "%s mm" % nozzle_dist),        False, False, 0)
        box.pack_start(row("Drive Rotation Dist",
                           str(drv_rot_dist)),            False, False, 0)

        # ── Per-path bowden ───────────────────────────────────────────────────
        box.pack_start(Gtk.Separator(), False, False, 4)
        box.pack_start(self._section("PER-PATH BOWDEN LENGTH"), False, False, 0)
        for i in range(num):
            val = ("%.1f mm" % bowden_lens[i]) if i < len(bowden_lens) else "\u2014"
            box.pack_start(row("T%d" % i, val, "#90CAF9"), False, False, 0)

        # ── Selector positions ────────────────────────────────────────────────
        if sel_pos:
            box.pack_start(Gtk.Separator(), False, False, 4)
            box.pack_start(self._section("SELECTOR POSITIONS"), False, False, 0)
            for i in range(num):
                val = ("%.2f mm" % sel_pos[i]) if i < len(sel_pos) else "\u2014"
                box.pack_start(row("T%d" % i, val, "#FFCC80"), False, False, 0)

        # ── Encoder mm/pulse ──────────────────────────────────────────────────
        if enc_mpp:
            box.pack_start(Gtk.Separator(), False, False, 4)
            box.pack_start(self._section("ENCODER mm/pulse"), False, False, 0)
            for i in range(num):
                val = ("%.4f" % enc_mpp[i]) if i < len(enc_mpp) else "\u2014"
                box.pack_start(row("T%d" % i, val, "#CE93D8"), False, False, 0)

        box.show_all()

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _section(self, title):
        lbl = Gtk.Label(halign=Gtk.Align.START)
        lbl.set_markup('<b><span font_size="large">%s</span></b>' % title)
        return lbl

    def _color_name_for(self, hex_c):
        """Look up the human-readable name of an accent hex from _COLORS."""
        for name, h, _hv, _ac in _COLORS:
            if h.lower() == hex_c.lower():
                return name
        return hex_c

    def _draw_marker(self, area, cr):
        """Outline the centre slot. Nothing else marks the selection."""
        w = area.get_allocated_width()
        h = area.get_allocated_height()
        r = 10.0
        cr.set_source_rgba(1, 1, 1, 0.95)
        cr.set_line_width(2.5)
        cr.new_sub_path()
        cr.arc(w - r - 1, r + 1, r, -1.5708, 0)
        cr.arc(w - r - 1, h - r - 1, r, 0, 1.5708)
        cr.arc(r + 1, h - r - 1, r, 1.5708, 3.1416)
        cr.arc(r + 1, r + 1, r, 3.1416, 4.7124)
        cr.close_path()
        cr.stroke()
        return False

    def _on_caro_size(self, widget, alloc):
        """Keep the end spacers at half the visible width.

        Without them the first and last colours can never reach the centre
        slot, so the ends of the palette would be unselectable.
        """
        # No end spacers any more -- the extra copies play that role, and any
        # colour can reach the centre because there is always more strip on
        # both sides.
        # Centre the stored colour once the strip has a real allocation.
        # Doing it earlier clamps to zero, because the adjustment's upper
        # bound is still the unpadded width -- which is what leaves the
        # marker sitting off the selected chip on first open.
        if not getattr(self, '_caro_centred', False) and alloc.width > 1:
            self._caro_centred = True
            GLib.idle_add(self._centre_on, self._selected_hex, False)

    def _chip_centre_at(self, n):
        """Centre x of the nth chip in the strip.

        Computed, not measured. translate_coordinates was returning nothing
        usable for these buttons -- every snap logged "found no chip position"
        and so did nothing, which is why stopping the strip neither settled
        nor selected.

        Computing is safe here precisely because the strip is now uniform:
        a plain Gtk.Box of equal-width chips with one spacing between each and
        no end spacers, so the nth chip starts at n * step. The earlier
        arithmetic was wrong only because a leading spacer added a gap this
        layout no longer has.
        """
        return n * self._chip_step + self._chip_px / 2.0

    def _copy_width(self):
        """Width of one full copy of the palette."""
        return len(_COLORS) * self._chip_step

    def _clamp_adj(self, value):
        adj = self._caro.get_hadjustment()
        top = max(adj.get_lower(), adj.get_upper() - adj.get_page_size())
        return max(adj.get_lower(), min(value, top))

    def _scroll_to_n(self, n):
        self._caro.get_hadjustment().set_value(
            self._clamp_adj(self._chip_centre_at(n)
                            - self._caro.get_allocated_width() / 2.0))

    def _rewrap(self):
        """Keep the scroll inside the middle copy.

        Jumping by exactly one copy width lands on an identical pixel, so the
        strip reads as endless. Without it the palette stops at a first and a
        last colour.
        """
        adj = self._caro.get_hadjustment()
        cw = self._copy_width()
        if cw <= 0:
            return
        v = adj.get_value()
        if v < cw * 0.5:
            adj.set_value(v + cw)
        elif v > cw * 1.5:
            adj.set_value(v - cw)

    def _on_caro_scroll(self, adj):
        """Snap once scrolling stops; debounced so it cannot fight a drag."""
        self._rewrap()
        if self._snap_id is not None:
            GLib.source_remove(self._snap_id)
        self._snap_id = GLib.timeout_add(160, self._do_snap)

    def _do_snap(self):
        """Settle on the chip nearest the marker, and select it."""
        self._snap_id = None
        if not self._chips:
            return False
        adj   = self._caro.get_hadjustment()
        focus = adj.get_value() + self._caro.get_allocated_width() / 2.0

        n = int(round((focus - self._chip_px / 2.0) / self._chip_step))
        n = max(0, min(n, len(self._chips) - 1))

        target = self._clamp_adj(self._chip_centre_at(n)
                                 - self._caro.get_allocated_width() / 2.0)
        if abs(adj.get_value() - target) > 0.5:
            adj.set_value(target)

        _btn, _idx, hex_c, hover, active = self._chips[n]
        if hex_c != self._selected_hex:
            self._set_color(None, hex_c, hover, active)
        return False

    def _centre_on(self, hex_c, animate=True):
        """Bring a colour to the centre slot, using its middle-copy chip."""
        for n, (btn, idx, h, hv, ac) in enumerate(self._chips):
            if h == hex_c and n >= len(_COLORS):
                self._scroll_to_n(n)
                return False
        return False

    def _on_chip(self, widget, hex_c, hover, active, idx):
        """A tap selects and slides that colour to the centre.

        Centring on the tapped widget rather than the middle copy's twin, so a
        tap near an edge does not jump the strip a whole palette sideways.
        """
        self._set_color(widget, hex_c, hover, active)
        for n, (btn, _i, _h, _hv, _ac) in enumerate(self._chips):
            if btn is widget:
                self._scroll_to_n(n)
                break
        self._rewrap()

    def _set_color(self, widget, hex_c, hover, active):
        # No per-chip ring any more: the centre marker IS the selection, and
        # a ring as well would mark the same thing twice.
        self._selected_hex = hex_c
        _prefs.save({"accent_color": hex_c})
        _sbs.reapply(hex_c, hover, active)
        # Update the "Currently: X" hint without rebuilding the page.
        if getattr(self, "_accent_name_lbl", None) is not None:
            self._accent_name_lbl.set_markup(
                '<span font_size="small" foreground="#9E9E9E">%s</span>'
                % self._color_name_for(hex_c))
        self._screen.show_popup_message(
            "Button color updated \u2014 reopen panels to see changes", level=1)

    def _reset_materials(self, widget):
        sa = self._last_sa
        n  = sa.get("num_paths", 6)
        for i in range(n):
            self._screen._ws.klippy.gcode_script(
                'SA_SET_MATERIAL TOOL=%d MATERIAL="" BRAND="" LINE="" '
                'COLOR_NAME="" COLOR_HEX="" '
                'LOAD_TEMP=200 UNLOAD_TEMP=185 PURGE_SPEED=5 PURGE_LENGTH=30' % i)
        self._screen.show_popup_message("All material profiles cleared", level=1)

    def _query_sa(self):
        try:
            resp = self._screen.apiclient.send_request(
                "printer/objects/query?autoloader")
            if resp and 'status' in resp:
                return resp['status'].get('autoloader', {})
        except Exception as e:
            logger.warning("sa_settings: query failed: %s", e)
        return {}

    def activate(self):
        self._stack.set_visible_child_name("main")
        sa = self._query_sa()
        self._last_sa = sa
        self._populate_detail(sa)

    def process_update(self, action, data):
        pass
