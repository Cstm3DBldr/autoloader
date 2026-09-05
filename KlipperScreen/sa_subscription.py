import logging
# sa_subscription.py — shared object-subscription builder for autoloader panels.
#
# Problem this solves:
#   `printer.objects.subscribe` REPLACES the previous subscription on a
#   websocket connection (Moonraker docs: "Successive requests will
#   overwrite the previous subscriptions"). So when an autoloader panel
#   activates and subscribes to only `autoloader`, KlipperScreen's base
#   panel stops receiving the `toolhead.extruder` updates that drive its
#   active-extruder temperature display — the toolhead-temp icon in the
#   top-left freezes on whichever extruder was active when the panel
#   opened, and won't follow tool changes that the autoloader triggers
#   during a load/unload.
#
# Fix:
#   Every autoloader panel calls build_subscription() to produce a dict
#   that includes BOTH the standard KS objects (so toolhead, extruder
#   temps, heaters, etc. keep flowing to base_panel) AND the autoloader
#   itself. The result is one combined subscribe call that doesn't
#   starve any consumer.

# ── Global popup watcher ─────────────────────────────────────────────────────
# KlipperScreen's screen.process_update only forwards status updates to the
# CURRENTLY ACTIVE panel. So a watcher that lives in sa_main.process_update
# (or any other autoloader panel) only fires when that panel is on screen.
# That meant: if the user kicked off a load/unload from Mainsail while KS was
# on the home screen (or any non-autoloader panel), KS never saw cal_state
# transition to 'load_purge' / 'unload_done' and never opened sa_post_load —
# the post-load action popup only appeared in Mainsail.
#
# Fix: monkey-patch screen.process_update once, the first time any autoloader
# panel calls install_global_popup_watcher(). The wrapped version delegates
# to the original (so all existing per-panel handlers keep working), then
# also checks autoloader.cal_state and opens sa_post_load on the load_purge /
# unload_done transitions regardless of which panel is currently active.

_watcher_installed = False
_last_guide_open = False
_subscribed = False
_last_cal_state    = None
_last_entry        = []
_initialized       = False  # baseline from first observation (no trigger)

# When the user explicitly dismisses sa_post_load (Park / Exit / Load-Same),
# Klipper's SA_RESPOND processing is asynchronous — there's a window where
# subsequent status updates still report the SAME cal_state value because
# the gcode hasn't been picked up yet. Without this flag, our global watcher
# (or sa_main's panel-local watcher) sees what looks like a fresh transition
# into load_purge / unload_done on the very next status reprocess and reopens
# sa_post_load. The flag stores the cal_state at dismiss time and suppresses
# popup reopening as long as cal_state matches; it clears automatically when
# cal_state actually transitions to a different value (i.e. Klipper has
# processed the response).
_dismissed_at_cal_state = None


def mark_user_dismissed(cal_state):
    """Called from sa_post_load._close() when the user explicitly dismisses
    the action popup. Suppresses popup reopen on the same cal_state value."""
    global _dismissed_at_cal_state
    _dismissed_at_cal_state = cal_state

def install_global_popup_watcher(screen):
    """Monkey-patch screen.process_update so the post-load action popup and
    the on-insert load wizard fire from any KlipperScreen panel, matching
    Mainsail's always-on behavior. Idempotent — only patches once per run.
    """
    global _watcher_installed
    if _watcher_installed:
        return
    _watcher_installed = True
    install_subscription_merge()
    # Logged because its absence is invisible and looks exactly like the
    # feature being broken: until some autoloader panel opens, nothing on this
    # screen is listening, so a guide opened in Mainsail is simply not seen.
    # With this line the log answers "was anything watching?" directly.
    logging.info("sa_subscription: global watcher installed")
    original = screen.process_update

    def wrapped(*args, **kwargs):
        result = original(*args, **kwargs)
        try:
            _on_status(screen, *args)
        except Exception:
            logging.exception("sa_subscription: popup watcher failed")
        return result

    screen.process_update = wrapped


_additive = False
_subscribed_objects = {}


def install_subscription_merge():
    """Send the union of every subscription asked for, not just the last one.

    Also fixes the reverse loss: when KlipperScreen re-subscribes after a
    Klippy restart it sends its own list, which does not contain `autoloader`,
    so our data stopped arriving until a panel was opened again.
    """
    global _additive
    if _additive:
        return True
    try:
        from ks_includes.KlippyWebsocket import MoonrakerApi
    except Exception:
        logging.exception("sa_subscription: cannot make subscriptions additive")
        return False

    original = MoonrakerApi.object_subscription

    def wrapped(self, updates):
        global _subscribed_objects
        incoming = (updates or {}).get("objects") or {}
        _subscribed_objects = merge_objects(_subscribed_objects, incoming)
        return original(self, {"objects": dict(_subscribed_objects)})

    MoonrakerApi.object_subscription = wrapped
    _additive = True
    logging.info("sa_subscription: subscriptions are additive")
    return True


def _ensure_subscription(screen):
    """Ask Moonraker for the autoloader object, once.

    A panel does two things when it activates: subscribes to this object and
    installs the watcher. Installing the watcher on its own -- which is what
    starting from an add-on did at first -- gives you a listener for data
    nobody is sending: KlipperScreen's own subscription does not include
    `autoloader`, so notify_status_update arrives without it and every check
    below falls through. The watcher looked installed and did nothing.

    Deferred to the first status update rather than done in init(), because at
    KlipperScreen startup the websocket is not connected yet.
    """
    global _subscribed
    if _subscribed:
        return
    try:
        screen._ws.klippy.object_subscription(
            {"objects": build_subscription(screen)})
    except Exception:
        logging.exception("sa_subscription: could not subscribe")
        return
    _subscribed = True

    # Subscribing only opens the tap. Moonraker then sends CHANGED fields
    # and nothing else, so a value that never changes again -- guide_step
    # sitting at 6, say -- is never delivered at all, and every reader sees
    # a status object containing one key. One query seeds the real thing.
    try:
        resp = screen.apiclient.send_request("printer/objects/query?autoloader")
        sa = (resp or {}).get("status", {}).get("autoloader")
        if isinstance(sa, dict) and sa:
            screen.printer.process_update({"autoloader": sa})
            logging.info("sa_subscription: subscribed and seeded %d fields"
                         % len(sa))
            return
    except Exception:
        logging.exception("sa_subscription: could not seed the autoloader object")
    logging.info("sa_subscription: subscribed to the autoloader object "
                 "(not seeded - values that never change will be missing)")


def _on_status(screen, *args):
    """Inspect a status update for autoloader transitions and open the
    appropriate popup panel via screen.show_panel."""
    global _last_cal_state, _last_entry, _initialized
    if not args or args[0] != "notify_status_update":
        return
    _ensure_subscription(screen)
    if len(args) < 2 or not isinstance(args[1], dict):
        return
    sa = args[1].get("autoloader")
    if not isinstance(sa, dict):
        return


    global _dismissed_at_cal_state, _last_guide_open
    cal   = sa.get("cal_state")
    entry = sa.get("entry_filament")

    # First observation establishes the baseline without firing any popup.
    # Otherwise a printer that already has filament inserted at boot would
    # auto-open the load wizard, and a stale cal_state would auto-open the
    # post-load panel.
    #
    # guide_open is deliberately NOT baselined that way. The other two are
    # conditions that happen to be true at boot -- filament sitting in a
    # sensor, a cal_state left over from before a restart -- and acting on
    # them would be acting on history. guide_open is someone having the guide
    # open on another screen right now, and following it is the entire point
    # of the flag.
    #
    # Swallowing it here is what made the quirk: this watcher is installed by
    # the first autoloader panel to open, so opening the Autoloader panel took
    # an already-true guide_open as the baseline and then waited forever for a
    # change that had already happened. The calibration panel had to be opened
    # by hand, which looks like the sync not working at all.
    if not _initialized:
        _last_cal_state = cal if cal is not None else _last_cal_state
        if isinstance(entry, list):
            _last_entry = list(entry)
        _last_guide_open = bool(sa.get("guide_open", False))
        _initialized = True
        if _last_guide_open:
            logging.info(
                "sa_subscription: guide already open elsewhere -> following it")
            from gi.repository import GLib
            stack = getattr(screen, "_cur_panels", None) or []
            if (stack[-1] if stack else None) != "sa_calibration_guide":
                GLib.idle_add(screen.show_panel, "sa_calibration_guide",
                              "Calibration Guide")
        return

    # Clear the user-dismissed flag once cal_state actually changes away
    # from the value at dismiss-time. This re-arms the popup for the next
    # legitimate transition into load_purge / unload_done.
    if (_dismissed_at_cal_state is not None
            and cal != _dismissed_at_cal_state):
        _dismissed_at_cal_state = None

    from gi.repository import GLib

    # guide_open transition → open or leave the calibration guide.
    #
    # The guide used to be a panel each UI opened for itself, so opening it in
    # Mainsail left the touchscreen wherever it was. The printer holds the flag
    # now and this follows it, which is the same thing that already makes
    # prompts appear on both screens at once.
    #
    # Only transitions act. Acting on the level would fight the operator every
    # time they navigated away from a guide that is still open.
    guide_open = sa.get("guide_open")
    if isinstance(guide_open, bool) and guide_open != _last_guide_open:
        logging.info("sa_subscription: guide_open %r -> %r"
                     % (_last_guide_open, guide_open))
        _last_guide_open = guide_open
        # _cur_panels is a stack, not a single name -- the last entry is what
        # is on screen. There is no _cur_panel attribute, so testing for one
        # would have quietly matched nothing and opened the guide on top of
        # itself every update.
        stack = getattr(screen, "_cur_panels", None) or []
        current = stack[-1] if stack else None
        if guide_open:
            if current != "sa_calibration_guide":
                GLib.idle_add(screen.show_panel, "sa_calibration_guide",
                              "Calibration Guide")
        elif current == "sa_calibration_guide":
            # Closed elsewhere. _menu_go_back rather than show_panel, so the
            # touchscreen returns wherever it came from instead of being sent
            # to a panel it never asked for.
            GLib.idle_add(screen._menu_go_back)

    # cal_state transition → post-load action popup
    if cal is not None and cal != _last_cal_state:
        logging.info(
            "sa_subscription: cal_state %r -> %r (dismissed_at=%r)"
            % (_last_cal_state, cal, _dismissed_at_cal_state))
        # Skip popup if user already explicitly dismissed at this cal_state
        # value. The dismiss flag clears automatically (above) once cal_state
        # actually transitions away.
        if cal == _dismissed_at_cal_state:
            logging.info("sa_subscription: suppressed (user dismissed)")
        elif cal in ("load_purge", "unload_done"):
            # Popup-on-complete is now unconditional — the per-user toggle
            # in sa_settings was removed because the popup behaviour worked
            # well enough that gating it added complexity without value.
            logging.info("sa_subscription: opening sa_post_load")
            GLib.idle_add(
                screen.show_panel, "sa_post_load", "Autoloader Action")
        # No branch for other cal_state values any more. Calibration prompts
        # are emitted by the Klipper extra using Klipper's own action:prompt_*
        # protocol, which KlipperScreen renders itself from any screen with no
        # panel open. This watcher could never do that: it is installed from an
        # sa_* panel's activate(), so a touchscreen sitting on its own main
        # menu had nothing watching and missed every prompt.
        _last_cal_state = cal

    # entry-sensor rising edge → load/unload wizard popup (filament inserted)
    if isinstance(entry, list):
        for i, active in enumerate(entry):
            was = _last_entry[i] if i < len(_last_entry) else False
            if not was and active:
                GLib.idle_add(
                    screen.show_panel, "sa_load_unload", "Load / Unload")
        _last_entry = list(entry)


def host_objects(screen):
    """The objects KlipperScreen itself subscribes to.

    Rebuilt here from the same printer helpers screen.py uses, because our
    subscription REPLACES the host's and therefore has to contain it. The
    duplication is unwanted: if KlipperScreen starts watching a new class of
    object, this list goes stale and that object stops updating with no error
    anywhere. It is the price of there being no way to add to a subscription.

    Every lookup is guarded -- a KlipperScreen without one of these helpers
    should cost us that one object, not the whole subscription.
    """
    objs = {
        "firmware_retraction": ["retract_length", "retract_speed",
                                "unretract_extra_length", "unretract_speed"],
        "exclude_object": ["current_object", "objects", "excluded_objects"],
        "manual_probe": ["is_active"],
        "screws_tilt_adjust": ["results", "error"],
    }
    groups = (
        ("get_tools", ["target", "temperature", "pressure_advance",
                       "smooth_time", "power"]),
        ("get_heaters", ["target", "temperature", "power"]),
        ("get_temp_sensors", ["temperature"]),
        ("get_temp_fans", ["target", "temperature"]),
        ("get_fans", ["speed"]),
        ("get_filament_sensors", ["enabled", "filament_detected"]),
        ("get_pwm_tools", ["value"]),
        ("get_output_pins", ["value"]),
        ("get_leds", ["color_data"]),
    )
    printer = getattr(screen, "printer", None)
    for getter, fields in groups:
        fn = getattr(printer, getter, None)
        if not callable(fn):
            continue
        try:
            for name in fn() or []:
                objs[name] = list(fields)
        except Exception:
            logging.exception("sa_subscription: %s failed", getter)
    return objs


def merge_objects(a, b):
    """Union of two subscription dicts. None means "every field"."""
    out = dict(a or {})
    for key, fields in (b or {}).items():
        if key not in out:
            out[key] = None if fields is None else list(fields)
        elif out[key] is None or fields is None:
            out[key] = None
        else:
            out[key] = sorted(set(out[key]) | set(fields))
    return out


def build_subscription(screen, num_paths=0, include_encoders=False):
    """Combined subscription dict for an autoloader panel.

    screen           : the KlipperScreen instance (self._screen in panels)
    num_paths        : number of autoloader paths (only used if include_encoders)
    include_encoders : if True, subscribe to each `sa_encoder N` object too
                       (needed by sa_main; not needed by load/unload panels)
    """
    objs = {
        # Autoloader's own status object — drives the panel UI.
        "autoloader":         None,
        # Toolhead — base_panel reads `toolhead.extruder` to know which
        # extruder's temperature to display in the top bar. WITHOUT this,
        # the temp icon won't follow autoloader-triggered tool changes.
        "toolhead":           ["homed_axes", "extruder", "position",
                               "estimated_print_time", "print_time",
                               "max_accel", "max_velocity",
                               "minimum_cruise_ratio",
                               "square_corner_velocity"],
        # Standard KS panels watch these for state and progress display.
        "gcode_move":         ["extrude_factor", "gcode_position",
                               "homing_origin", "speed_factor", "speed"],
        "idle_timeout":       ["state"],
        "pause_resume":       ["is_paused"],
        "print_stats":        ["print_duration", "total_duration",
                               "filament_used", "filename", "state",
                               "message", "info"],
        "virtual_sdcard":     ["file_position", "is_active", "progress"],
        "webhooks":           ["state", "state_message"],
        "motion_report":      ["live_position", "live_velocity",
                               "live_extruder_velocity"],
        "fan":                ["speed"],
        "display_status":     ["progress", "message"],
        # Toolchanger — sa_main marks the mounted tool from this, and pulses
        # that marker while a change is in flight. `status` is one of
        # uninitialized / initializing / ready / changing / error, and
        # `tool_number` is the ACTIVE tool, which flips partway through a
        # change (inside _configure_toolhead_for_tool, after the old head is
        # parked and before the new one is picked up). The target tool is
        # never exposed, which is why the marker follows tool_number.
        "toolchanger":        ["status", "tool", "tool_number",
                               "detected_tool_number"],
    }
    if include_encoders:
        for i in range(num_paths):
            objs["sa_encoder %d" % i] = None
    # All extruders — base_panel's per-extruder temp boxes need these.
    try:
        for tool in screen.printer.get_tools():
            objs[tool] = ["target", "temperature", "pressure_advance",
                          "smooth_time", "power"]
        for h in screen.printer.get_heaters():
            objs[h] = ["target", "temperature", "power"]
        for s in screen.printer.get_temp_sensors():
            objs[s] = ["temperature"]
        for f in screen.printer.get_fans():
            objs[f] = ["speed"]
        for fs in screen.printer.get_filament_sensors():
            objs[fs] = ["enabled", "filament_detected"]
    except Exception:
        # If printer object isn't fully initialized yet, return what we have.
        pass
    # With the additive wrap in place the host's own call already carries its
    # objects, so this only has to name ours. Without it, a subscription
    # REPLACES the connection's previous one and anything missing here stops
    # being delivered to the whole application -- hence the reconstruction,
    # kept strictly as the fallback it is.
    if _additive:
        return objs
    return merge_objects(host_objects(screen), objs)
