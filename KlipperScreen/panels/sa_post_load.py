import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk, GLib
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

logger = logging.getLogger('klipperscreen.sa_post_load')

_GREEN  = '#388E3C'
_ORANGE = '#E65100'
_GREY   = '#37474F'
_RED    = '#B71C1C'


class Panel(ScreenPanel):
    """Post-load / post-unload action panel.

    Appears automatically when cal_state becomes 'load_purge' or 'unload_done'.
    Sends SA_RESPOND VALUE=<action> for each button press.
    """

    def __init__(self, screen, title):
        super().__init__(screen, title or "Autoloader Action")
        _sbs.apply(min_height=self._touch())

        self._active    = False
        self._cal_state = ''
        self._cal_path  = -1
        self._num_paths = 6
        self._sel_path  = None     # nothing acts until a head is picked
        self._path_btns = {}
        self._last_sa   = {}

        self._build_ui()

    # ── UI construction ───────────────────────────────────────────────────────

    # -- Sizing derived from the framework -------------------------------------

    def _touch(self):
        return int(max(44.0, self._gtk.font_size * 2.4))

    def _gap(self):
        return int(max(4.0, self._gtk.font_size * 0.34))

    def _pad_bottom(self):
        return int(self._gap() * 2.5)

    # -- UI construction -------------------------------------------------------

    def _build_ui(self):
        """Pick-then-confirm flow.

        Replaces the two parallel LOAD PATH / UNLOAD PATH rows. Those rows had
        to shrink to 38 px to both fit -- below a reliable finger target, and
        the code said so outright -- and either could be triggered by a single
        stray tap on a panel that appears unprompted right after a load.

        Now: immediate actions on top, a toggle choosing the verb, one grid of
        heads, and a confirm that names what it is about to do. Two taps
        minimum before anything moves.
        """
        gap = self._gap()
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=gap)
        outer.set_margin_top(gap)
        outer.set_margin_start(gap)
        outer.set_margin_end(gap)
        outer.set_margin_bottom(self._pad_bottom())

        self._hdr = Gtk.Label(halign=Gtk.Align.CENTER)
        self._hdr.set_markup(
            '<span font_size="large" foreground="%s"><b>Autoloader Action</b></span>'
            % _GREEN)
        outer.pack_start(self._hdr, False, False, 0)

        self._sub = Gtk.Label(halign=Gtk.Align.CENTER)
        outer.pack_start(self._sub, False, False, 0)

        outer.pack_start(Gtk.Separator(), False, False, 0)

        # -- The heads, directly under the title. Mike's layout call: "id
        # rather move the tool heads up to below the title and put the 6
        # buttons at the bottom, with the active toolhead as the one selected
        # by default then the all the buttons are active at face value".
        #
        # The old shape was select-a-head, pick a verb with a toggle, then
        # press a confirm that named the pair. Three taps, and the state lived
        # in two widgets that had to agree. Now the head is a noun and every
        # button is a verb that acts on it immediately.
        # No scroller. Six heads in two rows of three fit a 480px panel once
        # the tile puts its icon BESIDE the T-number instead of above it --
        # Mike: "make it (toolhead icon) T3, so they at next to each other
        # rather then stacked ... should give us the height we need to not
        # need a scroll window". A scrollbar on a six-item grid is a control
        # that exists only because the items were the wrong shape.
        self._path_grid = Gtk.Grid(row_spacing=gap, column_spacing=gap,
                                   row_homogeneous=True,
                                   column_homogeneous=True)
        outer.pack_start(self._path_grid, True, True, 0)

        # -- Six buttons, two rows of three, locked at the bottom.
        #    PURGE and LOAD SAME are mutually exclusive by cal_state and share
        #    the first slot, as they always did.
        row1 = Gtk.Box(spacing=gap)
        self._more_btn = self._make_action_btn(
            "↺  PURGE 60mm", _GREEN, self._do_more)
        self._load_same_btn = self._make_action_btn(
            "▶  LOAD SAME", _GREEN, self._do_load_same)
        self._park_btn = self._make_action_btn("Ⓟ  PARK", None, self._do_park)
        self._clean_btn = self._make_action_btn(
            "✦  CLEAN NOZZLE", None, self._do_clean)
        self._more_btn.set_no_show_all(True)
        self._load_same_btn.set_no_show_all(True)
        for b in (self._more_btn, self._load_same_btn, self._park_btn,
                  self._clean_btn):
            b.set_size_request(-1, int(self._touch() * 1.35))
            row1.pack_start(b, True, True, 0)
        outer.pack_start(row1, False, False, 0)

        row2 = Gtk.Box(spacing=gap)
        self._load_btn   = _sbs.make("▶  LOAD",   "sa-btn")
        self._unload_btn = _sbs.make("◀  UNLOAD", "sa-btn")
        self._exit_btn   = self._make_action_btn("✕  EXIT", _RED,
                                                 self._do_exit)
        self._load_btn.connect("clicked",   self._do_verb, 'load')
        self._unload_btn.connect("clicked", self._do_verb, 'unload')
        for b in (self._load_btn, self._unload_btn, self._exit_btn):
            b.set_size_request(-1, int(self._touch() * 1.35))
            row2.pack_start(b, True, True, 0)
        outer.pack_start(row2, False, False, 0)

        self.content.pack_start(outer, True, True, 0)

    def _make_action_btn(self, label, color, callback):
        if color == _GREEN:
            btn = _sbs.make(label, "sa-btn")
        elif color == _RED:
            btn = _sbs.make(label, "sa-btn-warn")
        else:
            btn = _sbs.make(label, "sa-btn-alt")
        btn.connect("clicked", callback)
        return btn

    # -- Mode and selection ----------------------------------------------------

    def _select_path(self, widget, path):
        self._sel_path = path
        for i, btn in self._path_btns.items():
            ctx = btn.get_style_context()
            if i == path:
                ctx.add_class('path-selected')
            else:
                ctx.remove_class('path-selected')
        self._update_actions()

    def _path_state(self, path):
        states = (self._last_sa or {}).get("path_states", [])
        if path is None or path >= len(states):
            return 'unknown'
        return states[path] or 'unknown'

    def _update_actions(self):
        """LOAD and UNLOAD, decided by what the selected head actually is.

        There is no confirm step any more, so these two ARE the commitment --
        which makes it matter that the impossible one cannot be pressed. They
        are mutually exclusive by construction (a head is loaded or it is
        not), so exactly one is armed, and `sa-btn-armed` plus the :disabled
        opacity rule is what makes the pair read as one toggle instead of two
        live buttons.
        """
        state      = self._path_state(self._sel_path)
        has_path   = self._sel_path is not None
        can_load   = bool(has_path and state != 'loaded')
        can_unload = bool(has_path and state != 'empty')

        self._load_btn.set_sensitive(can_load)
        self._unload_btn.set_sensitive(can_unload)
        for btn, armed in ((self._load_btn, can_load),
                           (self._unload_btn, can_unload)):
            ctx = btn.get_style_context()
            if armed and not (can_load and can_unload):
                ctx.add_class('sa-btn-armed')
            else:
                ctx.remove_class('sa-btn-armed')

    def _do_verb(self, widget, verb):
        if self._sel_path is None:
            return
        self._do_path_action(None, verb, self._sel_path)

    def _do_clean(self, widget=None):
        # A direct macro, not a calibration response like the others.
        self._gcode("SA_CLEAN_NOZZLE")

    def _build_path_grids(self, num):
        """Rebuild the head grid for *num* toolheads.

        Three wide, expanding into whatever the page has left. Tiles carry the
        material and colour already on each head -- which the plain T-buttons
        never showed, and which is exactly what you are deciding against when
        changing a colour.
        """
        for child in self._path_grid.get_children():
            self._path_grid.remove(child)
        self._path_btns = {}

        sa        = self._last_sa or {}
        materials = sa.get("path_materials",   [])
        colors    = sa.get("path_color_names", [])

        for i in range(num):
            btn = Gtk.Button()
            btn.get_style_context().add_class("sa-btn-alt")
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
            box.set_valign(Gtk.Align.CENTER)

            # Icon and number share one line. Stacked, they cost a tile the
            # height that made the grid scroll.
            head = Gtk.Box(spacing=6, halign=Gtk.Align.CENTER)
            try:
                ic = int(self._gtk.font_size * 1.6)
                head.pack_start(self._gtk.Image("toolhead", ic, ic),
                                False, False, 0)
            except Exception:
                pass
            t = Gtk.Label()
            t.set_markup('<b><span font_size="large">T%d</span></b>' % i)
            head.pack_start(t, False, False, 0)
            box.pack_start(head, False, False, 0)

            mat  = materials[i] if i < len(materials) and materials[i] else ''
            name = colors[i]    if i < len(colors)    and colors[i]    else ''
            detail = ' \u00b7 '.join([x for x in (mat, name) if x]) or 'empty'
            d = Gtk.Label(ellipsize=3, max_width_chars=16)
            d.set_markup('<span font_size="small" foreground="#BDBDBD">%s</span>'
                         % GLib.markup_escape_text(detail))
            box.pack_start(d, False, False, 0)

            btn.add(box)
            btn.set_vexpand(True)
            btn.connect("clicked", self._select_path, i)
            self._path_grid.attach(btn, i % 3, i // 3, 1, 1)
            self._path_btns[i] = btn

        self._path_grid.show_all()
        self._update_actions()

    # ── State update ──────────────────────────────────────────────────────────

    def _apply_state(self, cal_state, cal_path, num_paths):
        self._cal_state = cal_state
        self._cal_path  = cal_path
        self._num_paths = num_paths or 6

        # The head this panel is ABOUT is the one to act on, so it arrives
        # selected rather than asking for a tap that has only one sensible
        # answer. Mike: "with the active toolhead as the one selected by
        # default".
        if cal_path is not None and 0 <= cal_path < self._num_paths:
            self._sel_path = cal_path

        self._build_path_grids(self._num_paths)
        if self._sel_path is not None and self._sel_path in self._path_btns:
            self._path_btns[self._sel_path].get_style_context().add_class(
                'path-selected')
        self._update_actions()

        if cal_state == 'load_purge':
            self._hdr.set_markup(
                '<span font_size="large" foreground="%s"><b>\u2713 LOAD COMPLETE \u00b7 T%d</b></span>'
                % (_GREEN, cal_path))
            self._sub.set_markup(
                '<span foreground="#BDBDBD">Filament purging at nozzle</span>')
            self._more_btn.set_visible(True)
            self._load_same_btn.set_visible(False)
        elif cal_state == 'unload_done':
            self._hdr.set_markup(
                '<span font_size="large" foreground="%s"><b>\u2713 UNLOAD COMPLETE \u00b7 T%d</b></span>'
                % (_ORANGE, cal_path))
            self._sub.set_markup(
                '<span foreground="#BDBDBD">What next?</span>')
            self._more_btn.set_visible(False)
            self._load_same_btn.set_visible(True)
        else:
            self._hdr.set_markup(
                '<span font_size="large"><b>Autoloader Action</b></span>')
            self._sub.set_text('')
            self._more_btn.set_visible(True)
            self._load_same_btn.set_visible(False)

    # ── Button handlers ───────────────────────────────────────────────────────

    def _gcode(self, cmd):
        self._screen._ws.klippy.gcode_script(cmd)

    def _respond(self, value):
        self._gcode("SA_RESPOND VALUE=%s" % value)

    def _close(self):
        # Tell the global popup watcher this dismiss is intentional, so the
        # next status update with the same cal_state (Klipper hasn't
        # processed our SA_RESPOND yet — async) doesn't re-open the popup.
        # The flag clears automatically once cal_state actually transitions.
        try:
            _sasub.mark_user_dismissed(self._cal_state)
        except Exception:
            pass

        # Walk back through the autoloader popup chain instead of pushing
        # sa_main onto the stack. show_panel() would leave sa_post_load and
        # sa_load_unload in the back stack, so the user's next "back" tap
        # would re-open the popup. Pop everything autoloader-popup-related
        # so back lands wherever the user was BEFORE the popup chain.
        s = self._screen
        try:
            s._menu_go_back()  # pop self (sa_post_load)
            popup_panels = ('sa_load_unload', 'sa_post_load')
            while s._cur_panels and s._cur_panels[-1] in popup_panels:
                s._menu_go_back()
        except Exception as e:
            logger.warning("sa_post_load: _close fallback to sa_main: %s", e)
            s.show_panel('sa_main', 'Autoloader Status')

    def _do_more(self, widget=None):
        self._respond("more")
        # Stay on panel — user may want more purge again

    def _do_park(self, widget=None):
        self._respond("park")
        self._close()

    def _do_exit(self, widget=None):
        self._respond("exit")
        self._close()

    def _do_load_same(self, widget=None):
        self._respond("load")
        self._close()

    def _do_path_action(self, widget, action, path):
        self._respond("%s:%d" % (action, path))
        self._close()

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def _query_sa(self):
        try:
            resp = self._screen.apiclient.send_request(
                "printer/objects/query?autoloader")
            if resp and 'status' in resp:
                return resp['status'].get('autoloader', {})
        except Exception as e:
            logger.warning("sa_post_load: query failed: %s", e)
        return {}

    def activate(self):
        self._active = True
        self._screen._ws.klippy.object_subscription(
            {"objects": _sasub.build_subscription(self._screen)})
        _sasub.install_global_popup_watcher(self._screen)
        sa = self._query_sa()
        # Held so the head tiles can show what is already on each path.
        self._last_sa = dict(sa) if sa else {}
        self._apply_state(
            sa.get("cal_state", ""),
            sa.get("cal_path",  -1),
            sa.get("num_paths",  6))

    def deactivate(self):
        self._active = False

    def process_update(self, action, data):
        if action != "notify_status_update":
            return
        sa = data.get("autoloader")
        if sa is None:
            return

        cal = sa.get("cal_state")
        if cal is not None:
            path = sa.get("cal_path", self._cal_path)
            num  = sa.get("num_paths", self._num_paths)
            GLib.idle_add(self._apply_state, cal, path, num)

            # Auto-close if backend cleared the state while we're visible
            if cal == '' and self._active:
                GLib.idle_add(self._close)
