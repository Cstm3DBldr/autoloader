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

import sys, os as _os, re
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

        # A real answer closes the dialog; the next phase raises its own.
        self.close_ui_prompt(gcmd)

        try:
            if state.startswith('chain_'):
                self._chain_respond(gcmd, state, val)
            elif state.startswith('srv_'):
                self._srv_respond(gcmd, state, val)
            elif state.startswith('dir_'):
                self._dir_respond(gcmd, state, val)
            elif state.startswith('sel_'):
                self._sel_respond(gcmd, state, val)
            elif state.startswith('drv_'):
                self._drv_respond(gcmd, state, val)
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

    def _emit_ui_prompt(self, gcmd, title, text, buttons, footer=(),
                        columns=None):
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
            columns=kw.get('columns'))

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

    def _ui_title(self):
        """Short heading for the prompt dialog, from the current phase."""
        st = (self.owner._cal_state or '').lower()
        if st.startswith('chain_'):
            return "Calibration"
        if st.startswith('srv_'):
            return "Servo Calibration"
        if st.startswith('dir_'):
            return "Motor Direction"
        if st.startswith('sel_'):
            return "Selector Calibration"
        if st.startswith('drv_'):
            return "Drive Calibration"
        if st.startswith('enc_'):
            return "Encoder Calibration"
        if st.startswith('bow_'):
            return "Bowden Calibration"
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

        owner._cal_data  = {'positions': positions, 'total_travel': total_travel}
        owner._cal_state = 'sel_confirm'

        self._prompt(gcmd,
            "Accept these positions?",
            "SA_RESPOND VALUE=yes",
            "SA_RESPOND VALUE=no",
            detail=("Total travel %.2fmm over %d paths, spacing %.2fmm"
                    % (total_travel, n, spacing)
                    + NL + offset_note + width_note + pos_lines))

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
        ('selector',   "Selector positions",
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
        self.owner._cal_data = {'_next_cmd': cmd_fmt % nxt}
        self.owner._cal_state = 'chain_next'
        self._prompt(
            gcmd,
            "%s done. Do path %d next?" % (label, nxt),
            cmd_fmt % nxt,
            "SA_RESPOND VALUE=no",
            detail=("Path %d of %d complete. Each path is measured separately "
                    "-- the remaining ones still hold their old values."
                    % (int(path) + 1, int(self.owner.num_paths))),
            choices=[("PATH %d" % nxt, "yes", "primary"),
                     ("STOP HERE", "no", "secondary")])

    def _offer_next(self, gcmd, step):
        """After a calibration completes, offer the one that follows it."""
        entry = None
        for e in self._CHAIN:
            if e[0] == step:
                entry = e
                break
        if entry is None or entry[2] is None:
            gcmd.respond_info(
                "SA CAL: %s done — that is the last step."
                % (entry[1] if entry else step))
            return

        _key, done_label, question, why, btn_label, btn_cmd = entry
        self.owner._cal_data = {'_next_cmd': btn_cmd}
        self.owner._cal_state = 'chain_next'
        self._prompt(
            gcmd, question,
            btn_cmd,
            "SA_RESPOND VALUE=no",
            detail=("%s saved." % done_label) + NL + NL + why,
            choices=[(btn_label, "yes", "primary"),
                     ("STOP HERE", "no", "secondary")])

    def _chain_respond(self, gcmd, state, value):
        owner = self.owner
        nxt = (owner._cal_data or {}).get('_next_cmd')
        self._clear()
        if not self._yes(value):
            gcmd.respond_info(
                "SA CAL: Stopped. Run the next step whenever you are ready.")
            return
        if nxt:
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
            "What is wrong with them?",
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
                + "SPACING     - set the gap between paths directly, if you "
                  "know what it should measure." + NL
                + "SWEEP AGAIN - if the travel measurement itself looks wrong."),
            choices=[("END OFFSET",  "offset",  "primary"),
                     ("SPACING",     "spacing", "primary"),
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
            head = "Spacing: %.2fmm  ->  last path at %.2fmm" % (
                val, positions[-1] if positions else 0.0)
            steps = self._SPACING_STEPS

        d['_preview'] = positions
        buttons = [("%+g" % s,  "adj:%g" % s,  "secondary") for s in steps]
        buttons += [("%+g" % -s, "adj:%g" % -s, "secondary") for s in steps]
        buttons.append(("SAVE THESE", "yes", "primary"))
        buttons.append(("BACK", "back", "secondary"))

        pos_lines = NL.join("  Path %d: %.2fmm" % (i, p)
                            for i, p in enumerate(positions))
        over = ""
        if positions and positions[-1] > tt + 0.01:
            over = (NL + "WARNING: the last path is beyond the %.2fmm the "
                         "selector can travel." % tt)

        self._emit_ui_prompt(
            gcmd, "Selector Calibration",
            head + NL + NL + pos_lines + over,
            buttons,
            footer=[("ABORT", "abort", "error")],
            columns=3)
        owner._cal_prompt = head

    def _sel_tune_respond(self, gcmd, value):
        owner = self.owner
        d     = owner._cal_data
        v     = str(value).strip().lower()

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
    # selector body, away from the drive gear -- and from there only the far
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
                  "selector body and strip the gears -- and if the arm was "
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
                    + "Fit the arm so it rests against the selector body, on "
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
                return
            self._clear()
            move(d['dis'])
            gcmd.respond_info(
                "SA CAL: Servo calibration cancelled. Returned to %.0f deg."
                % d['dis'])
            return

    def _srv_render(self, gcmd):
        """Re-ask the engage question at the current angle, moving there first."""
        owner = self.owner
        d     = owner._cal_data
        ang   = float(d.get('_np_val', d['dis']))
        owner.gcode.run_script_from_command(
            "SET_SERVO SERVO=%s ANGLE=%.1f"
            % (owner._servo_short_name(), ang))

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
            + ("Rest position is %.0f deg; previously saved grip was %.0f deg."
               % (d['dis'], d['eng'])) + NL
            + "If the arm is moving AWAY from the gear, press WRONG WAY.",
            buttons,
            footer=[("CANCEL", "abort", "error")],
            columns=3)
        owner._cal_prompt = "Servo: %.1f deg" % ang

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
            detail=(expect + NL + NL
                    + "Currently: %s. Answering NO flips it, saves it, and "
                      "buzzes again so you can check."
                      % ("INVERTED" if inverted else "normal")),
            choices=[("RIGHT WAY", "yes", "primary"),
                     ("WRONG WAY", "no", "warning")])

    def _dir_respond(self, gcmd, state, value):
        owner = self.owner
        motor = (owner._cal_data or {}).get('motor', 'drive')

        if self._yes(value):
            self._clear()
            gcmd.respond_info(
                "SA CAL: %s direction confirmed. Nothing changed." % motor)
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
            if self._yes(value):
                positions = owner._cal_data['positions']
                for i, pos in enumerate(positions):
                    owner._selector_positions[i] = pos
                    self._save_variable('selector_position_%d' % i, '%.2f' % pos)
                self._clear()
                gcmd.respond_info(
                    "SA CAL: Selector positions saved immediately — "
                    "effective now, no restart needed.\n"
                    "Run SA_HOME then SA_SELECT TOOL=N to verify each position.")
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
            motion.servo_engage()

            drive_obj = owner.printer.lookup_object(owner.drive_stepper_name)
            steppers  = drive_obj.get_steppers()
            best_rd   = steppers[0].get_rotation_distance()[0] if steppers else 22.0
            orig_sd   = steppers[0].get_step_dist() if steppers else None

            data.update({'path': path, 'best_rd': best_rd, 'attempt': 0,
                         'original_rd': best_rd, 'original_sd': orig_sd,
                         'steppers': steppers, 'cmd_mm': 100.0})
            owner._cal_state = 'drv_mark'

            self._prompt(gcmd,
                "Mark the filament at the encoder exit (tape or pen). Then confirm ready.",
                "SA_RESPOND VALUE=yes")

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
                "Measure from the encoder exit back to your mark - that is how far the filament travelled (target: 100mm).",
                "SA_RESPOND VALUE=100.0  (replace with actual mm)",
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
                owner._cal_state = 'drv_mark'
                self._prompt(gcmd,
                    "Re-mark the filament at its new position, then confirm ready.",
                    "SA_RESPOND VALUE=yes")

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
        """Find the max feed speed at which the encoder counts accurately.

        Steps through speeds [25, 50, 75, 100, 125, 150, 175, 200] mm/s.
        Each speed: run 100mm forward, compare encoder reading to commanded
        distance.  3 tries per speed — need 2/3 within tolerance to pass.
        Stops at first failing speed.  Saves safe_speed (max_pass * 0.8)
        to variables.cfg as 'encoder_max_speed'.
        """
        owner  = self.owner
        motion = owner.motion
        path   = gcmd.get_int('TOOL', 0, minval=0, maxval=owner.num_paths - 1)

        if owner._cal_state is not None:
            raise gcmd.error(
                "SA CAL: Calibration in progress (state=%s). SA_RESPOND VALUE=abort"
                % owner._cal_state)

        if not owner._selector_homed:
            gcmd.respond_info("SA CAL: Homing selector...")
            motion.selector_home()

        gcmd.respond_info(
            "SA ENCODER SPEED CALIBRATION — Path %d\n"
            "===========================================\n"
            "Requires filament through drive gear and encoder.\n"
            "Tests speeds 25→200mm/s, 3 tries each, 100mm per try.\n"
            "Stops at first failing speed. Safe speed (80%%) saved."
            % path)

        motion.servo_disengage()
        motion.selector_move_to(owner._selector_positions[path])
        owner.current_path = path
        motion.servo_engage()

        enc        = owner._encoder(path)
        test_dist  = 100.0
        tolerance  = 0.05   # 5% max error per try
        test_speeds = [25, 50, 75, 100, 125, 150, 175, 200]
        retract_speed = 25.0
        max_pass   = 0

        for speed in test_speeds:
            trial_errors = []
            passes = 0
            for attempt in range(3):
                enc.set_direction(forward=True)
                enc.reset_distance()
                motion.drive_move(test_dist, speed=float(speed))
                owner.reactor.pause(owner.reactor.monotonic() + 0.15)
                enc_reading = enc.get_distance()
                error = abs(enc_reading - test_dist) / test_dist
                trial_errors.append(error * 100.0)
                if error <= tolerance:
                    passes += 1
                # Retract at safe low speed — accuracy not needed here
                enc.set_direction(forward=False)
                enc.reset_distance()
                motion.drive_move(-test_dist, speed=retract_speed)
                owner.reactor.pause(owner.reactor.monotonic() + 0.2)

            avg_err = sum(trial_errors) / len(trial_errors)
            passed  = passes >= 2
            gcmd.respond_info(
                "  %3dmm/s: %s  (errors: %s  avg %.1f%%)"
                % (speed,
                   "PASS" if passed else "FAIL",
                   [round(e, 1) for e in trial_errors],
                   avg_err))

            if passed:
                max_pass = speed
            else:
                break   # no point testing faster speeds

        motion.servo_disengage()

        if max_pass == 0:
            gcmd.respond_info(
                "SA CAL: FAILED at all speeds. Check encoder wiring / mm_per_pulse.")
            return

        safe_speed = max_pass * 0.80
        self._save_variable('encoder_max_speed', '%.1f' % safe_speed)
        gcmd.respond_info(
            "SA CAL: Max reliable speed %dmm/s → safe speed %.0fmm/s (80%%).\n"
            "Saved as encoder_max_speed — Bowden cal blast speed updated automatically."
            % (max_pass, safe_speed))
        self._offer_next(gcmd, 'enc_speed')

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
