# sa_calibration.py — Autoloader calibration routines
#
# Phase-based state machine design:
#   - Each calibration command kicks off phase 0 (automated work + prompt).
#   - SA_RESPOND VALUE=<answer> dispatches to the next phase — no blocking wait loops.
#   - State stored in owner._cal_state / owner._cal_data; cleared on Klipper restart.
#   - Calibrated values are written immediately to save_variables (no SAVE_CONFIG needed).
#   - Values are loaded from save_variables at klippy:ready, overriding hardware.cfg defaults.
#
# Calibration states:
#   sel_confirm
#   drv_path / drv_mark / drv_meas / drv_save
#   enc_zero_N / enc_exit_N
#   bow_est_N

import sys, os as _os, re, math
_extras_dir = _os.path.dirname(_os.path.abspath(__file__))
if _extras_dir not in sys.path:
    sys.path.insert(0, _extras_dir)

NL = chr(10)

import logging


class SACalibration:

    def __init__(self, owner):
        self.owner = owner

    # ══════════════════════════════════════════════════════════════════════════
    # SA_RESPOND dispatch  (called from Autoloader._cmd_respond)
    # ══════════════════════════════════════════════════════════════════════════

    def respond(self, gcmd, value):
        """Route an SA_RESPOND value to the correct phase handler."""
        owner = self.owner
        state = owner._cal_state

        if state is None:
            gcmd.respond_info("SA: No calibration is waiting for input.")
            return

        val = value.strip()
        if val.lower() in ('abort', 'cancel'):
            self.close_ui_prompt(gcmd)
            self._abort(gcmd)
            return

        # A +/- tap from the numeric prompt: adjust and re-ask, staying in the
        # same phase rather than answering it.
        if val.lower().startswith('adj:'):
            self._numeric_adjust(gcmd, val[4:])
            return

        # SKIP STEP is answered here rather than in every phase handler: it
        # means "leave this one alone and move on", which is the same action
        # whatever question is on screen.
        if val.lower() == 'skipstep':
            self.close_ui_prompt(gcmd)
            self._skip_step(gcmd)
            return

        # A real answer closes the dialog; the next phase raises its own.
        self.close_ui_prompt(gcmd)

        try:
            if state.startswith('chain_'):
                self._chain_respond(gcmd, state, val)
            elif state.startswith('srv_'):
                self._srv_respond(gcmd, state, val)
            elif state.startswith('end_'):
                self._end_respond(gcmd, state, val)
            elif state.startswith('dir_'):
                self._dir_respond(gcmd, state, val)
            elif state.startswith('sel_'):
                self._sel_respond(gcmd, state, val)
            elif state.startswith('drv_'):
                self._drv_respond(gcmd, state, val)
            # Before the generic enc_ branch: these start with it too.
            elif state.startswith('enc_speed'):
                self._encspeed_respond(gcmd, state, val)
            elif state.startswith('enc_'):
                self._enc_respond(gcmd, state, val)
            elif state.startswith('bow_'):
                self._bow_respond(gcmd, state, val)
            elif state == 'load_purge':
                self.owner.sequences._load_purge_respond(gcmd, val)
            elif state == 'unload_done':
                self.owner.sequences._unload_done_respond(gcmd, val)
            else:
                gcmd.respond_info(
                    "SA CAL: Unknown calibration state '%s' — clearing." % state)
                self._clear()
        except Exception as e:
            logging.exception("SACalibration: error in respond()")
            self._clear()
            raise gcmd.error("SA CAL: %s" % str(e))

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _abort(self, gcmd):
        gcmd.respond_info("SA CAL: Calibration aborted.")
        # Stop anything that re-arms itself, or the sweep keeps running after
        # the phase it belongs to has been cleared.
        self._encspeed_disarm()
        self._end_disarm(self.owner)
        self.owner.motion.servo_disengage()
        self._clear()

    def _safe_selector_move(self, motion, position_mm):
        """Disengage servo if engaged, move selector, restore servo state."""
        was_engaged = self.owner._servo_is_engaged
        if was_engaged:
            motion.servo_disengage()
        motion.selector_move_to(position_mm)
        if was_engaged:
            motion.servo_engage()

    def _clear(self):
        self.owner._cal_state  = None
        self.owner._cal_data   = {}
        self.owner._cal_prompt = ''

    def _yes(self, value):
        return value.lower() in ('yes', 'y', '1', 'true', 'ok')

    # -- Prompts ---------------------------------------------------------------
    #
    # Every prompt goes out twice: as console text with copy-paste commands,
    # and as Klipper's `action:prompt_*` protocol. That protocol is understood
    # by KlipperScreen (screen.py -> ks_includes/widgets/prompts.py) and by
    # Mainsail and Fluidd, so a single emission drives every UI and they cannot
    # disagree about what is being asked.
    #
    # It also fixes a real defect. The KlipperScreen prompt panel was opened by
    # a watcher installed from each sa_* panel's activate(), so a freshly
    # started touchscreen -- sitting on its own main menu, having never been
    # into the Autoloader menu -- had nothing watching cal_state and silently
    # missed every prompt. A native prompt needs no panel to be open.

    _BTN_LABEL = {'yes': 'YES', 'no': 'NO', 'abort': 'ABORT'}
    _BTN_STYLE = {'yes': 'primary', 'no': 'secondary', 'abort': 'error'}

    SECT_EXPECT = "%s What to expect" % '✓'
    SECT_WARN   = "%s Watch out for" % '⚠'

    def _section(self, heading, items):
        """One marked block: a heading line, then bulleted lines."""
        if not items:
            return ""
        lines = [heading]
        for item in items:
            for part in str(item).split(NL):
                part = part.strip()
                if part:
                    lines.append("%s %s" % ('•', part))
        return NL.join(lines)

    def _emit_ui_prompt(self, gcmd, title, text, buttons, footer=(),
                        columns=None, expect=(), warn=()):
        """Send one action:prompt_* sequence.

        `buttons` and `footer` are (label, value, style) triples; each becomes a
        button that runs `SA_RESPOND VALUE=<value>`.

        Buttons go inside a group, which KlipperScreen renders as a Gtk.FlowBox
        -- it re-flows to the screen width on its own, so this needs no sizing
        of ours. `columns` splits them across several groups, and since each
        group is its own FlowBox stacked under the last, that is how a fixed
        grid is expressed in this protocol: columns=3 over six buttons gives a
        2x3 grid rather than whatever one row happens to wrap to.
        """
        # Remember it so a dismissed dialog can be brought back -- closing
        # the prompt does not answer the question, and the phase is still
        # waiting.
        try:
            self.owner._cal_data['_ui_last'] = (
                title, text, list(buttons), list(footer), columns)
        except Exception:
            pass

        # The step name, as the guide panel prints it above its own body. The
        # title carries "Step 4 / 9"; this says which step that is, so the two
        # surfaces read identically.
        step_n, step_name = self._current_step()
        if step_name and not str(text).startswith(step_name):
            text = step_name + NL + NL + str(text)

        # Move the guide to this phase's page wherever it is open, so the
        # panel behind the prompt is never showing a different step than the
        # prompt in front of it -- on either UI.
        if step_n is not None:
            self.owner._guide_step = step_n

        for heading, items in ((self.SECT_EXPECT, expect),
                               (self.SECT_WARN, warn)):
            block = self._section(heading, items)
            if block:
                text = str(text) + NL + NL + block

        # Somewhere to go that is not ABORT. A calibration cannot offer BACK
        # honestly -- the phases are not reversible, and a "back" that silently
        # did nothing would be worse than none -- but skipping forward is
        # always meaningful, and it is what the guide's NEXT does.
        footer = list(footer)
        if step_n is not None and not (self.owner._cal_state or '').startswith('chain_'):
            if self._step_after(step_n) is not None:
                footer = [("SKIP STEP", "skipstep", "secondary")] + footer

        r = gcmd.respond_raw
        try:
            r("// action:prompt_end")
            r("// action:prompt_begin %s" % title)
            # One prompt_text per line. Each "//" line is a separate command,
            # so an embedded newline would truncate the dialog at the first
            # one -- which is why "Accept these positions?" appeared with no
            # positions under it while they went to the console instead.
            for line in str(text).split(NL):
                line = line.rstrip()
                if line:
                    r("// action:prompt_text %s" % line)
                else:
                    r("// action:prompt_text  ")
            if buttons:
                step = columns if columns and columns > 0 else len(buttons)
                for i in range(0, len(buttons), step):
                    r("// action:prompt_button_group_start")
                    for label, value, style in buttons[i:i + step]:
                        r("// action:prompt_button %s|SA_RESPOND VALUE=%s|%s"
                          % (label, value, style))
                    r("// action:prompt_button_group_end")
            for label, value, style in footer:
                r("// action:prompt_footer_button %s|SA_RESPOND VALUE=%s|%s"
                  % (label, value, style))
            r("// action:prompt_show")
        except Exception:
            logging.exception("SA CAL: failed to emit UI prompt")

    def close_ui_prompt(self, gcmd):
        """Dismiss any open prompt on every UI."""
        try:
            gcmd.respond_raw("// action:prompt_end")
        except Exception:
            pass

    def reraise_prompt(self, gcmd):
        """Show the waiting phase's prompt again.

        Closing a prompt dialog dismisses the window but does not answer the
        question -- the phase is still waiting, and until this existed the
        only way back was to know to type SA_RESPOND VALUE=abort at a console.
        Asking for a calibration that is already running now simply puts the
        question back on screen.
        """
        last = self.owner._cal_data.get('_ui_last')
        if not last:
            return False
        title, text, buttons, footer, columns = last
        self._emit_ui_prompt(gcmd, title, text, buttons, footer, columns)
        return True

    def _busy(self, gcmd):
        """True if a calibration is already waiting; re-raises its prompt."""
        owner = self.owner
        if owner._cal_state is None:
            return False
        if self.reraise_prompt(gcmd):
            gcmd.respond_info(
                "SA CAL: Already at phase '%s' — prompt re-opened.\n"
                "  Answer it, or SA_RESPOND VALUE=abort to cancel."
                % owner._cal_state)
        else:
            gcmd.respond_info(
                "SA CAL: Calibration already in progress (state=%s).\n"
                "  SA_RESPOND VALUE=abort" % owner._cal_state)
        return True

    def _prompt(self, gcmd, message, *commands, **kw):
        """Print a message with copy-paste commands, and raise the same
        question on every UI.

        Keyword options:
          choices -- [(label, value), ...] for a fixed set of answers
          numeric -- {'value': float, 'unit': str, 'steps': (...)} for a value
                     the operator dials in; see _numeric_prompt
        """
        detail = kw.get('detail')
        self.owner._cal_prompt = message
        lines = [
            "",
            "SA CAL: " + message,
            "",
        ]
        if detail:
            lines.extend(str(detail).split(NL))
            lines.append("")
        for cmd in commands:
            lines.append("  " + cmd)
        lines.append("")
        gcmd.respond_info("\n".join(lines))

        numeric = kw.get('numeric')
        if numeric is not None:
            self._numeric_prompt(gcmd, message, **numeric)
            return

        choices = kw.get('choices')
        if choices is None:
            # Derive the answers from the commands already being printed, so
            # every existing yes/no phase gets buttons with no edit at all. A
            # command carrying a parenthetical is a fill-in-the-blank template
            # rather than a real choice -- skip those.
            choices = []
            for cmd in commands:
                m = re.match(r'^SA_RESPOND\s+VALUE=(\S+)\s*$', cmd.strip())
                if not m:
                    continue
                val = m.group(1)
                choices.append((self._BTN_LABEL.get(val.lower(), val.upper()),
                                val))
        if not choices:
            return

        # A choice may carry its own style as a third element; otherwise it
        # falls back to the yes/no/abort mapping.
        buttons = []
        for c in choices:
            if len(c) == 3:
                buttons.append(tuple(c))
            else:
                lbl, val = c
                buttons.append((lbl, val,
                                self._BTN_STYLE.get(str(val).lower(),
                                                    'default')))
        # The detail goes into the DIALOG, not just the console. A question
        # like "Accept these positions?" with the positions printed only to the
        # console is unanswerable on a touchscreen, and barely better in
        # Mainsail where the numbers scroll away behind the modal.
        body = message if not detail else (message + NL + NL + str(detail))
        self._emit_ui_prompt(
            gcmd, self._ui_title(), body, buttons,
            footer=[("ABORT", "abort", "error")],
            columns=kw.get('columns'),
            expect=kw.get('expect', ()), warn=kw.get('warn', ()))

    _PATH_STYLE = {'loaded': 'primary', 'partial': 'info'}

    def _path_choices(self):
        """Path buttons for a "which path?" prompt.

        Labelled T0..Tn to match every other surface, and coloured by what is
        actually in the path -- a loaded path stands out from a staged one,
        and both from an empty one -- so the choice carries the state the
        operator needs rather than making them remember it.
        """
        owner  = self.owner
        states = list(getattr(owner, 'path_states', []) or [])
        out = []
        for i in range(owner.num_paths):
            st = states[i] if i < len(states) else 'unknown'
            out.append(("T%d" % i, str(i),
                        self._PATH_STYLE.get(st, 'secondary')))
        return out

    # ── Where am I? ───────────────────────────────────────────────────────────
    #
    # The panels number the calibration 1..9 and the prompts used to number
    # nothing, so a prompt could not say which step it belonged to and read as
    # a popup that had interrupted the guide rather than a page of it.
    #
    # Both now take the number from here. A phase maps to a step by its state
    # prefix; a chain offer maps by the command it is about to run, so the
    # offer already shows the step you are going TO.

    _STEP_TOTAL = 9
    _STEP_NAMES = {
        1: "Motor direction",
        2: "Endstop test",
        3: "Home selector",
        4: "Selector positions",
        5: "Servo engage angle",
        6: "Drive rotation distance",
        7: "Encoder speed",
        8: "Encoder mm/pulse",
        9: "Bowden length",
    }

    # Longest prefix first: SA_CALIBRATE_ENCODER_SPEED would otherwise match
    # the per-path SA_CALIBRATE_ENCODER entry and report step 8 for step 7.
    _STEP_BY_COMMAND = (
        ("SA_BUZZ_CHECK",              1),
        ("SA_TEST_ENDSTOP",            2),
        ("SA_HOME",                    3),
        ("SA_CALIBRATE_SELECTOR",      4),
        ("SA_CALIBRATE_SERVO",         5),
        ("SA_CALIBRATE_DRIVE",         6),
        ("SA_CALIBRATE_ENCODER_SPEED", 7),
        ("SA_CALIBRATE_ENCODER",       8),
        ("SA_CALIBRATE_BOWDEN",        9),
    )

    # load_purge and unload_done are deliberately absent: they are load/unload
    # flows, not calibration, and numbering them "step N of 9" would be a lie.
    _STEP_BY_STATE = (
        ("dir_", 1),
        ("end_", 2),
        ("sel_", 4),
        ("srv_", 5),
        ("drv_", 6),
        # More specific first: the loop takes the first match, and
        # "enc_speed_run" starts with "enc_" too.
        ("enc_speed", 7),
        ("enc_", 8),
        ("bow_", 9),
    )

    def _step_after(self, step_n):
        """The first chain entry belonging to a later step, or None."""
        for entry in self._CHAIN:
            n = self._step_for_command(entry[5]) if entry[5] else None
            if n is None:
                # The last entry has no follow-on command; find its own step
                # from the key instead so the end of the list still terminates.
                continue
            if n > step_n:
                return entry
        return None

    @classmethod
    def _step_for_command(cls, cmd):
        text = (cmd or "").strip().upper()
        best = None
        for prefix, step in cls._STEP_BY_COMMAND:
            if text.startswith(prefix):
                if best is None or len(prefix) > len(best[0]):
                    best = (prefix, step)
        return best[1] if best else None

    def _current_step(self):
        """(number, name) for the phase now waiting, or (None, None)."""
        st = (self.owner._cal_state or "").lower()
        if not st:
            return None, None
        if st.startswith("chain_"):
            nxt = (self.owner._cal_data or {}).get("_next_cmd")
            n = self._step_for_command(nxt)
        else:
            n = None
            for prefix, step in self._STEP_BY_STATE:
                if st.startswith(prefix):
                    n = step
                    break
        if n is None:
            return None, None
        return n, self._STEP_NAMES.get(n, "")

    def _ui_title(self):
        """Heading for the prompt dialog.

        Matches the guide panel's own title exactly, so a prompt raised while
        the guide is open reads as that guide's next page rather than as
        something that has interrupted it.
        """
        n, _name = self._current_step()
        if n is not None:
            return "Calibration — Step %d / %d" % (n, self._STEP_TOTAL)
        return "Autoloader Calibration"

    # -- Numeric entry without a numpad ----------------------------------------
    #
    # The prompt protocol has buttons and text but no text entry, so a measured
    # value is dialled in with coarse-to-fine steps and confirmed. The value
    # lives in _cal_data so it survives between taps, and the prompt is re-sent
    # after each one with the running value in the text and baked into ACCEPT.
    #
    # This is why there is no numpad panel any more: a numpad needs a
    # KlipperScreen panel to be open, which is exactly the failure above.

    _NUM_STEPS = (10.0, 1.0, 0.1)

    def _numeric_prompt(self, gcmd, message, value=0.0, unit='mm', steps=None):
        d = self.owner._cal_data
        d['_np_val']   = float(value)
        d['_np_msg']   = message
        d['_np_unit']  = unit
        d['_np_steps'] = tuple(steps or self._NUM_STEPS)
        self._numeric_render(gcmd)

    def _numeric_render(self, gcmd):
        d     = self.owner._cal_data
        val   = float(d.get('_np_val', 0.0))
        unit  = d.get('_np_unit', 'mm')
        steps = d.get('_np_steps', self._NUM_STEPS)

        buttons = []
        for st in sorted(steps, reverse=True):
            buttons.append(("-%g" % st, "adj:-%g" % st, 'secondary'))
        for st in sorted(steps):
            buttons.append(("+%g" % st, "adj:+%g" % st, 'primary'))

        text = "%s\n\nCurrent: %.2f %s" % (d.get('_np_msg', ''), val, unit)
        # One row of decrements above one row of increments -- the coarse step
        # sits at the outside of each row, so the pair reads as a mirrored
        # scale rather than an arbitrary line of buttons.
        self._emit_ui_prompt(
            gcmd, self._ui_title(), text, buttons,
            footer=[("ACCEPT  %.2f %s" % (val, unit), "%.4f" % val, 'primary'),
                    ("ABORT", "abort", "error")],
            columns=len(steps))

    def _numeric_adjust(self, gcmd, delta):
        """Apply one +/- tap and re-raise the prompt with the new value."""
        d = self.owner._cal_data
        if '_np_val' not in d:
            gcmd.respond_info("SA: No value is being entered.")
            return
        try:
            d['_np_val'] = max(0.0, float(d['_np_val']) + float(delta))
        except ValueError:
            return
        # The servo phase moves to the new angle as you step, so the operator
        # is watching the mechanism rather than reading a number.
        if (self.owner._cal_state or '').startswith('srv_'):
            self._srv_render(gcmd)
            return
        if self.owner._cal_state == 'sel_tune':
            self._sel_tune_render(gcmd)
            return
        self._numeric_render(gcmd)

    def _save_variable(self, key, value):
        """Write a calibration value to save_variables immediately — no restart needed."""
        self.owner.gcode.run_script_from_command(
            "SAVE_VARIABLE VARIABLE=%s VALUE=%s" % (key, str(value)))

    def _patch_hardware_cfg(self, section, option, value):
        """Edit a key in hardware.cfg directly — no SAVE_CONFIG needed.

        Returns (True, path) on success, (False, error_msg) on failure.
        Looks for hardware.cfg alongside the primary Klipper config file.
        """
        try:
            config_file = self.owner.printer.get_start_args().get('config_file', '')
            config_dir  = _os.path.dirname(config_file)
            hw_cfg      = _os.path.join(
                config_dir, 'autoloader', 'hardware.cfg')
            if not _os.path.exists(hw_cfg):
                return False, "hardware.cfg not found at %s" % hw_cfg

            with open(hw_cfg, 'r') as f:
                lines = f.readlines()

            in_section = False
            patched    = False
            new_lines  = []
            for line in lines:
                stripped = line.strip()
                if stripped.startswith('['):
                    in_section = (stripped == '[%s]' % section)
                if in_section and re.match(
                        r'^' + re.escape(option) + r'\s*[=:]', stripped):
                    line    = re.sub(r'(\s*[=:]\s*)\S+', r'\g<1>' + value, line)
                    patched = True
                new_lines.append(line)

            if not patched:
                return False, ("'%s' not found in [%s]" % (option, section))

            with open(hw_cfg, 'w') as f:
                f.writelines(new_lines)
            logging.info("SACalibration: patched %s [%s] %s = %s",
                         hw_cfg, section, option, value)
            return True, hw_cfg
        except Exception as e:
            return False, str(e)

    def _restore_selector_current(self, gcmd, sn):
        owner = self.owner
        try:
            owner.gcode.run_script_from_command(
                "SET_TMC_CURRENT STEPPER=%s CURRENT=0.600" % sn)
        except Exception as e:
            logging.warning("SACalibration: failed to restore selector current: %s", e)

    # ══════════════════════════════════════════════════════════════════════════
    # SA_CALIBRATE_SELECTOR
    # ══════════════════════════════════════════════════════════════════════════

    def calibrate_selector_auto(self, gcmd):
        """Phase 0 — automated sweep + measurement, then prompt to accept."""
        owner  = self.owner
        motion = owner.motion
        sn     = owner._sel_name()

        if owner._cal_state is not None:
            self._busy(gcmd)
            return

        gcmd.respond_info(
            "SA SELECTOR CALIBRATION\n"
            "========================\n"
            "Homing → sweep to far stop → home back → calculate positions.\n"
            "No filament loaded. Servo must be free.")

        # ── Step 1: Home ──────────────────────────────────────────────────────
        gcmd.respond_info("SA CAL: Homing...")
        motion.selector_home()

        # ── Step 2: Stepper object for MCU position measurement ───────────────
        sel_obj   = owner.printer.lookup_object('manual_stepper sa_selector')
        stepper   = sel_obj.get_steppers()[0]
        step_dist = stepper.get_step_dist()

        # ── Steps 3+4: Sweep to far wall ─────────────────────────────────────
        # Overshoot move at reduced current — brief grind at far wall is
        # acceptable for one-time calibration. Current is restored immediately
        # after the sweep. Measurement accuracy comes from homing back, not
        # from detecting the far-wall stop.
        far_target = owner.selector_max_travel + 30.0

        owner.gcode.run_script_from_command("MANUAL_STEPPER STEPPER=%s ENABLE=1" % sn)
        owner.gcode.run_script_from_command("MANUAL_STEPPER STEPPER=%s SET_POSITION=0" % sn)
        cal_current = owner.selector_cal_current
        owner.gcode.run_script_from_command(
            "SET_TMC_CURRENT STEPPER=%s CURRENT=%.3f" % (sn, cal_current))
        gcmd.respond_info("SA CAL: Sweeping to far wall (%.0fmm) at %.2fA..." % (far_target, cal_current))
        owner.gcode.run_script_from_command(
            "MANUAL_STEPPER STEPPER=%s MOVE=%.2f SPEED=%.1f SYNC=1"
            % (sn, far_target, owner.selector_homing_speed))
        owner.gcode.run_script_from_command("M400")
        owner.gcode.run_script_from_command(
            "SET_TMC_CURRENT STEPPER=%s CURRENT=0.600" % sn)
        owner.reactor.pause(owner.reactor.monotonic() + 0.3)
        gcmd.respond_info("SA CAL: Sweep complete.")

        # ── Zero at far wall, home back to measure total travel ───────────────
        owner.gcode.run_script_from_command("MANUAL_STEPPER STEPPER=%s SET_POSITION=0" % sn)
        mcu_far = stepper.get_mcu_position()
        home_target = -(owner.selector_max_travel + 50.0)

        gcmd.respond_info("SA CAL: Homing back to measure total travel...")
        owner.gcode.run_script_from_command(
            "MANUAL_STEPPER STEPPER=%s MOVE=%.1f SPEED=%.1f STOP_ON_ENDSTOP=1"
            % (sn, home_target, owner.selector_homing_speed))
        owner.gcode.run_script_from_command("M400")

        mcu_home     = stepper.get_mcu_position()
        total_travel = abs(mcu_far - mcu_home) * step_dist
        owner.gcode.run_script_from_command("MANUAL_STEPPER STEPPER=%s SET_POSITION=0" % sn)

        gcmd.respond_info(
            "SA CAL: MCU steps far=%d  home=%d  delta=%d  step_dist=%.5fmm\n"
            "SA CAL: Total travel: %.2fmm"
            % (mcu_far, mcu_home, abs(mcu_far - mcu_home), step_dist, total_travel))

        # ── Step 8: Restore current and internal state ────────────────────────
        self._restore_selector_current(gcmd, sn)
        owner.motion._selector_position = 0.0
        owner.current_path = -1

        # ── Step 9: Calculate positions ───────────────────────────────────────
        n          = owner.num_paths
        end_offset = owner.selector_end_offset
        path_width = owner.path_width
        usable     = total_travel - end_offset

        if n == 1:
            positions = [0.0]
            spacing   = 0.0
        else:
            if usable < (n - 1) * 5.0:
                raise gcmd.error(
                    "SA CAL: Usable travel %.1fmm (total %.1fmm - offset %.1fmm) "
                    "too short for %d paths. "
                    "Check assembly or reduce selector_end_offset."
                    % (usable, total_travel, end_offset, n))
            spacing   = usable / float(n - 1)
            positions = [round(i * spacing, 2) for i in range(n)]

        offset_note = ""
        if end_offset != 0.0:
            offset_note = ("  end_offset %.2fmm  usable %.2fmm\n"
                           % (end_offset, usable))
        width_note  = ""
        if path_width > 0.0:
            width_note = (
                "  path_width configured %.1fmm  calculated %.2fmm  "
                "delta %.2fmm\n" % (path_width, spacing, abs(spacing - path_width)))

        pos_lines = "\n".join(
            "  Path %d: %.2fmm" % (i, p) for i, p in enumerate(positions))
        gcmd.respond_info(
            "SA CAL: Total travel %.2fmm → %d paths  spacing %.2fmm\n%s%s%s"
            % (total_travel, n, spacing, offset_note, width_note, pos_lines))

        owner._cal_data  = {'positions': positions, 'total_travel': total_travel,
                            'summary': ("Total travel %.2fmm over %d paths, "
                                        "spacing %.2fmm"
                                        % (total_travel, n, spacing)
                                        + NL + offset_note + width_note),
                            'at': None}
        owner._cal_state = 'sel_confirm'
        self._sel_confirm_render(gcmd)

    def _sel_confirm_render(self, gcmd):
        """Show the computed positions, with a button to drive to each one."""
        owner     = self.owner
        d         = owner._cal_data
        positions = d.get('positions') or []
        at        = d.get('at')

        lines = []
        for i, pos in enumerate(positions):
            lines.append("%s Path %d: %.2fmm"
                         % ("->" if at == i else "  ", i, pos))

        buttons = [("T%d" % i, "go:%d" % i,
                    "primary" if at == i else "secondary")
                   for i in range(len(positions))]
        buttons.append(("SAVE THESE", "yes", "primary"))
        buttons.append(("ADJUST", "no", "warning"))

        note = ("Press a path to drive the carriage there and check it lines "
                "up. The drive gear is released first, so nothing grips the "
                "filament while you look.")
        if at is not None:
            note = ("Carriage is at path %d. Check it is centred, then try "
                    "another or save." % at)

        self._emit_ui_prompt(
            gcmd, self._ui_title(),
            ("Accept these positions?" + NL + NL
             + str(d.get('summary', '')) + NL.join(lines) + NL + NL
             + note),
            buttons,
            footer=[("ABORT", "abort", "error")],
            columns=3)
        owner._cal_prompt = "Accept these positions?"

    # ── Chaining one calibration to the next ──────────────────────────────────
    #
    # Finishing a step used to end with a console line and a closed dialog. On
    # KlipperScreen that was survivable -- the guide panel is still underneath,
    # with its own Next button. In Mainsail there is no guide: the dialog closes
    # back to the dashboard and nothing says what to do next, which is what Mike
    # hit after accepting the selector positions.
    #
    # So the BACKEND offers the next step, as one more prompt. That works in
    # every UI at once and needs no panel code, which is the same reason the
    # prompts themselves are native.

    _CHAIN = [
        ('buzz_drive', "Drive motor direction",
         "Check the selector motor next?",
         "Same question for the other motor: it should move AWAY from the "
         "endstop first. Homing drives at that endstop, so a selector running "
         "backwards runs into the hard stop rather than the switch.",
         "BUZZ SELECTOR", "SA_BUZZ_CHECK MOTOR=selector"),

        ('buzz_selector', "Selector motor direction",
         "Test the endstop next?",
         "You move the carriage onto the switch by hand while the state is "
         "read back. Nothing is driven. Do it before homing -- homing is the "
         "first thing that trusts the switch, and it finds out by driving the "
         "carriage at it.",
         "TEST ENDSTOP", "SA_TEST_ENDSTOP DURATION=30"),

        ('endstop',    "Endstop test",
         "Home the selector next?",
         "Drives the carriage to the switch and calls that zero. Everything "
         "measured in millimetres from home depends on it.",
         "HOME SELECTOR", "SA_HOME"),

        ('home',       "Selector home",
         "Calibrate the selector positions next?",
         "Sweeps the rail to measure its travel, then divides it into path "
         "positions. Until it runs, the positions are guesses spaced 21mm "
         "apart.",
         "CALIBRATE SELECTOR", "SA_CALIBRATE_SELECTOR"),

        ('selector',   "Selector positions",
         "Calibrate the servo next?",
         "Finds the angle at which the drive gear grips. Needs filament at "
         "the gear on the selected path -- if there is none in yet, stop here "
         "and come back to it. Nothing downstream can move filament until the "
         "gear can hold it.",
         "CALIBRATE SERVO", "SA_CALIBRATE_SERVO"),

        ('servo',      "Servo engage angle",
         "Calibrate the drive motor next?",
         "Measures how far one motor turn moves filament. Everything that "
         "feeds or retracts is measured in those millimetres, so nothing "
         "downstream is trustworthy until it is set.",
         "CALIBRATE DRIVE", "SA_CALIBRATE_DRIVE"),

        ('drive',      "Drive rotation distance",
         "Calibrate encoder speed next?",
         "Finds the fastest feed the encoder can still count reliably, which "
         "is what the Bowden measurement then uses.",
         "CALIBRATE ENCODER SPEED", "SA_CALIBRATE_ENCODER_SPEED"),

        ('enc_speed',  "Encoder max speed",
         "Calibrate encoder mm/pulse next?",
         "Per path. Sets how far one encoder pulse means, which every slip "
         "check and every park depends on.",
         "CALIBRATE ENCODER T0", "SA_CALIBRATE_ENCODER TOOL=0"),

        ('encoder',    "Encoder mm/pulse",
         "Calibrate Bowden length next?",
         "Per path. Measures the tube from the drive gear to the toolhead, "
         "which is the distance a load feeds before it expects the filament "
         "to arrive.",
         "CALIBRATE BOWDEN T0", "SA_CALIBRATE_BOWDEN TOOL=0"),

        ('bowden',     "Bowden length",
         None, None, None, None),
    ]

    def _offer_command(self, gcmd, question, detail, label, cmd,
                       decline="STOP HERE"):
        """Leave a prompt behind that will run `cmd` if accepted.

        Every offer in this file goes through here. The three that existed
        before -- next step, next path, and the endstop retry -- had drifted
        into three copies of the same four lines, and a copy that forgets to
        set _cal_state is an offer whose button does nothing.
        """
        self.owner._cal_data  = {'_next_cmd': cmd}
        self.owner._cal_state = 'chain_next'
        head, _, why = str(detail).partition(NL + NL)
        self._prompt(
            gcmd, question,
            cmd,
            "SA_RESPOND VALUE=no",
            detail=head,
            expect=[why] if why.strip() else (),
            choices=[(label, "yes", "primary"),
                     (decline, "no", "secondary")])

    def _offer_retry(self, gcmd, question, detail, label, cmd):
        """Offer to run something again. Same shape, different intent:
        nothing has been achieved yet, so declining is not "stop here"."""
        self._offer_command(gcmd, question, detail, label, cmd,
                            decline="NOT NOW")

    def _offer_next_path(self, gcmd, kind, path, cmd_fmt, label):
        """Offer the same calibration on the next path, else move on.

        A per-path step is not finished when one path is done. Being asked
        about Bowden lengths after calibrating encoder 0 of six skips five
        paths silently, so the path loop is offered first and the chain only
        advances once the last one is done.
        """
        nxt = int(path) + 1
        if nxt >= int(self.owner.num_paths):
            self._offer_next(gcmd, kind)
            return
        self._offer_command(
            gcmd,
            "%s done. Do path %d next?" % (label, nxt),
            ("Path %d of %d complete. Each path is measured separately "
             "-- the remaining ones still hold their old values."
             % (int(path) + 1, int(self.owner.num_paths))),
            "PATH %d" % nxt, cmd_fmt % nxt)

    def _offer_next(self, gcmd, step):
        """After a calibration completes, offer the one that follows it."""
        entry = None
        for e in self._CHAIN:
            if e[0] == step:
                entry = e
                break
        if entry is None or entry[2] is None:
            self.owner._cal_chain = False
            gcmd.respond_info(
                "SA CAL: %s done — that is the last step."
                % (entry[1] if entry else step))
            return

        _key, done_label, question, why, btn_label, btn_cmd = entry
        self._offer_command(
            gcmd, question,
            ("%s saved." % done_label) + NL + NL + why,
            btn_label, btn_cmd)

    def _skip_step(self, gcmd):
        """Abandon the phase now waiting and offer the next step.

        Nothing is saved -- skipping is not answering. The step keeps whatever
        value it had, which is said out loud, because a skipped calibration
        that looked accepted is the failure this has to avoid.
        """
        step_n, step_name = self._current_step()
        entry = self._step_after(step_n) if step_n is not None else None
        self._clear()
        gcmd.respond_info(
            "SA CAL: %s skipped — nothing saved, it keeps its previous value."
            % (step_name or "Step"))
        if entry is None:
            gcmd.respond_info("SA CAL: That was the last step.")
            return
        self._offer_command(
            gcmd, entry[2] or ("Run %s next?" % entry[1]),
            entry[3] or "", entry[4] or "CONTINUE", entry[5])

    def _chain_respond(self, gcmd, state, value):
        owner = self.owner
        nxt = (owner._cal_data or {}).get('_next_cmd')
        self._clear()
        if not self._yes(value):
            owner._cal_chain = False
            gcmd.respond_info(
                "SA CAL: Stopped. Run the next step whenever you are ready.")
            return
        if nxt:
            # Set AFTER _clear(), which wipes the phase state between steps.
            # SA_HOME reads this to decide whether it is a step in a sequence
            # or just someone homing the selector.
            owner._cal_chain = True
            gcmd.respond_info("SA CAL: Starting %s..." % nxt)
            owner.gcode.run_script_from_command(nxt)

    # ── Selector: "no, I don't like these numbers" ────────────────────────────
    #
    # Rejecting the computed positions used to end the routine with "adjust
    # assembly or selector_end_offset and retry", which meant editing a config
    # file and running the whole sweep again to see the effect of a number you
    # were guessing at.
    #
    # The sweep measured total travel; that part is fine and worth keeping. It
    # is only the DIVISION of that travel that is in question, and that is
    # arithmetic -- so it can be redone instantly, as many times as needed,
    # with the resulting positions shown each time.

    _OFFSET_STEPS  = (0.5, 2.0, 10.0)
    _SPACING_STEPS = (0.1, 1.0, 5.0)

    def _sel_compute(self, total_travel, n, end_offset, spacing=None):
        """(positions, spacing) for a travel divided n ways."""
        usable = max(0.0, total_travel - end_offset)
        if n <= 1:
            return [0.0], 0.0
        sp = float(spacing) if spacing else usable / float(n - 1)
        return [round(i * sp, 2) for i in range(n)], sp

    def _sel_reject_menu(self, gcmd):
        owner = self.owner
        d     = owner._cal_data
        owner._cal_state = 'sel_reject'
        self._prompt(
            gcmd,
            "What do you want to change?",
            "SA_RESPOND VALUE=offset",
            "SA_RESPOND VALUE=spacing",
            "SA_RESPOND VALUE=resweep",
            detail=(
                "The sweep measured %.2fmm of travel. That measurement is "
                "probably fine -- it is how it gets divided that is in "
                "question, and that is just arithmetic, so it can be redone "
                "instantly." % d.get('total_travel', 0.0) + NL + NL
                + "END OFFSET  - hold some travel back before dividing, if "
                  "path 0 or the last path sits slightly off." + NL
                + "GATE WIDTH  - set the gap between paths directly, if you "
                  "know what it should measure." + NL
                + "SWEEP AGAIN - if the travel measurement itself looks wrong."),
            choices=[("END OFFSET",  "offset",  "primary"),
                     ("GATE WIDTH",  "spacing", "primary"),
                     ("SWEEP AGAIN", "resweep", "secondary")],
            columns=3)

    def _sel_tune_render(self, gcmd):
        """Show the positions the current offset/spacing would produce."""
        owner = self.owner
        d     = owner._cal_data
        mode  = d.get('_tune')
        tt    = float(d.get('total_travel', 0.0))
        n     = int(owner.num_paths)
        val   = float(d.get('_np_val', 0.0))

        if mode == 'offset':
            positions, spacing = self._sel_compute(tt, n, val)
            head = "End offset: %.2fmm  ->  spacing %.2fmm" % (val, spacing)
            steps = self._OFFSET_STEPS
        else:
            positions, spacing = self._sel_compute(tt, n, 0.0, spacing=val)
            head = "Gate width: %.2fmm  ->  last path at %.2fmm" % (
                val, positions[-1] if positions else 0.0)
            steps = self._SPACING_STEPS

        d['_preview'] = positions

        # Which path is being watched. Path 0 sits at zero under every scheme,
        # so it can never show a change; the last path has accumulated the most
        # and is where an error is easiest to see.
        watch = d.get('at')
        if watch is None or not (0 <= int(watch) < len(positions)):
            watch = len(positions) - 1
        watch = int(watch)
        d['at'] = watch

        # Drive there so the alignment moves with the number. Same idea as the
        # servo screen, which also moves before it renders.
        moved = ""
        if positions:
            try:
                owner.motion.servo_disengage()
                owner.motion.selector_move_to(positions[watch])
            except Exception as e:
                moved = NL + "Could not move the carriage: %s" % e

        buttons = [("%+g" % s,  "adj:%g" % s,  "secondary") for s in steps]
        buttons += [("%+g" % -s, "adj:%g" % -s, "secondary") for s in steps]
        buttons += [("T%d" % i, "go:%d" % i,
                     "primary" if i == watch else "secondary")
                    for i in range(len(positions))]
        buttons.append(("SAVE THESE", "yes", "primary"))
        buttons.append(("BACK", "back", "secondary"))

        pos_lines = NL.join(
            "%s Path %d: %.2fmm" % ("->" if i == watch else "  ", i, p)
            for i, p in enumerate(positions))
        over = ""
        if positions and positions[-1] > tt + 0.01:
            over = (NL + "WARNING: the last path is beyond the %.2fmm the "
                         "selector can travel." % tt)

        self._emit_ui_prompt(
            gcmd, "Selector Calibration",
            head + NL + NL + pos_lines + over + NL + NL
            + "Watching path %d — the carriage moves there on every change, "
              "so you can see it line up. Press another to watch that one "
              "instead." % watch + moved,
            buttons,
            footer=[("ABORT", "abort", "error")],
            columns=3)
        owner._cal_prompt = head

    def _sel_tune_respond(self, gcmd, value):
        owner = self.owner
        d     = owner._cal_data
        v     = str(value).strip().lower()

        if v.startswith('go:'):
            # Watch a different path. Changes nothing but where you are looking.
            try:
                idx = int(v.split(':', 1)[1])
            except ValueError:
                idx = -1
            if 0 <= idx < int(owner.num_paths):
                d['at'] = idx
            self._sel_tune_render(gcmd)
            return

        if v == 'back':
            self._sel_reject_menu(gcmd)
            return

        if self._yes(v):
            positions = d.get('_preview') or []
            for i, pos in enumerate(positions):
                owner._selector_positions[i] = pos
                self._save_variable('selector_position_%d' % i, '%.2f' % pos)
            if d.get('_tune') == 'offset':
                owner.selector_end_offset = float(d.get('_np_val', 0.0))
                self._save_variable('sa_selector_end_offset',
                                    '%.2f' % owner.selector_end_offset)
            self._clear()
            gcmd.respond_info(
                "SA CAL: Selector positions saved — effective now, no restart "
                "needed.\nRun SA_HOME then SA_SELECT TOOL=N to check each one.")
            owner.motion.selector_home()
            self._offer_next(gcmd, 'selector')
            return

        self._clear()
        gcmd.respond_info("SA CAL: Nothing saved.")

    # ── Servo ─────────────────────────────────────────────────────────────────
    #
    # Ordered to protect the servo, not to be quick.
    #
    # A servo driven against a hard stop strips its gears in seconds, and an arm
    # fitted at the wrong angle turns the whole travel into one long hard stop.
    # So nothing sweeps until the arm is OFF; the arm goes back on only at the
    # end that is mechanically safe by definition -- resting against the
    # servo body, away from the drive gear -- and from there only the far
    # angle is searched, stepping toward the gear and stopping the moment it
    # grips.
    #
    # The disengaged angle is therefore never "calibrated": it is defined by
    # where the arm is fitted. Only the engaged angle is found.

    _SERVO_STEPS = (1.0, 5.0, 10.0)

    def calibrate_servo(self, gcmd):
        owner = self.owner
        owner._cal_data = {
            'dis': float(owner.servo_disengaged_angle),
            'eng': float(owner.servo_engaged_angle),
        }
        owner._cal_state = 'srv_armoff'
        self._prompt(
            gcmd,
            "Is the servo arm removed?",
            "SA_RESPOND VALUE=yes",
            detail=(
                "TAKE THE SERVO ARM OFF before continuing." + NL + NL
                + "With the arm fitted, moving the servo can drive it into the "
                  "mechanism and strip the gears -- and if the arm was "
                  "fitted at the wrong angle, its whole travel is a hard stop."
                + NL + NL
                + "Undo the arm screw and lift the arm off the spline. Leave "
                  "the screw somewhere you will find it."),
            choices=[("ARM IS OFF", "yes", "primary")])

    def _srv_respond(self, gcmd, state, value):
        owner = self.owner
        d     = owner._cal_data

        def move(angle):
            owner.gcode.run_script_from_command(
                "SET_SERVO SERVO=%s ANGLE=%.1f"
                % (owner._servo_short_name(), angle))

        if state == 'srv_armoff':
            # Safe now: nothing is attached to the spline.
            move(d['dis'])
            owner._cal_state = 'srv_armon'
            self._prompt(
                gcmd,
                "Fit the arm at the rest position",
                "SA_RESPOND VALUE=yes",
                detail=(
                    "The servo is now at %.0f deg -- the DISENGAGED end."
                    % d['dis'] + NL + NL
                    + "Fit the arm so it rests against the servo body, on "
                      "the side AWAY from the drive gear, and tighten the "
                      "screw." + NL + NL
                    + "That position is what 'disengaged' means, so it is not "
                      "measured -- it is defined by where you fit the arm. "
                      "Only the gripping angle is searched from here."),
                choices=[("ARM IS FITTED", "yes", "primary")])
            return

        if state == 'srv_armon':
            # Start the search AT the rest angle and walk toward the gear, so
            # the first move is zero and every move after it is small.
            d['_np_val'] = d['dis']
            owner._cal_state = 'srv_find'
            self._srv_render(gcmd)
            return

        if state == 'srv_find':
            if str(value).strip().lower() == 'flip':
                # A reversed servo is not fixed by stepping the other way: the
                # arm is fitted near one extreme, so searching back past it
                # runs out of travel almost immediately. The arm has to come
                # off and go back on at the mirrored end -- and it must come
                # off FIRST, because driving it across the full range while
                # fitted is exactly the hard-stop crash this routine exists to
                # avoid.
                span = float(getattr(owner, 'servo_max_angle', 180.0))
                d['dis'] = max(0.0, min(span, span - d['dis']))
                d['eng'] = max(0.0, min(span, span - d['eng']))
                owner._cal_state = 'srv_armoff'
                self._prompt(
                    gcmd,
                    "Take the arm off again",
                    "SA_RESPOND VALUE=yes",
                    detail=(
                        "This servo runs the other way, so the rest position "
                        "is at the opposite end of its travel." + NL + NL
                        + "REMOVE THE ARM before continuing -- it will be "
                          "driven to %.0f deg, and crossing that far with the "
                          "arm fitted is what strips the gears." % d['dis']
                        + NL + NL
                        + "You will refit it at the new rest position, then "
                          "search from there."),
                    choices=[("ARM IS OFF", "yes", "primary")])
                return
            if self._yes(value):
                eng = float(d.get('_np_val', d['eng']))
                owner.servo_engaged_angle = eng
                self._save_variable('sa_servo_engaged_angle', '%.1f' % eng)
                self._save_variable('sa_servo_disengaged_angle',
                                    '%.1f' % d['dis'])
                move(d['dis'])
                self._clear()
                gcmd.respond_info(
                    "SA CAL: Servo saved — engaged %.1f deg, disengaged %.1f "
                    "deg. Effective now, no restart needed." % (eng, d['dis']))
                self._offer_next(gcmd, 'servo')
                return
            self._clear()
            move(d['dis'])
            gcmd.respond_info(
                "SA CAL: Servo calibration cancelled. Returned to %.0f deg."
                % d['dis'])
            return

    def _srv_render(self, gcmd):
        """Re-ask the engage question at the current angle, moving there first.

        Every angle is approached from the rest position rather than stepped to
        from the last one. A step of a few degrees does not give the arm enough
        of a run-up to overcome the torque it needs once it is loaded, so it
        simply does not arrive and the reading on screen is a lie about where
        the arm is. Returning to rest first lets it build the momentum to get
        there.
        """
        owner = self.owner
        d     = owner._cal_data
        ang   = float(d.get('_np_val', d['dis']))
        srv   = owner._servo_short_name()
        rest  = float(d['dis'])

        if abs(ang - rest) > 0.05:
            owner.gcode.run_script_from_command(
                "SET_SERVO SERVO=%s ANGLE=%.1f" % (srv, rest))
            owner.reactor.pause(
                owner.reactor.monotonic() + owner.servo_move_delay)
        owner.gcode.run_script_from_command(
            "SET_SERVO SERVO=%s ANGLE=%.1f" % (srv, ang))

        toward = "up" if d['eng'] >= d['dis'] else "down"
        buttons = []
        for step in self._SERVO_STEPS:
            delta = step if d['eng'] >= d['dis'] else -step
            buttons.append(("%+g" % delta, "adj:%g" % delta, "secondary"))
        for step in self._SERVO_STEPS:
            delta = -step if d['eng'] >= d['dis'] else step
            buttons.append(("%+g" % delta, "adj:%g" % delta, "secondary"))
        buttons.append(("GRIPS — SAVE", "yes", "primary"))
        buttons.append(("WRONG WAY", "flip", "warning"))

        self._emit_ui_prompt(
            gcmd, "Servo Calibration",
            ("Angle: %.1f deg" % ang) + NL + NL
            + ("Step %s until the drive gear just grips the filament, then "
               "save. Move in small steps: past the grip point the arm is "
               "pushing against the mechanism." % toward) + NL
            + "The arm returns to rest before each move -- it needs the run-up "
              "to reach a loaded angle." + NL
            + ("Rest position is %.0f deg; previously saved grip was %.0f deg."
               % (d['dis'], d['eng'])) + NL
            + "If the arm is moving AWAY from the gear, press WRONG WAY.",
            buttons,
            footer=[("CANCEL", "abort", "error")],
            columns=3)
        owner._cal_prompt = "Servo: %.1f deg" % ang


    # ── Endstop: prove the mapping, not just the movement ─────────────────────

    _END_TIMEOUT = 180.0

    def _end_meaning(self, triggered):
        """What a reading is supposed to mean about the carriage."""
        return ("the carriage is ON the switch, compressing it" if triggered
                else "the carriage is OFF the switch, free to move")

    def _end_word(self, triggered):
        return "TRIGGERED" if triggered else "open"

    def start_endstop_test(self, gcmd):
        owner = self.owner
        state, name = owner._selector_endstop_state()
        if state is None:
            gcmd.respond_info(
                "SA: Could not read an endstop for the selector (looked for "
                "'%s').%s    Check that the selector's manual_stepper has an "
                "endstop_pin in hardware.cfg." % (name, NL))
            return
        owner._cal_data = {
            'name': name,
            'first': bool(state),
            'seen': [],
            'deadline': owner.reactor.monotonic() + self._END_TIMEOUT,
        }
        owner._cal_state = 'end_wait'
        self._end_render_wait(gcmd)
        self._end_arm(owner)

    def _end_arm(self, owner, delay=0.25):
        """Re-arm the poll. A delayed_gcode rather than a loop, so the mutex is
        free between reads and the buttons below actually work."""
        try:
            owner.gcode.run_script_from_command(
                "UPDATE_DELAYED_GCODE ID=sa_endstop_poll DURATION=%.2f" % delay)
        except Exception:
            logging.exception("SA CAL: could not arm the endstop poll")

    def _end_disarm(self, owner):
        try:
            owner.gcode.run_script_from_command(
                "UPDATE_DELAYED_GCODE ID=sa_endstop_poll DURATION=0")
        except Exception:
            pass

    def _end_render_wait(self, gcmd):
        d = self.owner._cal_data
        now = bool(d['first']) if not d['seen'] else bool(d['seen'][-1])
        want = not now
        self._emit_ui_prompt(
            gcmd, self._ui_title(),
            ("Endstop test" + NL + NL
             + "Reading now: %s" % self._end_word(now) + NL
             + "That should mean %s." % self._end_meaning(now) + NL + NL
             + "Move the selector carriage by hand until it is %s."
               % ("ON the switch" if want else "OFF the switch") + NL
             + "Nothing is driven. This waits for the reading to change."
             + NL + NL
             + "If it never changes: check the wiring and the "
               "SA_SELECTOR_STOP pin."),
            [],
            footer=[("STOP", "abort", "error")])

    def poll_endstop(self, gcmd):
        """One read. Called by the delayed_gcode while the test is running."""
        owner = self.owner
        if (owner._cal_state or '') not in ('end_wait',):
            return
        d = owner._cal_data
        now, _name = owner._selector_endstop_state()
        if now is None:
            self._end_arm(owner)
            return

        prev = bool(d['first']) if not d['seen'] else bool(d['seen'][-1])
        if bool(now) == prev:
            if owner.reactor.monotonic() > d['deadline']:
                owner._cal_state = 'end_stuck'
                self._emit_ui_prompt(
                    gcmd, self._ui_title(),
                    ("Endstop test" + NL + NL
                     + "The reading never changed from %s."
                       % self._end_word(prev) + NL + NL
                     + "Either the carriage was not moved onto the switch, or "
                       "the switch is not reaching the board." + NL + NL
                     + "Check the wiring and the SA_SELECTOR_STOP pin, then "
                       "try again."),
                    [("TRY AGAIN", "restart", "primary")],
                    footer=[("STOP", "abort", "error")])
                return
            self._end_arm(owner)
            return

        # It changed. Stop and ask what it means.
        d['seen'].append(bool(now))
        owner._cal_state = 'end_confirm'
        self._end_render_confirm(gcmd)

    def _end_render_confirm(self, gcmd):
        d = self.owner._cal_data
        now = bool(d['seen'][-1])
        last = len(d['seen']) >= 2
        self._emit_ui_prompt(
            gcmd, self._ui_title(),
            ("Endstop test  (%d of 2)" % len(d['seen']) + NL + NL
             + "The reading changed to %s." % self._end_word(now) + NL + NL
             + "That should mean %s." % self._end_meaning(now) + NL + NL
             + "Is that where the carriage actually is?" + NL + NL
             + "If it is the other way round the switch is wired inverted. "
               "Answering NO writes the correction and tells you what to do."),
            [("YES, THAT IS RIGHT", "yes", "primary"),
             ("NO, IT IS BACKWARDS", "no", "warning"),
             ("START OVER", "restart", "secondary")],
            footer=[("STOP", "abort", "error")],
            columns=2)
        self.owner._cal_prompt = (
            "Endstop reads %s" % self._end_word(now))

    def _end_respond(self, gcmd, state, value):
        owner = self.owner
        v = str(value).strip().lower()

        if v == 'restart':
            self._end_disarm(owner)
            self._clear()
            self.start_endstop_test(gcmd)
            return

        if state == 'end_stuck':
            self._end_disarm(owner)
            self._clear()
            gcmd.respond_info("SA CAL: Endstop test stopped.")
            return

        if state != 'end_confirm':
            return

        if not self._yes(v):
            # Say what is wrong and how to correct it. Deliberately not doing
            # it here: this is a claim about physical wiring, inverting the pin
            # is not the only valid fix, and a config edit made on one button
            # press is hard to notice later.
            self._end_disarm(owner)
            self._clear()
            pin = owner.selector_endstop_pin() or "(could not read it)"
            bare = pin.replace('!', '')
            flipped = ('^!' + bare.lstrip('^')) if '!' not in pin else bare
            section = "manual_stepper %s" % owner.selector_stepper_name.split()[-1]
            gcmd.respond_info(
                "SA CAL: Endstop reads backwards. endstop_pin is %s; "
                "inverting it gives %s." % (pin, flipped))
            self._emit_ui_prompt(
                gcmd, self._ui_title(),
                ("Endstop test — reads backwards" + NL + NL
                 + "The switch reports the opposite of where the carriage "
                   "actually is. Homing trusts this reading, so as it stands "
                   "it will either stop immediately and call that position "
                   "zero, or drive into the hard stop waiting for a signal "
                   "that never comes." + NL + NL
                 + "Right now:" + NL
                 + "  endstop_pin: %s" % pin + NL + NL
                 + "Two ways to fix it. Either invert the pin:" + NL
                 + "  endstop_pin: %s" % flipped + NL
                 + "or move the switch wire between its NC and NO contacts."
                 + NL + NL
                 + "hardware.cfg is regenerated by the installer, so put the "
                   "change in user.cfg to keep it:" + NL
                 + "  [%s]" % section + NL
                 + "  endstop_pin: %s" % flipped + NL + NL
                 + "Then FIRMWARE_RESTART and run this test again."),
                [("RUN IT AGAIN", "restart", "primary")],
                footer=[("STOP", "abort", "error")])
            owner._cal_state = 'end_stuck'
            return

        # Correct. One state proven; go round for the other, or finish.
        d = owner._cal_data
        if len(d['seen']) >= 2:
            self._end_disarm(owner)
            self._clear()
            gcmd.respond_info(
                "SA CAL: ENDSTOP OK — both states read the right way round.")
            self._offer_next(gcmd, 'endstop')
            return

        d['deadline'] = owner.reactor.monotonic() + self._END_TIMEOUT
        owner._cal_state = 'end_wait'
        self._end_render_wait(gcmd)
        self._end_arm(owner)

    # ── Motor direction ───────────────────────────────────────────────────────

    def ask_direction(self, gcmd, motor, expect):
        """Ask which way a motor just moved, and fix it if it was wrong.

        The answer is acted on, not just reported: "wrong way" flips the saved
        direction and re-buzzes so the operator can confirm the fix rather than
        take it on trust.
        """
        owner = self.owner
        owner._cal_data  = {'motor': motor}
        owner._cal_state = 'dir_confirm'
        inverted = bool(getattr(owner, '%s_dir_invert' % motor, False))

        self._prompt(
            gcmd,
            "Did the %s motor move the right way?" % motor,
            "SA_RESPOND VALUE=yes",
            "SA_RESPOND VALUE=no",
            "SA_RESPOND VALUE=again",
            detail="Currently: %s." % ("INVERTED" if inverted else "normal"),
            expect=[expect,
                    "The move is short and happens once, so it is easy to "
                    "miss. BUZZ AGAIN repeats it and changes nothing."],
            warn=["WRONG WAY flips this motor and saves it, so answer it "
                  "rather than guessing -- a wrong answer inverts a motor "
                  "that was fine."],
            choices=[("RIGHT WAY", "yes", "primary"),
                     ("WRONG WAY", "no", "warning"),
                     ("BUZZ AGAIN", "again", "secondary")],
            columns=3)

    def _dir_respond(self, gcmd, state, value):
        owner = self.owner
        motor = (owner._cal_data or {}).get('motor', 'drive')

        if str(value).strip().lower() == 'again':
            # Re-running the whole command re-buzzes AND re-asks, so the
            # operator is never left looking at a stale question. Nothing is
            # decided here: the direction, the saved value and the chain
            # position are all exactly as they were.
            self._clear()
            gcmd.respond_info("SA CAL: Buzzing the %s motor again..." % motor)
            owner.gcode.run_script_from_command(
                "SA_BUZZ_CHECK MOTOR=%s" % motor)
            return

        if self._yes(value):
            self._clear()
            gcmd.respond_info(
                "SA CAL: %s direction confirmed. Nothing changed." % motor)
            # Confirming closed the dialog and left the operator on the
            # dashboard with nothing saying what came next -- the same
            # dead-end that accepting the selector positions used to have.
            # WRONG WAY never had it, because re-buzzing reopens the prompt.
            self._offer_next(gcmd, 'buzz_%s' % motor)
            return

        owner.gcode.run_script_from_command(
            "SA_SET_DIRECTION MOTOR=%s" % motor)
        self._clear()
        gcmd.respond_info(
            "SA CAL: Direction flipped and saved. Buzzing again — check it now "
            "moves the right way.")
        owner.gcode.run_script_from_command(
            "SA_BUZZ_CHECK MOTOR=%s" % motor)

    def _sel_respond(self, gcmd, state, value):
        owner = self.owner

        if state == 'sel_reject':
            v = str(value).strip().lower()
            if v == 'resweep':
                self._clear()
                gcmd.respond_info("SA CAL: Sweeping again...")
                self.calibrate_selector_auto(gcmd)
                return
            if v in ('offset', 'spacing'):
                d = owner._cal_data
                d['_tune'] = v
                if v == 'offset':
                    d['_np_val'] = float(getattr(owner, 'selector_end_offset', 0.0))
                else:
                    n  = int(owner.num_paths)
                    tt = float(d.get('total_travel', 0.0))
                    d['_np_val'] = (tt / float(n - 1)) if n > 1 else 0.0
                owner._cal_state = 'sel_tune'
                self._sel_tune_render(gcmd)
                return
            self._clear()
            gcmd.respond_info("SA CAL: Nothing saved.")
            return

        if state == 'sel_tune':
            self._sel_tune_respond(gcmd, value)
            return

        if state == 'sel_confirm':
            v = str(value).strip().lower()
            if v.startswith('go:'):
                # Drive to one position so it can be eyeballed. Nothing is
                # saved by looking, so this stays in the same phase and comes
                # straight back to the same screen.
                try:
                    idx = int(v.split(':', 1)[1])
                except ValueError:
                    idx = -1
                positions = owner._cal_data.get('positions') or []
                if 0 <= idx < len(positions):
                    try:
                        owner.motion.servo_disengage()
                        owner.motion.selector_move_to(positions[idx])
                        owner._cal_data['at'] = idx
                        gcmd.respond_info(
                            "SA CAL: Moved to path %d (%.2fmm)."
                            % (idx, positions[idx]))
                    except Exception as e:
                        gcmd.respond_info(
                            "SA CAL: Could not move to path %d: %s" % (idx, e))
                self._sel_confirm_render(gcmd)
                return
            if self._yes(value):
                positions = owner._cal_data['positions']
                for i, pos in enumerate(positions):
                    owner._selector_positions[i] = pos
                    self._save_variable('selector_position_%d' % i, '%.2f' % pos)
                self._clear()
                gcmd.respond_info(
                    "SA CAL: Selector positions saved immediately — "
                    "effective now, no restart needed.")
                owner.motion.selector_home()
                self._offer_next(gcmd, 'selector')
            else:
                # NO _clear() here. The measured travel lives in _cal_data and
                # the retune arithmetic needs it -- clearing first left every
                # recomputed position at 0.00mm, since total_travel had gone.
                #
                # Not a dead end any more. The sweep's travel measurement
                # stands; only its division into path positions is in
                # question, and that is arithmetic -- so it is redone here,
                # instantly, as many times as needed, rather than sending the
                # operator to edit a config file and sweep again.
                self._sel_reject_menu(gcmd)

    # ══════════════════════════════════════════════════════════════════════════
    # SA_CALIBRATE_DRIVE
    # ══════════════════════════════════════════════════════════════════════════

    def calibrate_drive(self, gcmd):
        """Phase 0 — intro, ask which path has filament."""
        owner = self.owner

        if owner._cal_state is not None:
            self._busy(gcmd)
            return

        if not owner._selector_homed:
            gcmd.respond_info("SA CAL: Selector not homed — homing now...")
            owner.motion.selector_home()

        gcmd.respond_info(
            "SA DRIVE CALIBRATION\n"
            "====================\n"
            "Calibrates drive motor rotation_distance — one motor, one-time setup.\n"
            "\n"
            "Requirements: filament loaded past drive gear on one path. Calipers or ruler.")

        owner._cal_data  = {'attempt': 0, 'best_rd': None, 'path': None,
                            'original_rd': None, 'original_sd': None}
        owner._cal_state = 'drv_path'

        self._prompt(gcmd,
            "Which path has filament loaded past the drive gear? (0-%d)"
            % (owner.num_paths - 1),
            "SA_RESPOND VALUE=0",
            "SA_RESPOND VALUE=1  (etc.)",
            choices=self._path_choices(),
            columns=3)

    def _drv_respond(self, gcmd, state, value):
        owner  = self.owner
        motion = owner.motion
        data   = owner._cal_data

        if state == 'drv_path':
            try:
                path = int(value)
            except ValueError:
                gcmd.respond_info(
                    "SA CAL: Enter a path number (0-%d)." % (owner.num_paths - 1))
                return
            if not (0 <= path < owner.num_paths):
                gcmd.respond_info("SA CAL: Path %d out of range." % path)
                return

            gcmd.respond_info("SA CAL: Selecting path %d..." % path)
            self._safe_selector_move(motion, owner._selector_positions[path])
            owner.current_path = path
            # Gear closed so the knob can feed the filament, motor released so
            # it is not holding against you. Both are needed to set the tip by
            # hand, and engaging without releasing is what made the old
            # instruction impossible to carry out.
            motion.servo_engage()
            motion.drive_disable()

            drive_obj = owner.printer.lookup_object(owner.drive_stepper_name)
            steppers  = drive_obj.get_steppers()
            best_rd   = steppers[0].get_rotation_distance()[0] if steppers else 22.0
            orig_sd   = steppers[0].get_step_dist() if steppers else None

            data.update({'path': path, 'best_rd': best_rd, 'attempt': 0,
                         'original_rd': best_rd, 'original_sd': orig_sd,
                         'steppers': steppers, 'cmd_mm': 100.0})
            owner._cal_state = 'drv_mark'

            self._prompt(gcmd,
                "Set the filament tip flush with the gate exit.",
                "SA_RESPOND VALUE=yes",
                detail=(
                    "Turn the drive knob by hand until the very tip of the "
                    "filament is level with the exit of the gate -- not "
                    "protruding, not recessed." + NL + NL
                    + "The drive gear is holding the filament and the motor is "
                      "released, so the knob feeds it either way." + NL + NL
                    + "The gate exit is the measurement datum, so no tape or "
                      "pen is needed: whatever sticks out afterwards is "
                      "exactly how far it travelled."),
                choices=[("TIP IS FLUSH", "yes", "primary")])

        elif state == 'drv_mark':
            attempt        = data['attempt'] + 1
            data['attempt'] = attempt
            path   = data['path']
            cmd_mm = data.get('cmd_mm', 100.0)

            gcmd.respond_info(
                "SA CAL: Attempt %d/3 — commanding %.1fmm..." % (attempt, cmd_mm))
            enc = owner._encoder(path)
            enc.set_direction(forward=True)
            enc.reset_distance()
            motion.drive_move(cmd_mm, speed=owner.feed_speed * 0.5)
            motion.drive_disable()
            data['last_cmd_mm'] = cmd_mm

            owner._cal_state = 'drv_meas'
            self._prompt(gcmd,
                "How much filament is sticking out of the gate?",
                "SA_RESPOND VALUE=100.0  (replace with actual mm)",
                detail=(
                    "Measure from the gate exit to the tip. The tip started "
                    "flush, so that length is exactly how far the filament "
                    "travelled." + NL + NL
                    + "Commanded %.1fmm. Dial in what you measured."
                      % data.get('last_cmd_mm', 100.0)),
                numeric={'value': 100.0, 'unit': 'mm'})

        elif state == 'drv_meas':
            try:
                measured = float(value)
            except ValueError:
                gcmd.respond_info("SA CAL: Enter a number (e.g. 103.5).")
                return
            if measured <= 0.0:
                gcmd.respond_info("SA CAL: Must be > 0.")
                return

            cmd_mm   = data.get('last_cmd_mm', 100.0)
            orig_rd  = data['original_rd']
            attempt  = data['attempt']
            target   = 100.0
            error    = abs(measured - target)
            pct      = error / target * 100.0

            # True rotation_distance based on original rd and actual ratio this pass
            new_rd   = orig_rd * (measured / cmd_mm)
            # Command this distance next pass so stepper outputs 100mm
            next_cmd = cmd_mm * (target / measured)

            data['best_rd'] = new_rd
            data['cmd_mm']  = next_cmd

            done = (attempt >= 3)
            gcmd.respond_info(
                "SA CAL: Pass %d/3 — commanded %.1fmm  measured %.2fmm  "
                "error %.2fmm (%.1f%%)\n"
                "  rotation_distance: %.4f → %.4f  next_cmd: %.1fmm%s"
                % (attempt, cmd_mm, measured, error, pct, orig_rd, new_rd, next_cmd,
                   "  ✓ done" if done else ""))

            if done:
                motion.servo_disengage()
                owner._cal_state = 'drv_save'
                self._prompt(gcmd,
                    "Save rotation_distance=%.4f?" % new_rd,
                    "SA_RESPOND VALUE=yes",
                    "SA_RESPOND VALUE=no")
            else:
                # Back to the datum. The previous pass left the tip proud of
                # the gate, and the motor holding it, so neither the reference
                # nor the knob is usable until both are reset.
                motion.drive_disable()
                owner._cal_state = 'drv_mark'
                self._prompt(gcmd,
                    "Set the tip flush with the gate exit again.",
                    "SA_RESPOND VALUE=yes",
                    detail=(
                        "Turn the drive knob by hand to pull the filament back "
                        "until its tip is level with the gate exit." + NL + NL
                        + "Each pass measures from that same datum, which is "
                          "what lets the three attempts be compared."),
                    choices=[("TIP IS FLUSH", "yes", "primary")])

        elif state == 'drv_save':
            new_rd   = data['best_rd']
            orig_rd  = data.get('original_rd') or new_rd
            self._clear()

            if self._yes(value):
                self._save_variable('drive_rotation_distance', '%.4f' % new_rd)
                ok, result = self._patch_hardware_cfg(
                    'manual_stepper sa_drive', 'rotation_distance', '%.4f' % new_rd)
                if ok:
                    gcmd.respond_info(
                        "SA CAL: rotation_distance=%.4f written to hardware.cfg.\n"
                        "Restart Klipper — 100mm will equal 100mm." % new_rd)
                else:
                    gcmd.respond_info(
                        "SA CAL: rotation_distance=%.4f saved to variables.cfg.\n"
                        "Could not auto-update hardware.cfg (%s).\n"
                        "Manually set rotation_distance: %.4f in "
                        "[manual_stepper sa_drive] then restart Klipper."
                        % (new_rd, result, new_rd))
                self._offer_next(gcmd, 'drive')
            else:
                gcmd.respond_info(
                    "SA CAL: Not saved. rotation_distance remains %.4f." % orig_rd)

    # ══════════════════════════════════════════════════════════════════════════
    # SA_CALIBRATE_ENCODER
    # ══════════════════════════════════════════════════════════════════════════

    def calibrate_encoder(self, gcmd):
        """Phase 0 — select path, engage, prompt to mark filament."""
        owner = self.owner
        path  = gcmd.get_int('TOOL', minval=0, maxval=owner.num_paths - 1)

        if owner._cal_state is not None:
            self._busy(gcmd)
            return

        if not owner._selector_homed:
            gcmd.respond_info("SA CAL: Selector not homed — homing now...")
            owner.motion.selector_home()

        gcmd.respond_info(
            "SA ENCODER CALIBRATION — Path %d\n"
            "==================================\n"
            "Feeds until encoder reads 100mm, you measure actual — 3 passes.\n"
            "\n"
            "Requirements: filament through drive gear AND encoder for path %d.\n"
            "~400mm of free filament needed." % (path, path))

        gcmd.respond_info("SA CAL: Selecting path %d..." % path)
        self._safe_selector_move(owner.motion, owner._selector_positions[path])
        owner.current_path = path
        owner.motion.servo_engage()

        enc = owner._encoder(path)
        owner._cal_data  = {
            'path':         path,
            'attempt':      0,
            'best_mpp':     enc.mm_per_pulse,
            'original_mpp': enc.mm_per_pulse,
        }
        owner._cal_state = 'enc_mark_%d' % path

        self._prompt(gcmd,
            "Mark the filament at the encoder exit, then confirm ready.",
            "SA_RESPOND VALUE=yes")

    def _enc_respond(self, gcmd, state, value):
        owner  = self.owner
        motion = owner.motion
        data   = owner._cal_data
        path   = int(state.rsplit('_', 1)[-1])
        enc    = owner._encoder(path)

        if state.startswith('enc_mark_'):
            attempt        = data['attempt'] + 1
            data['attempt'] = attempt
            target         = 100.0
            max_travel     = 600.0
            poll_interval  = 0.05   # seconds between encoder checks
            cal_speed      = owner.feed_speed * 0.5

            # Apply current best mm_per_pulse so encoder counts correctly
            enc.mm_per_pulse = data['best_mpp']
            enc.set_direction(forward=True)
            enc.reset_distance()

            dn = owner._drv_name()
            motion.servo_engage()
            motion._cancel_timeout(dn)
            owner.gcode.run_script_from_command(
                "MANUAL_STEPPER STEPPER=%s ENABLE=1" % dn)

            gcmd.respond_info(
                "SA CAL: Attempt %d/3 — stepping until encoder reads "
                "%.0fmm (mm_per_pulse=%.5f)..." % (attempt, target, data['best_mpp']))

            # Step-by-step: motor stops fully between steps so encoder
            # pulses are delivered one-by-one (no CAN batching issue).
            # Fast approach until 80% of target, then 3mm precision steps.
            fast_step     = 10.0
            slow_step     = 3.0
            slow_threshold = target * 0.8
            travelled     = 0.0

            while enc.get_distance() < target and travelled < max_travel:
                step = slow_step if enc.get_distance() >= slow_threshold else fast_step
                motion.drive_move(step, speed=cal_speed)
                travelled += step

            enc_reading = enc.get_distance()

            if enc_reading < 3.0:
                motion.servo_disengage()
                motion.drive_disable()
                self._clear()
                raise gcmd.error(
                    "SA CAL: Encoder %d not responding — %.2fmm counted after "
                    "%.0fmm travel. Check wiring and filament grip."
                    % (path, enc_reading, max_travel))

            gcmd.respond_info(
                "SA CAL: Motor stopped — encoder reads %.2fmm." % enc_reading)

            # Hold servo + motor torque while user measures
            dn = owner._drv_name()
            motion._cancel_timeout(dn)
            owner.gcode.run_script_from_command(
                "MANUAL_STEPPER STEPPER=%s ENABLE=1" % dn)
            data['enc_reading'] = enc_reading
            owner._cal_state = 'enc_meas_%d' % path

            self._prompt(gcmd,
                "Servo engaged, drive holding. Measure from the encoder exit "
                "back to your mark - that is how far the filament travelled "
                "(target 100mm).",
                "SA_RESPOND VALUE=100.0  (replace with actual mm)",
                numeric={'value': 100.0, 'unit': 'mm'})

        elif state.startswith('enc_meas_'):
            # Release motor torque but keep servo engaged —
            # user needs grip to reposition filament with the drive knob
            motion.drive_disable()

            try:
                actual = float(value)
            except ValueError:
                gcmd.respond_info("SA CAL: Enter a number (e.g. 199.5).")
                return
            if actual <= 0.0:
                gcmd.respond_info("SA CAL: Must be > 0.")
                return

            current_mpp = data['best_mpp']
            attempt     = data['attempt']
            enc_reading = data['enc_reading']
            # Use actual enc_reading (not assumed target) so formula is valid
            # whether motor stopped at target or was halted by max_travel limit
            new_mpp     = current_mpp * (actual / enc_reading)
            correction  = abs(new_mpp - current_mpp) / current_mpp * 100.0

            data['best_mpp'] = new_mpp
            # Apply immediately so next pass uses corrected mpp
            enc.mm_per_pulse = new_mpp

            done = (attempt >= 3)
            gcmd.respond_info(
                "SA CAL: Pass %d/3 — encoder %.2fmm  actual %.2fmm  "
                "mpp correction %.2f%%\n"
                "  mm_per_pulse: %.5f → %.5f%s"
                % (attempt, enc_reading, actual, correction,
                   current_mpp, new_mpp, "  ✓ done" if done else ""))

            if done:
                motion.servo_disengage()
                owner._cal_state = 'enc_save_%d' % path
                self._prompt(gcmd,
                    "Save mm_per_pulse=%.5f?" % new_mpp,
                    "SA_RESPOND VALUE=yes",
                    "SA_RESPOND VALUE=no")
            else:
                # Servo still engaged — use knob to re-mark filament position
                owner._cal_state = 'enc_mark_%d' % path
                self._prompt(gcmd,
                    "Servo engaged — use knob to reposition filament to new mark, "
                    "then confirm ready.",
                    "SA_RESPOND VALUE=yes")

        elif state.startswith('enc_save_'):
            new_mpp  = data['best_mpp']
            orig_mpp = data.get('original_mpp') or new_mpp
            self._clear()

            if self._yes(value):
                enc.mm_per_pulse = new_mpp
                self._save_variable('encoder_mpp_%d' % path, '%.5f' % new_mpp)
                ok, result = self._patch_hardware_cfg(
                    'sa_encoder %d' % path, 'mm_per_pulse', '%.5f' % new_mpp)
                if ok:
                    gcmd.respond_info(
                        "SA CAL: Encoder %d mm_per_pulse=%.5f written to "
                        "hardware.cfg — restart Klipper to apply." % (path, new_mpp))
                else:
                    gcmd.respond_info(
                        "SA CAL: Encoder %d mm_per_pulse=%.5f saved to "
                        "variables.cfg. Could not auto-update hardware.cfg (%s)."
                        % (path, new_mpp, result))
                self._offer_next_path(gcmd, 'encoder', path,
                                      'SA_CALIBRATE_ENCODER TOOL=%d',
                                      'Encoder mm/pulse')
            else:
                enc.mm_per_pulse = orig_mpp
                gcmd.respond_info(
                    "SA CAL: Not saved. mm_per_pulse remains %.5f." % orig_mpp)

    # ══════════════════════════════════════════════════════════════════════════
    # SA_CALIBRATE_ENCODER_SPEED
    # ══════════════════════════════════════════════════════════════════════════

    def calibrate_encoder_speed(self, gcmd):
        """Find the fastest feed each encoder still counts accurately.

        With no TOOL, every channel is tested in turn. The faults this finds on
        a fresh build are per channel -- a tight tube, a dirty wheel, a
        marginal connector -- so testing one says little about the other five,
        and the comparison between them is what points at the bad one.
        """
        owner  = self.owner
        motion = owner.motion

        if owner._cal_state is not None:
            raise gcmd.error(
                "SA CAL: Calibration in progress (state=%s). SA_RESPOND VALUE=abort"
                % owner._cal_state)

        one = gcmd.get_int('TOOL', None, minval=0, maxval=owner.num_paths - 1)
        queue = [one] if one is not None else list(range(owner.num_paths))

        if not owner._selector_homed:
            gcmd.respond_info("SA CAL: Homing selector...")
            motion.selector_home()

        gcmd.respond_info(
            "SA ENCODER SPEED CALIBRATION — %s\n"
            "===========================================\n"
            "Requires filament through the drive gear and encoder.\n"
            "Tests 25→200mm/s, 3 passes each, 100mm per pass."
            % ("path %d" % one if one is not None
               else "all %d paths" % owner.num_paths))

        owner._cal_data = {'queue': queue, 'results': {}, 'single': one is not None}
        self._encspeed_next(gcmd)

    # 25s to 200 where most machines land, coarser above for the builds
    # optimised for fast feeds.
    #
    # 200 was not an arbitrary ceiling: a 100mm move at the drive's stock
    # accel of 400mm/s^2 peaks at sqrt(a*D) = 200mm/s exactly, so the old
    # ladder ended where the old fixed distance ran out. Going higher needs
    # the distance to grow with the speed, which _encspeed_distance does.
    _ENC_SPEEDS = [25, 50, 75, 100, 125, 150, 175, 200,
                   250, 300, 350, 400, 450, 500]

    # How much cruise to buy on top of the ramp. A move that only touches the
    # speed measures the ramp; holding it for half the ramp again means most of
    # what the encoder counted happened at the speed on the label.
    _ENC_CRUISE_FRAC = 0.5

    # Bound on a pass. The filament goes from the gate into the Bowden and
    # comes straight back, so the tube it is feeding is the real limit -- taken
    # per path from SA_CALIBRATE_BOWDEN, not guessed at globally.
    _ENC_BOWDEN_FRAC = 0.70    # leave the last third of the tube alone
    _ENC_ABS_MAX     = 900.0   # and never more than this, calibrated or not
    _ENC_MIN_DIST    = 100.0

    def _encspeed_cap(self, path):
        """Longest pass this path may drive, in mm."""
        try:
            bowden = float(self.owner._bowden_lengths[path])
        except Exception:
            bowden = 0.0
        if bowden <= 0.0:
            # Bowden not calibrated yet: stay short enough to be safe in any
            # tube worth building.
            return 400.0
        return max(self._ENC_MIN_DIST,
                   min(self._ENC_ABS_MAX, bowden * self._ENC_BOWDEN_FRAC))

    def _drive_accel(self):
        """The drive stepper's configured acceleration, mm/s^2."""
        try:
            settings = self.owner.printer.lookup_object(
                'configfile').get_status(self.owner.reactor.monotonic())['settings']
            name = self.owner.drive_stepper_name.lower()
            return float(settings.get(name, {}).get('accel', 0.0)) or 0.0
        except Exception:
            return 0.0

    def _encspeed_distance(self, speed, cap):
        """How far to drive so *speed* is held, not merely touched.

        A move ramps up, maybe cruises, then ramps down. Accelerating to v and
        back costs v^2/a of travel and spends none of it at v. The cruise on top
        is what the test is actually reading.

        Returns (distance, cruise_mm). Distance is None when it does not fit in
        *cap*, and the second value is then the distance it would have needed --
        so the rung is reported as untested rather than passed on a speed the
        move never reached.
        """
        accel = self._drive_accel()
        if accel <= 0.0:
            return self._ENC_MIN_DIST, 0.0    # accel unknown: behave as before
        ramp = (speed * speed) / accel        # up and down together
        want = ramp * (1.0 + self._ENC_CRUISE_FRAC)
        if want <= self._ENC_MIN_DIST:
            # The floor already dwarfs the ramp; all the slack is cruise.
            return self._ENC_MIN_DIST, self._ENC_MIN_DIST - ramp
        if want > cap:
            return None, want
        return round(want, 0), want - ramp

    def _encspeed_accel_for(self, speed, dist):
        """A practical accel that would fit *speed* into *dist*.

        Rounded up to the next 50: the exact figure sits on the boundary, where
        the move fits only by floating-point luck, and it is not a number anyone
        would type into a config anyway.
        """
        if dist <= 0.0:
            return 0.0
        exact = (speed * speed) * (1.0 + self._ENC_CRUISE_FRAC) / dist
        return math.ceil(exact / 50.0) * 50.0

    def _encspeed_explain(self):
        return ("Each pass is long enough to reach the speed on the label and "
                "then hold it, so most of what the encoder counted happened "
                "at that speed rather than on the way up to it. The "
                "percentages are how far the encoder count was from the "
                "distance driven -- one per pass. Under 5% passes; two of "
                "three must pass.")

    def _encspeed_next(self, gcmd):
        """Run the sweep for the next queued path, then stop on its result."""
        owner = self.owner
        d     = owner._cal_data
        if not d.get('queue'):
            self._encspeed_summary(gcmd)
            return
        path = d['queue'].pop(0)
        self._encspeed_run(gcmd, path)

    def _encspeed_arm(self, delay=0.05):
        try:
            self.owner.gcode.run_script_from_command(
                "UPDATE_DELAYED_GCODE ID=sa_encspeed_step DURATION=%.2f" % delay)
        except Exception:
            logging.exception("SA CAL: could not arm the encoder speed step")

    def _encspeed_disarm(self):
        try:
            self.owner.gcode.run_script_from_command(
                "UPDATE_DELAYED_GCODE ID=sa_encspeed_step DURATION=0")
        except Exception:
            pass

    def _encspeed_run(self, gcmd, path):
        """Begin the sweep for one path. The passes happen one per call."""
        owner  = self.owner
        motion = owner.motion
        d      = owner._cal_data

        motion.servo_disengage()
        motion.selector_move_to(owner._selector_positions[path])
        owner.current_path = path
        motion.servo_engage()

        d.update({'at': path, 'si': 0, 'ai': 0, 'errors': [],
                  'per_speed': [], 'max_pass': 0})
        owner._cal_state = 'enc_speed_run'
        self._encspeed_show(gcmd)
        self._encspeed_arm()

    def _encspeed_show(self, gcmd, note=""):
        d    = self.owner._cal_data
        rows = ["  %3dmm/s  %s" % (sp, txt) for sp, txt in d.get('per_speed', [])]
        si   = d.get('si', 0)
        speed = (self._ENC_SPEEDS[si] if si < len(self._ENC_SPEEDS) else 0)
        dist, cruise = d.get('dist', 0.0), d.get('cruise', 0.0)
        geom = ("  (%.0fmm pass, %.0fmm of it at speed)" % (dist, cruise)
                if dist else "")
        head = (note or ("Now: %dmm/s, pass %d of 3%s"
                         % (speed, d.get('ai', 0) + 1, geom)))
        self._emit_ui_prompt(
            self.owner.gcode if gcmd is None else gcmd, self._ui_title(),
            ("Encoder speed test — path %d" % d.get('at', 0) + NL + NL
             + self._encspeed_explain() + NL + NL
             + head
             + (NL + NL + NL.join(rows) if rows else "")),
            [],
            footer=[("STOP", "abort", "error")])

    def encspeed_step(self, gcmd):
        """One 100mm pass. Called by the delayed_gcode while a sweep runs."""
        owner  = self.owner
        motion = owner.motion
        d      = owner._cal_data
        if (owner._cal_state or '') != 'enc_speed_run':
            return                      # aborted, or moved on

        si, ai = d.get('si', 0), d.get('ai', 0)
        if si >= len(self._ENC_SPEEDS):
            self._encspeed_finish(gcmd)
            return

        speed = self._ENC_SPEEDS[si]
        path  = d['at']
        cap   = self._encspeed_cap(path)
        dist, cruise = self._encspeed_distance(speed, cap)

        if dist is None:
            # Will not fit in the tube this path feeds. Say so, and say what
            # would change it -- the travel needed falls as v^2/a, so accel is
            # the lever here, not a longer move.
            d['per_speed'].append(
                (speed, "not tested - needs %.0fmm, this path allows %.0fmm "
                        "(accel %.0f would fit it)"
                        % (cruise, cap, self._encspeed_accel_for(speed, cap))))
            d['errors'] = []
            d['ai'] = 0
            d['si'] = si + 1
            if d['si'] >= len(self._ENC_SPEEDS):
                self._encspeed_finish(gcmd)
                return
            self._encspeed_show(gcmd)
            self._encspeed_arm()
            return

        d['dist']   = dist
        d['cruise'] = cruise

        enc   = owner._encoder(path)
        enc.set_direction(forward=True)
        enc.reset_distance()
        motion.drive_move(dist, speed=float(speed))
        owner.reactor.pause(owner.reactor.monotonic() + 0.15)
        err = abs(enc.get_distance() - dist) / dist
        d['errors'].append(err * 100.0)
        enc.set_direction(forward=False)
        enc.reset_distance()
        motion.drive_move(-dist, speed=25.0)
        owner.reactor.pause(owner.reactor.monotonic() + 0.2)

        d['ai'] = ai + 1
        if d['ai'] < 3:
            self._encspeed_show(gcmd)
            self._encspeed_arm()
            return

        errors = d['errors']
        passes = sum(1 for e in errors if e <= 5.0)
        ok     = passes >= 2
        gcmd.respond_info(
            "  path %d  %3dmm/s: %s  (off by %s%%  avg %.1f%%)"
            % (path, speed, "PASS" if ok else "FAIL",
               [round(e, 1) for e in errors], sum(errors) / len(errors)))
        d['per_speed'].append(
            (speed, "%s  off by %s%%" % ("PASS" if ok else "FAIL",
                                         [round(e, 1) for e in errors])))
        d['errors'] = []
        d['ai'] = 0
        if ok:
            d['max_pass'] = speed
            d['si'] = si + 1
            if d['si'] >= len(self._ENC_SPEEDS):
                self._encspeed_finish(gcmd)
                return
            self._encspeed_show(gcmd)
            self._encspeed_arm()
        else:
            self._encspeed_finish(gcmd)

    def _encspeed_finish(self, gcmd):
        """This path is done: stop, save, and wait to be read."""
        owner  = self.owner
        motion = owner.motion
        d      = owner._cal_data
        path   = d['at']
        max_pass = d.get('max_pass', 0)

        self._encspeed_disarm()
        motion.servo_disengage()

        safe = max_pass * 0.80 if max_pass else 0.0
        d.setdefault('results', {})[path] = {
            'max': max_pass, 'safe': safe, 'rows': list(d.get('per_speed', []))}
        if max_pass:
            self._save_variable('encoder_max_speed_%d' % path, '%.1f' % safe)

        owner._cal_state = 'enc_speed_done'
        more = bool(d.get('queue'))
        verdict = ("Fastest reliable speed: %dmm/s  ->  using %.0fmm/s (80%%)."
                   % (max_pass, safe) if max_pass else
                   "No speed counted accurately, including the slowest. That "
                   "points at this channel rather than at the speed: check the "
                   "encoder wheel, its wiring, and that mm_per_pulse is "
                   "calibrated for this path.")
        buttons = [("NEXT PATH" if more else "SEE ALL RESULTS", "next", "primary"),
                   ("REPEAT PATH %d" % path, "again", "secondary")]
        self._emit_ui_prompt(
            gcmd, self._ui_title(),
            ("Encoder speed test — path %d done" % path + NL + NL
             + verdict + NL + NL
             + NL.join("  %3dmm/s  %s" % (sp, txt)
                       for sp, txt in d.get('per_speed', []))
             + NL + NL + self._encspeed_explain()),
            buttons,
            footer=[("STOP", "abort", "error")])

    def _encspeed_summary(self, gcmd):
        """All channels side by side, with a way to redo any of them."""
        owner = self.owner
        d     = owner._cal_data
        res   = d.get('results') or {}

        rows = []
        for p in sorted(res):
            r = res[p]
            rows.append("  T%d  %s" % (
                p,
                ("%3dmm/s  (using %.0f)" % (r['max'], r['safe'])) if r['max']
                else "FAILED at every speed"))

        speeds = [r['max'] for r in res.values() if r['max']]
        note = ""
        if speeds and len(speeds) > 1:
            if min(speeds) < max(speeds) * 0.6:
                note = (NL + NL
                        + "T%d is well below the others. That is usually "
                          "mechanical -- a tight tube, a dirty or slipping "
                          "encoder wheel, or filament dragging -- rather than "
                          "the encoder being wrong."
                        % min(res, key=lambda k: res[k]['max'] or 0))
            else:
                note = (NL + NL + "The channels agree closely, which is what a "
                                  "healthy build looks like.")

        buttons = [("RETEST T%d" % p, "re:%d" % p, "secondary")
                   for p in sorted(res)]
        buttons.append(("DONE", "done", "primary"))
        owner._cal_state = 'enc_speed_all'
        self._emit_ui_prompt(
            gcmd, self._ui_title(),
            ("Encoder speed — all paths" + NL + NL
             + NL.join(rows) + note + NL + NL
             + "Inspect, clean or repair a path and retest just that one; the "
               "others keep their results."),
            buttons,
            footer=[("STOP", "abort", "error")],
            columns=3)

    def _encspeed_respond(self, gcmd, state, value):
        owner = self.owner
        d     = owner._cal_data
        v     = str(value).strip().lower()

        if state == 'enc_speed_done':
            if v == 'again':
                self._encspeed_run(gcmd, int(d.get('at', 0)))
                return
            self._encspeed_next(gcmd)
            return

        if state == 'enc_speed_all':
            if v.startswith('re:'):
                try:
                    p = int(v.split(':', 1)[1])
                except ValueError:
                    return
                self._encspeed_run(gcmd, p)
                return
            best = [r['safe'] for r in (d.get('results') or {}).values()
                    if r.get('safe')]
            self._clear()
            if best:
                # The Bowden blast uses one number for the machine, so the
                # slowest channel sets it -- the fastest would outrun the worst
                # path every time it was used.
                slowest = min(best)
                self._save_variable('encoder_max_speed', '%.1f' % slowest)
                gcmd.respond_info(
                    "SA CAL: encoder_max_speed=%.0fmm/s saved (the slowest "
                    "channel; a shared speed has to suit the worst path)."
                    % slowest)
            self._offer_next(gcmd, 'enc_speed')
            return

    # ══════════════════════════════════════════════════════════════════════════
    # SA_CALIBRATE_BOWDEN
    # ══════════════════════════════════════════════════════════════════════════

    def calibrate_bowden(self, gcmd):
        """Phase 0 — validate sensors, prompt for estimated tube length."""
        owner = self.owner
        path  = gcmd.get_int('TOOL', minval=0, maxval=owner.num_paths - 1)

        if owner._cal_state is not None:
            self._busy(gcmd)
            return

        if not owner._selector_homed:
            gcmd.respond_info("SA CAL: Selector not homed — homing now...")
            owner.motion.selector_home()

        gcmd.respond_info(
            "SA BOWDEN CALIBRATION — Path %d\n"
            "================================" % path)

        if not owner._extruder_sensor_names[path]:
            raise gcmd.error(
                "SA CAL: No extruder_sensor_%d configured.\n"
                "Add to [autoloader] in hardware.cfg:\n"
                "  extruder_sensor_%d : filament_switch_sensor extruder_sensor_%d"
                % (path, path, path))

        if not owner._entry_sensor_active(path):
            raise gcmd.error(
                "SA CAL: No filament at entry of path %d. Load a spool first." % path)

        owner._cal_data  = {'path': path, 'trials': []}
        owner._cal_state = 'bow_est_%d' % path

        self._prompt(gcmd,
            "Enter estimated Bowden tube length for path %d (mm). "
            "Over-estimate is safer — approach uses 90%% first." % path,
            "SA_RESPOND VALUE=800  (replace with your estimate)",
            numeric={'value': float(owner._bowden_lengths[path]
                                    if path < len(owner._bowden_lengths)
                                    else 800.0),
                     'unit': 'mm', 'steps': (100.0, 10.0, 1.0)})

    def _bow_respond(self, gcmd, state, value):
        owner  = self.owner
        motion = owner.motion
        data   = owner._cal_data
        path   = int(state.rsplit('_', 1)[-1])

        if state.startswith('bow_est_'):
            try:
                estimated = float(value)
            except ValueError:
                gcmd.respond_info("SA CAL: Enter a number (e.g. 800).")
                return
            if estimated <= 0.0:
                gcmd.respond_info("SA CAL: Must be > 0.")
                return

            # Three-phase approach speeds (48V / TMC5160)
            # Blast speed: use calibrated encoder_max_speed if available, else 100mm/s safe default
            sv = owner.printer.lookup_object('save_variables', None)
            saved_max = float(sv.allVariables.get('encoder_max_speed', 0)) if sv else 0
            # encoder_max_speed tested at 100mm near tube entrance (low friction).
            # Bowden blast pushes full tube depth — apply 0.75x for tube friction load.
            blast_speed = (saved_max * 0.75) if saved_max > 0 else 75.0
            quick_speed    = 50.0              # 65–82.5% — no sensor check
            approach_speed = owner.feed_speed  # 82.5%+ — sensor polling

            # Distances scale with user's estimate:
            #   blast = 75%, quick = half of remainder (12.5%), approach = final 12.5%+
            blast_end  = estimated * 0.75
            quick_end  = blast_end + (estimated - blast_end) * 0.5   # midpoint of remainder
            # Sensor polling from quick_end; overshoot budget = 20% beyond estimated
            inch_limit = estimated * 0.20

            gcmd.respond_info(
                "SA CAL: Running 3 trials\n"
                "  Blast  %.0f–%.0fmm @ %.0fmm/s (no sensor)\n"
                "  Quick  %.0f–%.0fmm @ %.0fmm/s (no sensor)\n"
                "  Approach %.0fmm+ @ %.0fmm/s with sensor polling\n"
                "  NOTE: accuracy depends on your estimate being close to actual length."
                % (0, blast_end, blast_speed,
                   blast_end, quick_end, quick_speed,
                   quick_end, approach_speed))

            # Select path and engage servo once — stays engaged for all 3 trials
            motion.servo_disengage()
            motion.selector_move_to(owner._selector_positions[path])
            owner.current_path = path
            motion.servo_engage()

            enc = owner._encoder(path)
            retract_speed = blast_speed * 0.5

            def _retract_to_clear(fast_dist):
                """Retract fast_dist at retract_speed, then 5mm pulses at 25mm/s
                until encoder goes quiet (filament tip clears encoder).
                Max 20 slow pulses (100mm) before giving up."""
                if fast_dist > 0:
                    motion.drive_move(-fast_dist, speed=retract_speed)
                enc.set_direction(forward=False)
                for _ in range(20):
                    enc.reset_distance()
                    motion.drive_move(-5.0, speed=25.0)
                    owner.reactor.pause(owner.reactor.monotonic() + 0.15)
                    if abs(enc.get_distance()) < 0.5:
                        break
                enc.set_direction(forward=True)
                enc.reset_distance()

            # Pre-run: clear any filament stub sitting in encoder before trial 1
            gcmd.respond_info("SA CAL: Clearing encoder — retracting until filament clears...")
            _retract_to_clear(0.0)   # no fast phase — just slow pulses from current position
            gcmd.respond_info("SA CAL: Encoder cleared — starting 3 trials.")

            for trial in range(3):
                gcmd.respond_info("SA CAL: === Trial %d/3 ===" % (trial + 1))

                enc.set_direction(forward=True)
                enc.reset_distance()

                # Phase 1: blast to 75% — single move, no sensor check
                motion.drive_move(blast_end, speed=blast_speed)

                # Phase 2: quick to midpoint of remainder — single move, no sensor check
                motion.drive_move(quick_end - blast_end, speed=quick_speed)

                # Phase 3: sensor polling from quick_end until triggered or overshoot limit
                triggered = False
                inched    = 0.0
                while not triggered and inched < inch_limit:
                    motion.drive_move(owner.feed_step_size, speed=approach_speed)
                    inched += owner.feed_step_size
                    owner.reactor.pause(owner.reactor.monotonic() + owner.sensor_delay)
                    if owner._extruder_sensor_active(path):
                        triggered = True

                if not triggered:
                    motion.servo_disengage()
                    self._clear()
                    raise gcmd.error(
                        "SA CAL: Extruder sensor path %d not triggered within %.0fmm of "
                        "your estimate (%.0fmm). Re-run with a larger estimate."
                        % (path, inch_limit, estimated))

                length = enc.get_distance()
                gcmd.respond_info("SA CAL: Sensor triggered at %.2fmm." % length)
                data['trials'].append(length)

                # Retract 95% fast, then slow-pulse until encoder goes quiet
                # Stops before overshooting drive gears — no fixed overshoot distance
                _retract_to_clear(length * 0.95)
                owner.reactor.pause(owner.reactor.monotonic() + 0.3)

            motion.servo_disengage()

            trials     = data['trials']
            avg_length = sum(trials) / len(trials)
            spread     = max(trials) - min(trials)

            gcmd.respond_info(
                "SA CAL: Bowden path %d — trials %s\n"
                "  Average: %.2fmm  Spread: %.2fmm%s"
                % (path, [round(x, 2) for x in trials], avg_length, spread,
                   "  <- high, check sensor bounce" if spread > 3.0 else ""))

            # Update live state and persist immediately
            owner._bowden_lengths[path] = avg_length
            self._save_variable('bowden_length_%d' % path, '%.2f' % avg_length)
            self._clear()
            gcmd.respond_info(
                "SA CAL: bowden_length_%d=%.2fmm saved — "
                "effective immediately, no restart needed." % (path, avg_length))
            self._offer_next_path(gcmd, 'bowden', path,
                                  'SA_CALIBRATE_BOWDEN TOOL=%d', 'Bowden length')
