import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk, GLib
import logging
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import sa_button_style as _sbs
import sa_subscription as _sasub
from ks_includes.screen_panel import ScreenPanel

logger = logging.getLogger('klipperscreen.sa_main')

COLOR_SWATCH = '\u2b24'
EMPTY_SWATCH = '\u25ef'

# No glyph before the word: the colour already encodes the state, and the
# width is better spent on MATERIAL and COLOUR, which are the cells that
# actually run out of room.
_STATE_MARKUP = {
    'loaded':  ('<b>LOADED</b>', '#388E3C'),
    'empty':   ('EMPTY',         '#616161'),
    'partial': ('PARTIAL',       '#E65100'),
    'unknown': ('UNKNOWN',       '#F9A825'),
}

# Above this the hotend reads as hot. Klipper's heater_fan already manages
# the same threshold, and sa_led_animator uses the fan to decide the amber
# nozzle warning -- so screen and printer agree on which heads are hot.
_TEMP_HOT_C   = 50.0
_TEMP_HOT_COL = '#FFB74D'
_TEMP_COLD_COL = '#7E9AB1'

# Matches sa_led_animator.breathing_period. The row highlight and the rack
# logo LEDs then pulse together during a tool change.
_PULSE_PERIOD_MS = 4000

_ROW_CSS = b"""
.sa-row-active {
    background-color: rgba(28,77,120,1);
    transition: background-color 2000ms ease-in-out;
}
.sa-row-active.sa-row-dim { background-color: rgba(18,49,78,1); }
.sa-row-stripe { box-shadow: inset 3px 0 0 #4FC3F7; }
.sa-row-stripe.sa-row-dim { box-shadow: inset 3px 0 0 #2B6D96; }
.sa-row-error  { box-shadow: inset 3px 0 0 #E8A33D; }
"""
_row_css_installed = False


def _install_row_css():
    """Install the active-row styling once per session.

    The pulse is a CSS transition driven by a class toggle rather than a GTK
    CSS animation: transitions are reliable across GTK3 builds, and toggling
    one class every 2000 ms costs a single timer tick instead of redrawing at
    animation frame rate.
    """
    global _row_css_installed
    if _row_css_installed:
        return
    try:
        prov = Gtk.CssProvider()
        prov.load_from_data(_ROW_CSS)
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), prov,
            Gtk.STYLE_PROVIDER_PRIORITY_USER + 50)
        _row_css_installed = True
    except Exception:
        logging.exception("sa_main: failed to install row CSS")
_DOT_ON     = '#388E3C'
_DOT_OFF    = '#616161'
_ENC_ACTIVE = '#42A5F5'
_ENC_IDLE   = '#616161'


def _rgba_from_hex(hex_c):
    rgba = Gdk.RGBA()
    if hex_c and Gdk.RGBA.parse(rgba, hex_c):
        return rgba
    if hex_c and Gdk.RGBA.parse(rgba, '#' + hex_c):
        return rgba
    Gdk.RGBA.parse(rgba, 'rgba(97,97,97,1)')
    return rgba


def _effective_state(i, states, entry, toolhead, extruder):
    e  = entry[i]    if i < len(entry)    else None
    th = toolhead[i] if i < len(toolhead) else None
    ex = extruder[i] if i < len(extruder) else None
    if e is None:
        return states[i] if i < len(states) else 'unknown'
    if not e and not th and not ex:
        return 'empty'
    if e and th and ex:
        return 'loaded'
    if e or th or ex:
        return 'partial'
    return states[i] if i < len(states) else 'unknown'


class Panel(ScreenPanel):
    def __init__(self, screen, title):
        super().__init__(screen, title or "Autoloader Status")
        _install_row_css()
        self.labels = {}
        # path -> list of that row's cell widgets, so the active row can be
        # tinted without restructuring the Grid.
        self._row_cells   = {}
        self._active_tool = -1
        self._tc_status   = ''
        self._pulse_id    = None
        self._pulse_dim   = False
        self._num_paths = 0
        self._entry_prev = []
        self._last_sa = {}
        self._enc_distances = {}
        self._last_cal_state = ''

        _sbs.apply(min_height=self._touch())

        scroll = self._gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        # CENTER rather than START: with few toolheads the row cap leaves the
        # table shorter than the viewport, and centring reads as deliberate
        # where top-aligned reads as a page that failed to fill.
        center_box = Gtk.Box(halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        self._grid = Gtk.Grid(row_spacing=2, column_spacing=14, margin=8,
                              row_homogeneous=True)
        self._grid.set_halign(Gtk.Align.CENTER)
        self._build_header()
        center_box.pack_start(self._grid, False, False, 0)
        scroll.add(center_box)
        self.content.pack_start(scroll, True, True, 0)

        bar = Gtk.Grid(row_spacing=4, column_spacing=4, margin=4,
                       row_homogeneous=True, column_homogeneous=True)
        home_btn = _sbs.make("HOME")
        home_btn.connect("clicked", self._send, "SA_HOME")
        home_btn.set_hexpand(True)
        bar.attach(home_btn, 0, 0, 1, 1)

        refresh_btn = _sbs.make("REFRESH")
        refresh_btn.connect("clicked", self._refresh)
        refresh_btn.set_hexpand(True)
        bar.attach(refresh_btn, 1, 0, 1, 1)

        bar.set_margin_bottom(self._pad_bottom())
        # Packed on self.content, outside the scroll, so HOME and REFRESH
        # cannot scroll away from under the finger.
        self.content.pack_end(bar, False, False, 0)

    def _cols(self):
        """Column headings for this display width."""
        if self._narrow():
            return ["#", "STATE", "TEMP", "EN EX TH", "MATERIAL"]
        return ["#", "STATE", "TEMP", "EN", "EX", "TH",
                "ENCODER", "MATERIAL", "COLOR"]

    def _build_header(self):
        for child in self._grid.get_children():
            if self._grid.child_get_property(child, 'top-attach') == 0:
                self._grid.remove(child)
        for col, h in enumerate(self._cols()):
            lbl = Gtk.Label(label=h)
            lbl.get_style_context().add_class("color4")
            lbl.set_halign(Gtk.Align.CENTER)
            self._grid.attach(lbl, col, 0, 1, 1)

    # -- Sizing derived from the framework, never hard-coded ------------------

    def _touch(self):
        """Minimum comfortable finger target, in px."""
        return int(max(44.0, self._gtk.font_size * 2.4))

    def _gap(self):
        return int(max(4.0, self._gtk.font_size * 0.34))

    def _pad_bottom(self):
        return int(self._gap() * 2.5)

    def _row_h(self):
        """Row height, scaled to the toolhead count.

        Sized against the DATA AREA -- the scroll viewport minus the table's
        own header row. Forgetting that header is what clipped the last row in
        review: six rows plus a header overflowed the viewport and the sixth
        hid behind the button bar.

        Clamped between a 34 px readability floor and font_size * 3.4 so three
        heads do not become three enormous bands. Past the floor the table
        scrolls -- 5 heads on a 3.5 inch panel, 9 at 800x480 and 1024x600.

        Replaces `(self._screen.height - 160) // (num_paths * 2)`, which
        guessed the space and then halved it for no stated reason, leaving the
        table using well under half the page.
        """
        g   = self._gap()
        bar = int(max(44.0, self._gtk.font_size * 2.4) * 1.4)
        vp  = self._gtk.content_height - (bar + self._pad_bottom() + g * 4)
        data = max(60.0, vp - self._gtk.font_size * 1.15)
        n = max(self._num_paths, 1)
        return int(min(max(data / n, 34.0), self._gtk.font_size * 3.4))

    def _narrow(self):
        """True on a display too narrow for the full column set.

        Below 800 px the three sensor columns merge into one cell holding the
        same three dots, and COLOUR folds into MATERIAL as a swatch. Five
        columns at ~86 px read where nine at 48 px do not -- the information
        is re-packed, not dropped.
        """
        return self._screen.width < 800

    def _build_rows(self, num_paths):
        for key in [k for k in self.labels if k.startswith('row_')]:
            w = self.labels.pop(key)
            self._grid.remove(w)

        self._num_paths = num_paths
        # Rebuilding rows invalidates every cached cell widget; a stale entry
        # here would have _paint_active_row styling a destroyed widget.
        self._row_cells = {}
        self._build_header()
        rh = self._row_h()
        for i in range(num_paths):
            row = i + 1

            narrow = self._narrow()
            cells = []

            num_lbl = Gtk.Label(halign=Gtk.Align.CENTER)
            num_lbl.set_markup('<b>T%d</b>' % i)
            num_lbl.set_size_request(-1, rh)
            self._grid.attach(num_lbl, 0, row, 1, 1)
            self.labels['row_%d_num' % i] = num_lbl
            cells.append(num_lbl)

            state_lbl = Gtk.Label(label="UNKNOWN", halign=Gtk.Align.CENTER)
            self._grid.attach(state_lbl, 1, row, 1, 1)
            self.labels['row_%d_state' % i] = state_lbl
            cells.append(state_lbl)

            # Hotend temperature for this path's extruder.
            temp_lbl = Gtk.Label(label="\u2014", halign=Gtk.Align.CENTER)
            self._grid.attach(temp_lbl, 2, row, 1, 1)
            self.labels['row_%d_temp' % i] = temp_lbl
            cells.append(temp_lbl)

            if narrow:
                # One cell carrying the same three dots.
                sens = Gtk.Label(halign=Gtk.Align.CENTER)
                self._grid.attach(sens, 3, row, 1, 1)
                self.labels['row_%d_sensors' % i] = sens
                cells.append(sens)
            else:
                for col, key in [(3, 'entry'), (4, 'extruder'), (5, 'toolhead')]:
                    dot = Gtk.Label(label="\u25cb", halign=Gtk.Align.CENTER)
                    self._grid.attach(dot, col, row, 1, 1)
                    self.labels['row_%d_%s' % (i, key)] = dot
                    cells.append(dot)

                enc_lbl = Gtk.Label(label="\u2014", halign=Gtk.Align.CENTER)
                enc_lbl.set_size_request(int(self._gtk.font_size * 3.3), -1)
                self._grid.attach(enc_lbl, 6, row, 1, 1)
                self.labels['row_%d_encoder' % i] = enc_lbl
                cells.append(enc_lbl)

            self._row_cells[i] = cells

            # Narrow: MATERIAL carries the swatch and COLOUR is folded in.
            mat_col = 4 if narrow else 7
            mat_box = Gtk.Box(spacing=self._gap(), halign=Gtk.Align.CENTER,
                              valign=Gtk.Align.CENTER)
            mat_swatch = Gtk.Label(label=EMPTY_SWATCH)
            mat_lbl = Gtk.Label(label="---", halign=Gtk.Align.CENTER,
                                max_width_chars=10, ellipsize=3)
            mat_box.pack_start(mat_swatch, False, False, 0)
            mat_box.pack_start(mat_lbl,    False, False, 0)
            self._grid.attach(mat_box, mat_col, row, 1, 1)
            self.labels['row_%d_material' % i]    = mat_lbl
            self.labels['row_%d_mat_swatch' % i]  = mat_swatch
            cells.append(mat_box)

            if not narrow:
                color_box = Gtk.Box(spacing=6, halign=Gtk.Align.START,
                                    valign=Gtk.Align.CENTER)
                swatch = Gtk.Label(label=EMPTY_SWATCH)
                color_name = Gtk.Label(label="---", halign=Gtk.Align.START,
                                       xalign=0.0, max_width_chars=20,
                                       ellipsize=3)
                color_box.pack_start(swatch,     False, False, 0)
                color_box.pack_start(color_name, False, False, 0)
                self._grid.attach(color_box, 8, row, 1, 1)
                cells.append(color_box)
                self.labels['row_%d_swatch' % i] = swatch
                self.labels['row_%d_color'  % i] = color_name

        self._grid.show_all()

    def _send(self, widget, gcode):
        self._screen._ws.klippy.gcode_script(gcode)

    def _query_sa(self):
        try:
            resp = self._screen.apiclient.send_request(
                "printer/objects/query?autoloader")
            if resp and 'status' in resp:
                return resp['status'].get('autoloader', {})
        except Exception as e:
            logger.warning("sa_main: query failed: %s", e)
        return {}

    def _query_encoders(self, num_paths):
        distances = {}
        try:
            objs = "&".join("sa_encoder%%20%d" % i for i in range(num_paths))
            resp = self._screen.apiclient.send_request(
                "printer/objects/query?" + objs)
            if resp and 'status' in resp:
                status = resp['status']
                for i in range(num_paths):
                    key = "sa_encoder %d" % i
                    enc = status.get(key, {})
                    if enc:
                        distances[i] = float(enc.get('distance', 0.0))
        except Exception as e:
            logger.warning("sa_main: encoder query failed: %s", e)
        return distances

    # -- Temperature ----------------------------------------------------------

    def _extruder_temp(self, i):
        """Hotend temperature for path *i*, or None if it cannot be read.

        Path 0 is `extruder`, path N is `extruderN` -- Klipper's own naming,
        the same mapping the load sequence uses to heat before extruding.
        """
        key = 'extruder' if i == 0 else 'extruder%d' % i
        try:
            d = self._printer.data.get(key) or {}
            t = d.get('temperature')
            return float(t) if t is not None else None
        except Exception:
            return None

    # -- Active tool ----------------------------------------------------------

    def _apply_toolchanger(self, tc):
        """Mark the mounted tool, and pulse the mark while a change runs.

        Everything here comes from `toolchanger`, which needs no gcode
        watching:

          ready         solid on tool_number
          changing      pulsing on tool_number, which moves when it flips
          initializing  pulsing -- it behaves like a change and ends in ready
          uninitialized nothing marked; tool_number is -1
          error         solid with an amber stripe, on the last known row

        toolchanger.py flips active_tool inside _configure_toolhead_for_tool,
        after the old head is parked and before the new one is picked up, and
        never exposes the target. So through a change the mark pulses on the
        outgoing head during dropoff, hops at that boundary, and pulses on the
        incoming head through pickup. The hop marks a real transition rather
        than lagging behind one.
        """
        if not isinstance(tc, dict):
            return
        status = tc.get('status', self._tc_status) or ''
        tool   = tc.get('tool_number', self._active_tool)
        try:
            tool = int(tool)
        except (TypeError, ValueError):
            tool = -1

        if status == 'uninitialized':
            tool = -1

        changed = (tool != self._active_tool) or (status != self._tc_status)
        self._tc_status   = status
        self._active_tool = tool
        if changed:
            self._paint_active_row()
            self._set_pulsing(status in ('changing', 'initializing'))

    def _paint_active_row(self):
        """Apply the highlight classes to exactly one row's cells."""
        for i, cells in self._row_cells.items():
            active = (i == self._active_tool and self._active_tool >= 0)
            for n, w in enumerate(cells):
                ctx = w.get_style_context()
                for cls in ('sa-row-active', 'sa-row-stripe',
                            'sa-row-error', 'sa-row-dim'):
                    ctx.remove_class(cls)
                if not active:
                    continue
                ctx.add_class('sa-row-active')
                if n == 0:
                    ctx.add_class('sa-row-error' if self._tc_status == 'error'
                                  else 'sa-row-stripe')
                if self._pulse_dim:
                    ctx.add_class('sa-row-dim')

    def _set_pulsing(self, on):
        """Start or stop the tool-change pulse.

        Half the LED animator's breathing period per toggle, with a CSS
        transition of the same length doing the interpolation -- so the row
        and the rack logo LEDs breathe together at 4 s, for one timer tick
        every 2 s rather than an animation redraw every frame.
        """
        if on and self._pulse_id is None:
            self._pulse_id = GLib.timeout_add(
                _PULSE_PERIOD_MS // 2, self._pulse_tick)
        elif not on and self._pulse_id is not None:
            GLib.source_remove(self._pulse_id)
            self._pulse_id = None
            self._pulse_dim = False
            self._paint_active_row()

    def _pulse_tick(self):
        self._pulse_dim = not self._pulse_dim
        self._paint_active_row()
        return True

    def deactivate(self):
        # Leaving the panel must stop the timer; it holds a reference to the
        # panel and would otherwise keep ticking against dead widgets.
        self._set_pulsing(False)

    def _refresh(self, widget=None):
        sa = self._query_sa()
        if sa:
            self._apply_sa(sa)
        if self._num_paths:
            encs = self._query_encoders(self._num_paths)
            self._enc_distances.update(encs)
            self._apply_encoders()

    def activate(self):
        num = self._num_paths or 6
        # Combined subscription so base_panel's toolhead-temp display
        # keeps updating during autoloader-triggered tool changes.
        objs = _sasub.build_subscription(
            self._screen, num_paths=num, include_encoders=True)
        self._screen._ws.klippy.object_subscription({"objects": objs})
        _sasub.install_global_popup_watcher(self._screen)

        # Seed the marker straight away rather than waiting for the first
        # toolchanger update, which may not arrive until something moves.
        try:
            self._apply_toolchanger(self._printer.data.get("toolchanger") or {})
        except Exception:
            logging.exception("sa_main: could not seed toolchanger state")

        sa = self._query_sa()
        if sa:
            self._last_sa = dict(sa)
            self._entry_prev = list(sa.get("entry_filament", []))
            self._apply_sa(self._last_sa)
            encs = self._query_encoders(sa.get("num_paths", 6))
            self._enc_distances.update(encs)
            self._apply_encoders()
        else:
            self._refresh()

    def process_update(self, action, data):
        if action != "notify_status_update":
            return

        if isinstance(data, dict):
            if "toolchanger" in data:
                self._apply_toolchanger(data["toolchanger"])
            # A temperature tick carries no autoloader key, so the table would
            # not otherwise repaint; refresh just the temperature cells.
            if any(k == "extruder" or k.startswith("extruder")
                   for k in data.keys()):
                self._apply_temps()

        updated_enc = False
        for key, val in data.items():
            if key.startswith("sa_encoder "):
                try:
                    idx = int(key.split()[-1])
                    self._enc_distances[idx] = float(val.get('distance', 0.0))
                    updated_enc = True
                except (ValueError, AttributeError):
                    pass

        sa = data.get("autoloader")
        if sa is None and not updated_enc:
            return

        if sa is not None:
            self._last_sa.update(sa)
            # Track entry rising-edges for stats only — the actual popup
            # trigger is handled by the global watcher in sa_subscription.py
            # so it works from any KS panel, not only sa_main.
            self._entry_prev = list(self._last_sa.get("entry_filament", []))
            self._last_cal_state = self._last_sa.get("cal_state", "")
            # Popup logic moved to sa_subscription.install_global_popup_watcher.
            # That watcher monkey-patches screen.process_update so it fires
            # regardless of which panel is currently active, AND it checks
            # _dismissed_at_cal_state so an explicit user-Park doesn't
            # immediately reopen the popup before Klipper finishes processing
            # SA_RESPOND. Keeping the panel-local logic here would cause the
            # two watchers to race during the dismiss window.

        GLib.idle_add(self._redraw)

    def _redraw(self):
        self._apply_sa(self._last_sa)
        self._apply_encoders()
        return False

    def _apply_temps(self):
        """Repaint only the temperature cells.

        Temperature updates arrive far more often than autoloader state, and
        rebuilding every cell for each one would be wasteful.
        """
        for i in range(self._num_paths):
            lbl = self.labels.get('row_%d_temp' % i)
            if lbl is None:
                continue
            t = self._extruder_temp(i)
            if t is None:
                lbl.set_markup('<span font_size="large" foreground="%s">'
                               '\u2014</span>' % _TEMP_COLD_COL)
            else:
                col = _TEMP_HOT_COL if t >= _TEMP_HOT_C else _TEMP_COLD_COL
                weight = ' weight="bold"' if t >= _TEMP_HOT_C else ''
                lbl.set_markup(
                    '<span font_size="large" foreground="%s"%s>%.0f\u00b0</span>'
                    % (col, weight, t))

    def _apply_encoders(self):
        for i in range(self._num_paths):
            lbl = self.labels.get('row_%d_encoder' % i)
            if lbl is None:
                continue
            dist = self._enc_distances.get(i, None)
            if dist is None:
                lbl.set_markup(
                    '<span foreground="%s" font_size="small">\u2014</span>' % _ENC_IDLE)
            elif abs(dist) > 0.1:
                lbl.set_markup(
                    '<span foreground="%s" font_size="small"><b>%.1fmm</b></span>'
                    % (_ENC_ACTIVE, dist))
            else:
                lbl.set_markup(
                    '<span foreground="%s" font_size="small">0.0</span>' % _ENC_IDLE)

    def _apply_sa(self, sa):
        num = sa.get("num_paths", 0)
        if num != self._num_paths:
            self._build_rows(num)
            objs = _sasub.build_subscription(
                self._screen, num_paths=num, include_encoders=True)
            self._screen._ws.klippy.object_subscription({"objects": objs})

        states    = sa.get("path_states",      [])
        entry     = sa.get("entry_filament",    [])
        toolhead  = sa.get("toolhead_filament", [])
        extruder  = sa.get("extruder_filament", [])
        materials = sa.get("path_materials",    [])
        colors    = sa.get("path_color_names",  [])
        hexes     = sa.get("path_color_hexes",  [])

        grey_rgba = Gdk.RGBA()
        Gdk.RGBA.parse(grey_rgba, 'rgba(97,97,97,1)')

        for i in range(self._num_paths):
            state = _effective_state(i, states, entry, toolhead, extruder)

            state_lbl = self.labels.get('row_%d_state' % i)
            if state_lbl:
                markup, color_hex = _STATE_MARKUP.get(state, ('? UNKNOWN', '#616161'))
                state_lbl.set_markup(
                    '<span font_size="large" foreground="%s">%s</span>'
                    % (color_hex, markup))

            # Hotend temperature for this path. Amber once the hotend is
            # above the heater_fan threshold, dim below -- the same signal
            # sa_led_animator uses for the amber nozzle warning.
            temp_lbl = self.labels.get('row_%d_temp' % i)
            if temp_lbl:
                t = self._extruder_temp(i)
                if t is None:
                    temp_lbl.set_markup(
                        '<span font_size="large" foreground="%s">\u2014</span>'
                        % _TEMP_COLD_COL)
                else:
                    col = _TEMP_HOT_COL if t >= _TEMP_HOT_C else _TEMP_COLD_COL
                    weight = ' weight="bold"' if t >= _TEMP_HOT_C else ''
                    temp_lbl.set_markup(
                        '<span font_size="large" foreground="%s"%s>%.0f\u00b0</span>'
                        % (col, weight, t))

            def _dot(val):
                return ('<span foreground="%s">%s</span>'
                        % (_DOT_ON if val else _DOT_OFF,
                           "\u25cf" if val else "\u25cb"))

            sens_lbl = self.labels.get('row_%d_sensors' % i)
            if sens_lbl:
                # Narrow layout: one cell, same three dots, same order.
                sens_lbl.set_markup(
                    '<span font_size="large">%s %s %s</span>'
                    % (_dot(entry[i] if i < len(entry) else False),
                       _dot(extruder[i] if i < len(extruder) else False),
                       _dot(toolhead[i] if i < len(toolhead) else False)))

            for sensor_key, arr in [('entry', entry), ('extruder', extruder), ('toolhead', toolhead)]:
                dot = self.labels.get('row_%d_%s' % (i, sensor_key))
                if dot:
                    val = arr[i] if i < len(arr) else False
                    dot.set_markup('<span font_size="large">%s</span>' % _dot(val))

            mat_lbl = self.labels.get('row_%d_material' % i)
            if mat_lbl:
                mat = materials[i] if i < len(materials) and materials[i] else "---"
                mat_lbl.set_markup('<span font_size="large">%s</span>' % mat)

            # On the narrow layout this swatch is the only colour shown, so it
            # carries what the folded-away COLOUR column would have said.
            mat_sw = self.labels.get('row_%d_mat_swatch' % i)
            if mat_sw:
                hx = hexes[i] if i < len(hexes) else ''
                if hx:
                    mat_sw.override_color(Gtk.StateType.NORMAL,
                                          _rgba_from_hex(hx))
                    mat_sw.set_markup(
                        '<span font_size="large">%s</span>' % COLOR_SWATCH)
                else:
                    mat_sw.override_color(Gtk.StateType.NORMAL, grey_rgba)
                    mat_sw.set_markup(
                        '<span font_size="large">%s</span>' % EMPTY_SWATCH)

            swatch    = self.labels.get('row_%d_swatch' % i)
            color_lbl = self.labels.get('row_%d_color'  % i)
            hex_c  = hexes[i]  if i < len(hexes)  else ''
            name_c = colors[i] if i < len(colors) and colors[i] else "---"

            if swatch:
                if hex_c:
                    rgba = _rgba_from_hex(hex_c)
                    swatch.override_color(Gtk.StateType.NORMAL, rgba)
                    swatch.set_markup(
                        '<span font_size="large">%s</span>' % COLOR_SWATCH)
                else:
                    swatch.override_color(Gtk.StateType.NORMAL, grey_rgba)
                    swatch.set_markup(
                        '<span font_size="large">%s</span>' % EMPTY_SWATCH)
            if color_lbl:
                color_lbl.set_markup('<span font_size="large">%s</span>' % name_c)

        return False
