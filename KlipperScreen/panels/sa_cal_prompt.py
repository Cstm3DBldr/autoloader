import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib
import logging
import sys, os

_panels_dir = os.path.dirname(os.path.abspath(__file__))
_ks_root    = os.path.dirname(_panels_dir)
for _p in (_ks_root, _panels_dir):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import sa_button_style as _sbs
import sa_subscription as _sasub
from ks_includes.screen_panel import ScreenPanel

logger = logging.getLogger('klipperscreen.sa_cal_prompt')

_GREEN  = '#388E3C'
_RED    = '#B71C1C'
_BLUE   = '#1565C0'
_GREY   = '#37474F'


def _input_type(state):
    """Map cal_state to the kind of input widget needed."""
    if state in ('sel_confirm', 'drv_save') or \
       state.startswith('enc_save_') or state.startswith('enc_mark_'):
        return 'yesno'
    if state == 'drv_mark':
        return 'ready'
    if state == 'drv_path':
        return 'numpad_int'
    if state in ('drv_meas',) or \
       state.startswith('enc_meas_') or state.startswith('bow_est_'):
        return 'numpad_float'
    return 'yesno'


def _phase_label(cal_state):
    """Short uppercase phase name from a cal_state value, shown above the
    prompt as a section header. Driven by the cal_state prefix that the
    autoloader Klipper extra emits."""
    if not cal_state:
        return "CALIBRATION"
    s = cal_state.lower()
    if s.startswith('sel_'):  return "SELECTOR CALIBRATION"
    if s.startswith('drv_'):  return "DRIVE MOTOR CALIBRATION"
    if s.startswith('enc_'):  return "ENCODER CALIBRATION"
    if s.startswith('bow_'):  return "BOWDEN CALIBRATION"
    return cal_state.upper()


class Panel(ScreenPanel):
    """Calibration prompt panel — shows backend prompt + appropriate input."""

    def __init__(self, screen, title):
        super().__init__(screen, title or "SA Calibration")
        _sbs.apply()

        self._active    = False
        self._cal_state = ''
        self._entry_val = ''

        # Claim exactly the framework's content budget and stop expanding.
        # In landscape the action bar spans both rows of base_panel's grid,
        # so it negotiates height with the content row; an exact request
        # settles that on the first allocation pass rather than letting the
        # two fight over the leftover.
        self.content.set_size_request(-1, self._gtk.content_height)
        self.content.set_vexpand(False)

        self._build_ui()

    # -- Sizing derived from the framework, never hard-coded --------------------

    def _touch_h(self):
        """Minimum comfortable finger target height, in px.

        Derived from the framework font size so it tracks resolution and the
        user's font_size preference, with an absolute floor for tiny screens.
        """
        return int(max(44.0, self._gtk.font_size * 2.6))

    def _pt(self, mult):
        """Pango point size as a multiple of the framework font size."""
        return max(7, int(round(self._gtk.font_size * mult)))

    # ── UI construction ────────────────────────────────────────────────────────

    def _build_ui(self):
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, margin=8)

        # Phase label — small dimmed line above the prompt indicating which
        # calibration is running ("SELECTOR · sel_confirm" etc.). Updated by
        # _apply_state() from the cal_state value.
        self._phase_lbl = Gtk.Label(halign=Gtk.Align.CENTER)
        # Pinned to a point size derived from the framework font -- never
        # em-based ("x-small") and never letter_spacing. Both are measured
        # from font metrics that are unstable on the first realize pass, and
        # each added a few px per label: the same failure that pushed
        # sa_macros over budget and clipped the power icon off-screen.
        self._phase_lbl.set_markup(
            '<span font="%d" foreground="#9E9E9E">CALIBRATION</span>'
            % self._pt(0.62))
        outer.pack_start(self._phase_lbl, False, False, 0)

        # Prompt text — large, centered, the focal point of the panel.
        self._prompt_lbl = Gtk.Label()
        self._prompt_lbl.set_line_wrap(True)
        self._prompt_lbl.set_halign(Gtk.Align.CENTER)
        self._prompt_lbl.set_justify(Gtk.Justification.CENTER)
        self._prompt_lbl.set_markup(
            '<span font="%d" weight="bold">Waiting for calibration…</span>'
            % self._pt(1.25))
        outer.pack_start(self._prompt_lbl, False, False, 4)

        # Divider removed — phase label + bold prompt give enough separation
        # without the visual weight of a Gtk.Separator.

        # Input area — swapped based on input type
        self._input_stack = Gtk.Stack()
        self._input_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self._input_stack.set_transition_duration(100)

        self._input_stack.add_named(self._build_yesno(),       "yesno")
        self._input_stack.add_named(self._build_ready(),       "ready")
        self._input_stack.add_named(self._build_numpad(False), "numpad_int")
        self._input_stack.add_named(self._build_numpad(True),  "numpad_float")

        outer.pack_start(self._input_stack, True, True, 0)

        # ABORT — always at bottom
        abort_btn = _sbs.make("\u26d4  ABORT", "sa-btn-warn")
        abort_btn.set_size_request(-1, self._touch_h())
        abort_btn.connect("clicked", self._do_abort)
        outer.pack_start(abort_btn, False, False, 0)

        self.content.pack_start(outer, True, True, 0)

    def _build_yesno(self):
        box = Gtk.Box(spacing=12, margin_top=12)
        yes = _sbs.make("\u2714  YES", "sa-btn")
        no  = _sbs.make("\u2716  NO",  "sa-btn-alt")
        for _b in (yes, no):
            _b.set_size_request(-1, self._touch_h())
            _b.set_vexpand(True)
        yes.connect("clicked", self._respond_fixed, "yes")
        no.connect("clicked",  self._respond_fixed, "no")
        box.pack_start(yes, True, True, 0)
        box.pack_start(no,  True, True, 0)
        return box

    def _build_ready(self):
        box = Gtk.Box(spacing=12, margin_top=12)
        rdy  = _sbs.make("\u25b6  READY",    "sa-btn")
        retry = _sbs.make("\u21ba  NOT YET", "sa-btn-alt")
        for _b in (rdy, retry):
            _b.set_size_request(-1, self._touch_h())
            _b.set_vexpand(True)
        rdy.connect("clicked",   self._respond_fixed, "yes")
        retry.connect("clicked", self._respond_fixed, "no")
        box.pack_start(rdy,   True, True, 0)
        box.pack_start(retry, True, True, 0)
        return box

    def _build_numpad(self, with_decimal):
        """Numpad as ONE homogeneous 3x6 grid, so it divides the space it is
        given instead of demanding a fixed height.

        Rows: display / 7 8 9 / 4 5 6 / 1 2 3 / . 0 back / SEND.

        The previous version stacked fixed heights -- 48 for the display,
        4 x 52 for the pad, 56 for SEND, plus gaps -- for a 336 px minimum.
        That overflowed a 480x320 screen (296 px of content) by 40 px with
        nothing above it, and left only 108 px here for the prompt text.
        Six homogeneous rows come to 49 px each on that screen and 74 px
        here, both above a comfortable finger target, and they follow the
        display rather than fighting it.
        """
        key = "float" if with_decimal else "int"

        grid = Gtk.Grid(row_spacing=4, column_spacing=4,
                        row_homogeneous=True, column_homogeneous=True,
                        hexpand=True, vexpand=True)

        # Row 0 — entry display, full width
        disp = Gtk.Entry()
        disp.set_editable(False)
        disp.set_alignment(1.0)
        disp.set_hexpand(True)
        disp.set_vexpand(True)
        disp.get_style_context().add_class("sa-btn-alt")
        setattr(self, "_disp_%s" % key, disp)
        grid.attach(disp, 0, 0, 3, 1)

        # Rows 1-3 — digits
        digits = [
            ('7', 1, 0), ('8', 1, 1), ('9', 1, 2),
            ('4', 2, 0), ('5', 2, 1), ('6', 2, 2),
            ('1', 3, 0), ('2', 3, 1), ('3', 3, 2),
        ]
        for lbl, row, col in digits:
            btn = _sbs.make(lbl, "sa-btn-alt")
            btn.set_vexpand(True)
            btn.connect("clicked", self._numpad_digit, key, lbl)
            grid.attach(btn, col, row, 1, 1)

        # Row 4 — [. or blank] [0] [backspace]
        if with_decimal:
            dot_btn = _sbs.make(".", "sa-btn-alt")
            dot_btn.set_vexpand(True)
            dot_btn.connect("clicked", self._numpad_digit, key, ".")
            grid.attach(dot_btn, 0, 4, 1, 1)
        else:
            grid.attach(Gtk.Label(), 0, 4, 1, 1)

        zero_btn = _sbs.make("0", "sa-btn-alt")
        zero_btn.set_vexpand(True)
        zero_btn.connect("clicked", self._numpad_digit, key, "0")
        grid.attach(zero_btn, 1, 4, 1, 1)

        back_btn = _sbs.make("⌫", "sa-btn-alt")
        back_btn.set_vexpand(True)
        back_btn.connect("clicked", self._numpad_backspace, key)
        grid.attach(back_btn, 2, 4, 1, 1)

        # Row 5 — SEND, full width
        send_btn = _sbs.make("✓  SEND", "sa-btn")
        send_btn.set_vexpand(True)
        send_btn.connect("clicked", self._numpad_send, key)
        grid.attach(send_btn, 0, 5, 3, 1)

        return grid

    # ── Numpad logic ───────────────────────────────────────────────────────────

    def _get_disp(self, key):
        return getattr(self, "_disp_%s" % key, None)

    def _numpad_digit(self, widget, key, digit):
        disp = self._get_disp(key)
        if disp is None:
            return
        cur = disp.get_text()
        if digit == '.' and '.' in cur:
            return
        disp.set_text(cur + digit)

    def _numpad_backspace(self, widget, key):
        disp = self._get_disp(key)
        if disp is None:
            return
        cur = disp.get_text()
        disp.set_text(cur[:-1])

    def _numpad_send(self, widget, key):
        disp = self._get_disp(key)
        if disp is None:
            return
        val = disp.get_text().strip()
        if not val:
            return
        disp.set_text('')
        self._respond(val)

    # ── Button handlers ────────────────────────────────────────────────────────

    def _gcode(self, cmd):
        self._screen._ws.klippy.gcode_script(cmd)

    def _respond(self, value):
        self._gcode("SA_RESPOND VALUE=%s" % value)

    def _respond_fixed(self, widget, value):
        self._respond(value)

    def _do_abort(self, widget=None):
        self._respond("abort")
        self._close()

    def _close(self):
        self._screen.show_panel('sa_main', 'SA Status')

    # ── State update ───────────────────────────────────────────────────────────

    def _apply_state(self, cal_state, cal_prompt):
        self._cal_state = cal_state

        if cal_state:
            from xml.sax.saxutils import escape as _xml_escape
            # Phase label — derive a short uppercase category name from the
            # cal_state prefix so the user knows which calibration is running.
            phase = _phase_label(cal_state)
            self._phase_lbl.set_markup(
                '<span font_size="x-small" foreground="#9E9E9E" '
                'letter_spacing="2000">%s</span>' % _xml_escape(phase))
            display_text = cal_prompt if cal_prompt else cal_state
            self._prompt_lbl.set_markup(
                '<span font_size="x-large" weight="bold">%s</span>'
                % _xml_escape(display_text))
            itype = _input_type(cal_state)
            self._input_stack.set_visible_child_name(itype)
            # Clear numpad display on state change
            for key in ('int', 'float'):
                disp = self._get_disp(key)
                if disp:
                    disp.set_text('')

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    def _query_sa(self):
        try:
            resp = self._screen.apiclient.send_request(
                "printer/objects/query?autoloader")
            if resp and 'status' in resp:
                return resp['status'].get('autoloader', {})
        except Exception as e:
            logger.warning("sa_cal_prompt: query failed: %s", e)
        return {}

    def activate(self):
        self._active = True
        self._screen._ws.klippy.object_subscription(
            {"objects": _sasub.build_subscription(self._screen)})
        _sasub.install_global_popup_watcher(self._screen)
        sa = self._query_sa()
        self._apply_state(
            sa.get("cal_state",  ""),
            sa.get("cal_prompt", ""))

    def deactivate(self):
        self._active = False

    def process_update(self, action, data):
        if action != "notify_status_update":
            return
        sa = data.get("autoloader")
        if sa is None:
            return

        cal   = sa.get("cal_state")
        if cal is None:
            return

        prompt = sa.get("cal_prompt", "")
        GLib.idle_add(self._apply_state, cal, prompt)

        # State cleared → return to main; post-load/unload → let sa_main handle it
        if (cal == '' or cal in ('load_purge', 'unload_done')) and self._active:
            GLib.idle_add(self._close)
