import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib
import logging
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import sa_button_style as _sbs
from ks_includes.screen_panel import ScreenPanel

logger = logging.getLogger('klipperscreen.sa_calibration_guide')

_GREY      = "#616161"
_GREEN     = "#388E3C"
_AMBER     = "#F9A825"


class Panel(ScreenPanel):
    """Step-by-step calibration guide — one full page per step."""

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
        super().__init__(screen, title or "Autoloader Calibration")
        _sbs.apply(min_height=self._touch())

        self._num_paths   = 6
        self._last_sa     = {}
        self._step        = 0
        # How many pages there are is the printer's answer, not ours. It used
        # to be a constant here, which is how this screen came to show nine
        # steps of an eleven-step chain.
        self._n_steps     = 0

        # One view. The path picker it used to swap to is gone: the
        # per-path steps arrive with a button per path already.
        self._stack = Gtk.Stack()
        self._stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
        self._stack.set_transition_duration(150)
        # See sa_macros.py for the rationale — Gtk.Stack defaults to sizing
        # to its largest child page, which stretches base_panel's left
        # action bar and clips the bottom power icon.
        self._stack.set_vhomogeneous(False)
        self._stack.set_hhomogeneous(False)

        self._stack.add_named(self._build_pages_view(), "pages")

        self.content.pack_start(self._stack, True, True, 0)

    # ── Pages view ────────────────────────────────────────────────────────────

    def _build_pages_view(self):
        wrapper = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        # Inner stack — one ScrolledWindow per step
        self._page_stack = Gtk.Stack()
        self._page_stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
        self._page_stack.set_transition_duration(200)
        # Same homogeneous fix as the outer Stack — different steps have
        # different content heights, so let GTK size to the visible step
        # rather than the tallest one.
        self._page_stack.set_vhomogeneous(False)
        self._page_stack.set_hhomogeneous(False)

        # Built on demand rather than up front: the count comes from the
        # printer and this runs before it has answered.
        self._step_boxes = []

        wrapper.pack_start(self._page_stack, True, True, 0)

        # Nav bar: [◀ Back]  Step N of 7  [Next ▶]
        nav = Gtk.Box(spacing=6, margin_start=6, margin_end=6,
                      margin_top=4, margin_bottom=4)

        # Prev/Next buttons trimmed 220 → 150 so the center label has more
        # room for the progress-dots strip without forcing the nav box
        # natural width past the screen and clipping content in the page
        # above (was happening on 800×480 displays).
        self._prev_btn = _sbs.make("◀  Back", "sa-btn")
        # Font-derived, not 150 px: on a 480 px-wide screen two fixed
        # 150 px buttons claim 300 of it, leaving under 130 for the action
        # button between them.
        self._prev_btn.set_size_request(int(self._gtk.font_size * 6.2), -1)
        self._prev_btn.connect("clicked", self._go_prev)

        self._step_lbl = Gtk.Label()
        self._step_lbl.set_hexpand(True)
        self._step_lbl.set_halign(Gtk.Align.CENTER)
        # Belt-and-suspenders: even with smaller dots, ellipsize end so an
        # unexpectedly long step name (or future locale) can't grow the
        # label past its allocation.
        self._step_lbl.set_ellipsize(3)
        self._step_lbl.set_max_width_chars(28)

        self._next_btn = _sbs.make("Next  ▶", "sa-btn")
        self._next_btn.set_size_request(int(self._gtk.font_size * 6.2), -1)
        self._next_btn.connect("clicked", self._go_next)

        nav.pack_start(self._prev_btn, False, False, 0)
        nav.pack_start(self._step_lbl, True,  True,  0)
        nav.pack_start(self._next_btn, False, False, 0)
        wrapper.pack_start(nav, False, False, 0)

        return wrapper

    def _ensure_pages(self, n):
        """Have at least *n* page boxes. Grows; never shrinks, because a box
        that is not the visible child costs nothing and removing one mid-flight
        is a good way to drop the page being looked at."""
        while len(self._step_boxes) < n:
            i = len(self._step_boxes)
            scroll = Gtk.ScrolledWindow()
            scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.ALWAYS)
            scroll.set_overlay_scrolling(False)
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10,
                          margin_top=12, margin_start=12, margin_end=12,
                          margin_bottom=20)
            scroll.add(box)
            scroll.show_all()
            self._step_boxes.append(box)
            self._page_stack.add_named(scroll, "step%d" % i)

    def _update_nav(self):
        # Step name now lives only in the page header (not in the dots
        # markup) — keeps the nav strip narrow enough to fit alongside
        # the prev/next buttons without forcing horizontal overflow.
        self._step_lbl.set_markup(
            _sbs.progress_dots(self._step, max(1, self._n_steps)))
        self._prev_btn.set_sensitive(self._step > 0)
        last = self._step >= self._n_steps - 1
        self._next_btn.set_label("Done" if last else "Next  ▶")
        self._next_btn.set_sensitive(not last)
        ctx = self._next_btn.get_style_context()
        if last:
            ctx.remove_class("sa-btn")
            ctx.add_class("sa-btn-nav")
        else:
            ctx.remove_class("sa-btn-nav")
            ctx.add_class("sa-btn")

    def _go_prev(self, widget):
        if self._step > 0:
            self._gcode("SA_GUIDE STEP=%d" % self._step)

    def _go_next(self, widget):
        if self._step < self._n_steps - 1:
            self._gcode("SA_GUIDE STEP=%d" % (self._step + 2))

    def _sync_from_printer(self, sa):
        """Follow guide_step, so both screens show the same page.

        The printer holds the page number and this panel reflects it. Moving
        locally and telling the printer afterwards would leave the screens on
        different pages whenever the command did not land.
        """
        step = sa.get("guide_step")
        if not isinstance(step, int) or step < 1:
            # Logged because the failure is silent and looks like the panel
            # ignoring the printer: it renders step 1 and nothing says why.
            logger.info("guide: no usable guide_step in %s",
                        sorted(sa.keys())[:6] or "an empty status")
            return False
        pages = sa.get("guide_pages")
        if isinstance(pages, list) and pages:
            self._n_steps = len(pages)
            self._ensure_pages(self._n_steps)
        if self._n_steps <= 0:
            return False
        idx = min(self._n_steps - 1, step - 1)
        if idx != self._step:
            self._step = idx
            self._show_step()
        return False

    def _show_step(self):
        self._page_stack.set_visible_child_name("step%d" % self._step)
        self._update_nav()
        self._populate_step(self._step, self._last_sa)

    # ── Step content ──────────────────────────────────────────────────────────

    def _populate_step(self, idx, sa):
        """Render one page of the printer's guide.

        Everything shown here arrives in guide_pages: the heading, whether the
        step is done, what it does, what to press, what to expect and what to
        check when it does not happen. This decides none of it.
        """
        pages = sa.get("guide_pages") or self._last_sa.get("guide_pages") or []
        if idx >= len(pages) or idx >= len(self._step_boxes):
            return
        page = pages[idx]
        box  = self._step_boxes[idx]
        for child in box.get_children():
            box.remove(child)

        box.pack_start(self._section("%d — %s" % (page.get("n", idx + 1),
                                                  page.get("title", ""))),
                       False, False, 0)

        if page.get("status"):
            tone = {"ok": _GREEN, "warn": _AMBER}.get(page.get("tone"), _GREY)
            box.pack_start(self._status(page["status"], tone), False, False, 0)

        if page.get("hint"):
            box.pack_start(self._hint(page["hint"]), False, False, 0)

        buttons = page.get("buttons") or []
        if buttons:
            row = Gtk.Grid(column_spacing=8)
            row.set_column_homogeneous(True)
            for i, b in enumerate(buttons):
                btn = _sbs.make(b.get("label", "").upper(), "sa-btn")
                btn.connect("clicked", self._send, b.get("gcode", ""))
                row.attach(btn, i, 0, 1, 1)
            box.pack_start(row, False, False, 0)

        # A per-path step arrives with one button per path, already addressed,
        # so there is nothing left to pick on another screen.
        grid = page.get("grid")
        if grid:
            g = Gtk.Grid(column_spacing=6, row_spacing=6)
            g.set_column_homogeneous(True)
            for cell in grid:
                t  = int(cell.get("tool", 0))
                fg = _GREEN if cell.get("done") else _GREY
                lbl = Gtk.Label(halign=Gtk.Align.CENTER)
                lbl.set_markup(
                    '<span foreground="%s" font_size="small">T%d\n%s</span>'
                    % (fg, t, cell.get("value") or "\u2715"))
                lbl.set_size_request(-1, int(self._gtk.font_size * 1.9))
                g.attach(lbl, t % 3, t // 3 * 2, 1, 1)
                btn = _sbs.make("T%d" % t, "sa-btn")
                btn.connect("clicked", self._send, cell.get("gcode", ""))
                g.attach(btn, t % 3, t // 3 * 2 + 1, 1, 1)
            box.pack_start(g, False, False, 0)

        if page.get("expect"):
            box.pack_start(
                self._expect("\n".join("\u2022 " + x for x in page["expect"])),
                False, False, 0)
        if page.get("warn"):
            box.pack_start(
                self._warn("\n".join("\u2022 " + x for x in page["warn"])),
                False, False, 0)

        box.show_all()

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _section(self, title):
        lbl = Gtk.Label(halign=Gtk.Align.START)
        lbl.set_markup('<b><span font_size="large">%s</span></b>' % title)
        return lbl

    def _hint(self, text):
        lbl = Gtk.Label(label=text, halign=Gtk.Align.START, xalign=0.0, wrap=True)
        lbl.get_style_context().add_class("color4")
        return lbl

    def _expect(self, text):
        """Green 'what to expect when it works' block."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        hdr = Gtk.Label(halign=Gtk.Align.START)
        hdr.set_markup('<b><span foreground="%s">\u2713 Expected</span></b>' % _GREEN)
        lbl = Gtk.Label(label=text, halign=Gtk.Align.START, xalign=0.0, wrap=True)
        lbl.set_markup('<span foreground="%s">%s</span>' % (_GREEN, text))
        box.pack_start(hdr, False, False, 0)
        box.pack_start(lbl, False, False, 0)
        return box

    def _warn(self, text):
        """Amber 'if something is wrong' block."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        hdr = Gtk.Label(halign=Gtk.Align.START)
        hdr.set_markup('<b><span foreground="%s">\u26a0 If wrong</span></b>' % _AMBER)
        lbl = Gtk.Label(halign=Gtk.Align.START, xalign=0.0, wrap=True)
        lbl.set_markup('<span foreground="%s">%s</span>' % (_AMBER, text))
        box.pack_start(hdr, False, False, 0)
        box.pack_start(lbl, False, False, 0)
        return box

    def _status(self, text, fg=_GREY):
        lbl = Gtk.Label(halign=Gtk.Align.START)
        lbl.set_markup('<span foreground="%s">%s</span>' % (fg, text))
        return lbl

    def _send(self, widget, gcode):
        self._screen._ws.klippy.gcode_script(gcode)

    def _gcode(self, gcode):
        """Send a command that did not come from a button press.

        _send is a GTK signal handler and takes the widget first, so calling
        it with one argument passes the command as the widget and sends
        nothing at all.
        """
        self._screen._ws.klippy.gcode_script(gcode)

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def activate(self):
        sa = self._printer.data.get("autoloader", {})
        self._last_sa   = dict(sa)
        self._num_paths = sa.get("num_paths", 6)
        self._stack.set_visible_child_name("pages")
        self._sync_from_printer(sa)
        self._show_step()
        # Render again once the panel is realized.
        #
        # attach_panel adds the content, calls the panel's process_update,
        # THEN activate(), and only then show_all(). Populating during that
        # first pass left the page built but not shown -- a blank content area
        # under a correct title and nav strip, on the first construction of the
        # panel only. Every later activation reuses the cached panel and looked
        # fine, which is what made it hard to see.
        GLib.idle_add(self._show_step)
        # Announce it, so opening the guide here opens it in Mainsail too.
        self._gcode("SA_GUIDE OPEN=1")

    def deactivate(self):
        # Leaving the panel closes the guide everywhere. One left open on a
        # screen nobody is looking at would keep reopening on the other.
        self._gcode("SA_GUIDE OPEN=0")

    def process_update(self, action, data):
        if action != "notify_status_update":
            return
        sa = data.get("autoloader")
        if sa is not None:
            self._last_sa.update(sa)
            n = sa.get("num_paths")
            if n is not None:
                self._num_paths = n
            GLib.idle_add(self._sync_from_printer, dict(self._last_sa))
            GLib.idle_add(self._refresh_current_step)

    def _refresh_current_step(self):
        if self._stack.get_visible_child_name() == "pages":
            self._populate_step(self._step, self._last_sa)
        return False
