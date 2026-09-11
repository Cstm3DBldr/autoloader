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

import ast as _ast
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
            elif state.startswith('sen_'):
                self._sen_respond(gcmd, state, val)
            elif state.startswith('end_'):
                self._end_respond(gcmd, state, val)
            elif state.startswith('dir_'):
                self._dir_respond(gcmd, state, val)
            elif state.startswith('sel_'):
                self._sel_respond(gcmd, state, val)
            elif state.startswith('vf_'):
                self._vf_respond(gcmd, state, val)
            elif state.startswith('drv_'):
                self._drv_respond(gcmd, state, val)
            # Before the generic enc_ branch: these start with it too.
            elif state.startswith('enc_speed'):
                self._encspeed_respond(gcmd, state, val)
            elif state.startswith('enc_'):
                self._enc_respond(gcmd, state, val)
            elif state.startswith('bow_'):
                self._bow_respond(gcmd, state, val)
            elif state.startswith('thg_unload_'):
                self._thg_unload_respond(
                    gcmd, int(state.rsplit('_', 1)[-1]), val)
            elif state.startswith('thg_'):
                self._thg_respond(gcmd, state, val)
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
        self._sen_disarm()
        self._end_disarm(self.owner)
        self.owner.motion.servo_disengage()
        self._clear()

    def _select_path(self, gcmd, path):
        """Put the carriage on *path* before driving any filament through it.

        Homing alone is NOT this. selector_home() leaves the carriage on the
        endstop, which is position 0 -- T0's gate -- so a routine that only
        homes drives every path at T0. And a routine that homes only when the
        position is untrusted drives at wherever the LAST operation left the
        carriage, which is worse because it usually looks right.

        That is exactly what happened on 2026-09-11: step 12 parked paths 3, 4
        and 5 in turn, leaving the carriage at T5, and SA_CALIBRATE_TOOLHEAD
        TOOL=3 then hunted for path 3's filament at path 5's gate. It had
        passed on T0, T1 and T2 only because each had been parked immediately
        before being measured, so the carriage happened to be in the right
        place.

        Every routine that drives filament for a given path goes through here.
        """
        self.owner.sequences._ensure_selector(gcmd, path)

    def _assert_on_path(self, gcmd, path):
        """Refuse to drive filament when the carriage is not on *path*.

        The failure this catches is silent by nature: the drive gear engages
        whatever is in front of it and reports perfectly healthy encoder
        motion, because the filament it is pushing IS moving -- just the wrong
        path's. Only the operator noticing "that is the wrong gate" catches it
        otherwise.
        """
        cur = getattr(self.owner, 'current_path', -1)
        if cur == path:
            return True
        raise gcmd.error(
            "SA CAL: Carriage is on path %s but this is path %d. Refusing to "
            "drive filament at the wrong gate — run SA_SELECT TOOL=%d, or "
            "re-run this step so it selects for you."
            % ("none" if cur is None or cur < 0 else cur, path, path))

    def _safe_selector_move(self, motion, position_mm):
        """Disengage servo if engaged, move selector, restore servo state."""
        was_engaged = self.owner._servo_is_engaged
        if was_engaged:
            motion.servo_disengage()
        motion.selector_move_to(position_mm)
        if was_engaged:
            motion.servo_engage()

    def _clear(self):
        # Delegates so there is ONE implementation of "clear the state and
        # release what it held". This module got the pairing right and
        # sa_sequences did not; a shared method is what makes that impossible
        # rather than merely unlikely.
        self.owner.clear_cal_state()

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
                        columns=None, expect=(), warn=(), restate=False,
                        ks_line=None):
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
            # restate: this dialog is already on screen and only its
            # contents change. prompt_end would remove the window and
            # prompt_begin build another, which is the flash on every tap of a
            # +/- prompt. prompt_begin alone clears the text and buttons on
            # both UIs, so the window survives and only its contents move.
            if not restate:
                r("// action:prompt_end")
            r("// action:prompt_begin %s" % title)
            # ONE prompt_text, carrying the whole body.
            #
            # Each "//" line is a separate command, so a newline cannot be sent
            # inside one -- and sending a line each looked right because
            # Mainsail concatenates them. KlipperScreen does not: prompts.py
            # does `self.text = data.replace('prompt_text ', '')`, an
            # assignment, so every line but the LAST is thrown away. The
            # touchscreen has been showing one sentence of every prompt, which
            # is why a yes/no question arrived as "Is it?" with nothing above
            # it, and why the endstop wait screen showed only its footnote.
            #
            # So the body goes as one line. Paragraph breaks are lost on
            # Mainsail, which is a cheap price for the other screen showing
            # anything at all -- and the bodies are short now.
            if ks_line:
                # The two UIs disagree about prompt_text, and the disagreement
                # can be used rather than worked around. Mainsail renders ONE
                # PARAGRAPH PER prompt_text -- MacroPromptText.vue is
                # instantiated per event, each emitting its own <p> -- while
                # KlipperScreen assigns, keeping only the LAST.
                #
                # So detail first, then a line that stands on its own: the web
                # panel gets every row, the touchscreen gets the one line that
                # matters, from a single emission with nothing to keep in step.
                #
                # ks_line must make sense ALONE. Anything whose meaning depends
                # on the lines above it must not use this -- that is the bug
                # the single-line rule was written for, where a yes/no question
                # arrived as "Is it?" with nothing above it.
                for part in str(text).split(NL):
                    part = part.strip()
                    if part:
                        r("// action:prompt_text %s" % part)
                r("// action:prompt_text %s" % str(ks_line).strip())
            else:
                body = " ".join(
                    part.strip() for part in str(text).split(NL) if part.strip())
                r("// action:prompt_text %s" % body)
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

    # ══════════════════════════════════════════════════════════════════════
    # The guide. One definition; every UI renders from it.
    # ══════════════════════════════════════════════════════════════════════
    #
    # Keys:
    #   title    heading
    #   status   which live line to resolve, or None
    #   hint     what this step does, in a sentence or two
    #   buttons  [(label, gcode)] -- plain, run as-is
    #   grid     (status_field | None, fmt, gcode) -- a per-path row of
    #            buttons; {t} in the gcode is the path number
    #   expect   what should happen
    #   warn     what to do when it does not
    _GUIDE = [
        {'title': "Motor direction check", 'status': 'motors',
         'hint': "Buzz each motor and answer which way it moved. Answering "
                 "'wrong way' flips that motor in software, saves it, and "
                 "buzzes again so you can check the fix.",
         'buttons': [("BUZZ DRIVE", "SA_BUZZ_CHECK MOTOR=drive"),
                     ("BUZZ SELECTOR", "SA_BUZZ_CHECK MOTOR=selector")],
         'grid': None,
         'expect': ["Drive: first move pushes filament toward the toolhead.",
                    "Selector: first move travels away from the endstop, "
                    "toward higher path numbers.",
                    "Both buzz, return to where they started, then ask which "
                    "way they went."],
         'warn': ["No movement — check motor wiring and driver power.",
                  "Wrong direction — answer WRONG WAY; no rewiring needed.",
                  "Very weak — raise run_current in hardware.cfg."]},

        {'title': "Test the selector endstop", 'status': 'endstop',
         'hint': "Move the selector carriage by hand onto the endstop and off "
                 "again while this watches. Nothing is driven.",
         'buttons': [("TEST ENDSTOP", "SA_TEST_ENDSTOP DURATION=30")],
         'grid': None,
         'expect': ["Reads open off the switch and TRIGGERED on it, reporting "
                    "every change.",
                    "It ends with ENDSTOP OK only after seeing BOTH states, so "
                    "a switch stuck either way fails rather than passing."],
         'warn': ["Never triggers — check wiring and the SA_SELECTOR_STOP pin.",
                  "Always triggered — polarity is inverted; check the '^' or "
                  "'^!' on the endstop pin.",
                  "Do not run HOME until this passes: homing is the first "
                  "thing that trusts the switch, and it finds out by driving "
                  "the carriage at it."]},

        {'title': "Entry sensor check (per tool)", 'status': None,
         'hint': "Per path. Push filament into the entry by hand and pull it "
                 "out again. Nothing is driven.",
         'buttons': [],
         'grid': ('entry_sensor_ok', "proved", "SA_TEST_ENTRY_SENSORS TOOL={t}"),
         'expect': ["Empty reads CLEAR, filament reads FILAMENT, and it clears "
                    "again when you pull it out.",
                    "All three have to happen — a sensor stuck on is as bad as "
                    "one that never triggers."],
         'warn': ["Reads FILAMENT while empty — the pin is inverted; add or "
                  "remove the '!' on that sensor's switch_pin.",
                  "Never changes — check the connector, and that the lever "
                  "actually moves when filament passes.",
                  "A load waits on this sensor and a runout is declared by it, "
                  "so a bad one means a path that never starts or never stops."]},

        {'title': "Home the selector", 'status': 'homed',
         'hint': "Moves the selector to the physical endstop and zeros its "
                 "position. Required before any selector movement.",
         'buttons': [("HOME SELECTOR", "SA_HOME")],
         'grid': None,
         'expect': ["Moves toward the endstop, slows, touches, backs off and "
                    "touches again to confirm."],
         'warn': ["Moves away from the endstop — go back to step 1 and answer "
                  "WRONG WAY for the selector.",
                  "Never triggers — check the endstop wiring and pin.",
                  "Slams hard — reduce selector_homing_speed."]},

        {'title': "Calibrate selector positions", 'status': 'selector',
         'hint': "Sweeps the rail using stallguard to find the far end, homes "
                 "back to measure total travel, and divides it into even path "
                 "positions. You confirm each one before it saves.",
         'buttons': [("CAL SELECTOR", "SA_CALIBRATE_SELECTOR")],
         'grid': None,
         'expect': ["Homes, sweeps out until it stalls, homes back.",
                    "Then offers a button per path so you can see each one "
                    "centered before saving, and adjust gate width or end "
                    "offset with the carriage following as you dial."],
         'warn': ["Stalls mid-rail — raise selector_stall_threshold.",
                  "Misses the far end — lower selector_stall_threshold.",
                  "Spacing wrong — check the rail is unobstructed and re-run."]},

        {'title': "Calibrate the engage servo", 'status': 'servo',
         'hint': "Load filament to the drive gear first. You will be asked to "
                 "REMOVE the servo arm before anything moves, refit it at the "
                 "rest position, then step toward the gear until it grips.",
         'buttons': [("CAL SERVO", "SA_CALIBRATE_SERVO")],
         'grid': None,
         'expect': ["Arm off, servo moves to rest, refit the arm resting "
                    "against the servo body and away from the drive gear.",
                    "Then step in 1/5/10° until the gear just grips, and save. "
                    "Effective immediately, no restart."],
         'warn': ["Take the arm OFF when asked. Fitted at the wrong angle its "
                  "whole travel is a hard stop and the gears strip in seconds.",
                  "Arm moves away from the gear as the angle rises — the servo "
                  "is reversed; press WRONG WAY.",
                  "Near the grip point move in 1° steps."]},

        {'title': "Calibrate drive rotation distance", 'status': 'drive',
         'hint': "Filament must reach the drive gear. The gear holds it and "
                 "the motor is released, so the knob feeds it: set the tip "
                 "flush with the gate exit, it feeds, and you measure what is "
                 "sticking out. No tape or marker.",
         'buttons': [("CAL DRIVE", "SA_CALIBRATE_DRIVE")],
         'grid': None,
         'expect': ["Three passes, averaged. Measure from the gate exit to the "
                    "tip each time and enter what you read."],
         'warn': ["No movement — check the gear grips and the servo is engaged.",
                  "Filament slips — tighten the idler, or re-run the servo step "
                  "for a firmer engage angle.",
                  "Passes disagree by more than a few percent — that is "
                  "measurement scatter, not the machine; re-seat and repeat."]},

        {'title': "Encoder mm/pulse (per tool)", 'status': None,
         'hint': "Per path. Sets how far one encoder count means. Feeds until "
                 "the encoder reads the datum, you measure what came out of "
                 "the gate, three times, averaged.",
         'buttons': [],
         'grid': ('encoder_mpp', "%.4f", "SA_CALIBRATE_ENCODER TOOL={t}"),
         'expect': ["Most of the datum is fed in one continuous move, then "
                    "the last 50mm in small steps.",
                    "Three passes at the same starting value, so they are "
                    "three samples rather than a chain.",
                    "The path is parked once its value is saved, so it ends "
                    "ready rather than with the tip at the gate.",
                    "The spread is shown next to the mean; passes disagreeing "
                    "by more than a few percent are refused rather than "
                    "averaged into a confident wrong answer."],
         'warn': ["Value near zero — the encoder is not counting; check the "
                  "wiring and pin.",
                  "Paths differ by more than about 1% — the odd one out is "
                  "worth looking at rather than accepting.",
                  "Every distance downstream is measured in these units, so "
                  "Bowden lengths must be re-measured after this changes."]},

        {'title': "Encoder max speed", 'status': 'enc_speed',
         'hint': "Finds the fastest feed each encoder still counts accurately. "
                 "Tests every path in turn, because the faults this finds are "
                 "per path. Filament must be through the drive gear.",
         'buttons': [("CAL ENCODER SPEED", "SA_CALIBRATE_ENCODER_SPEED")],
         'grid': None,
         'expect': ["The slowest pass is the reference: at that speed the "
                    "encoder cannot alias, so what it reads is this path's "
                    "scale. Every later pass is measured against it, which is "
                    "why the figures start at zero -- a mm_per_pulse a few "
                    "percent out would otherwise be charged to whichever speed "
                    "is on screen.",
                    "Speed climbs until the encoder falls behind, then stops "
                    "and shows the result for that path.",
                    "At the end every path is listed side by side so a slow one "
                    "stands out, and any of them can be retested alone."],
         'warn': ["One path far below the others — usually mechanical: a tight "
                  "tube, a dirty or slipping encoder wheel.",
                  "Fails at the slowest speed too — that is the channel, not "
                  "the speed. Check the wheel and its wiring.",
                  "The shared speed is the slowest path's, so fix a bad path "
                  "rather than accepting the number it produces."]},

        {'title': "Toolhead sensor check (per tool)", 'status': None,
         'hint': "Per path. It changes to that toolhead and brings it to the "
                 "middle of the bed first, so pick a path only when the "
                 "printer is clear. Then, with the Bowden off: push a scrap of "
                 "filament into the inlet, feed it past the gears by hand, and "
                 "pull it out.",
         'buttons': [],
         'grid': ('toolhead_sensor_ok', "proved",
                  "SA_TEST_TOOLHEAD_SENSORS TOOL={t}"),
         'expect': ["It asks before the toolchange, and does nothing until "
                    "you say the printer is clear.",
                    "Both read CLEAR when empty.",
                    "The extruder sensor sees the filament BEFORE the toolhead "
                    "one — that ordering is the point of the test.",
                    "Both clear again on the way out."],
         'warn': ["The far sensor triggers first — they are crossed. Swap the "
                  "two connectors or the two pins.",
                  "Reads FILAMENT while empty — that pin is inverted.",
                  "Do this before the Bowden step: that one blasts filament "
                  "most of a meter at speed and stops on the extruder sensor. "
                  "Crossed, it stops on a sensor the filament has not reached, "
                  "at the gears."]},

        {'title': "Bowden tube length (per tool)", 'status': None,
         'hint': "Per path. Feeds from the drive gear until the extruder "
                 "sensor triggers and records the distance. Needs the encoder "
                 "calibrated and the toolhead sensors proven first.",
         'buttons': [],
         'grid': ('bowden_lengths', "%.0fmm", "SA_CALIBRATE_BOWDEN TOOL={t}"),
         'expect': ["Filament loads until the extruder sensor triggers; the "
                    "distance is saved per path.",
                    "Paths should agree to within about 10mm unless the tubes "
                    "are genuinely different lengths."],
         'warn': ["Sensor never triggers — go back and run the toolhead sensor "
                  "test.",
                  "Distance too short — the filament may have buckled; check "
                  "the tube routing.",
                  "This is stored in encoder millimeters, so re-measure it "
                  "whenever mm/pulse changes."]},

        {'title': "Toolhead geometry (per tool)", 'status': 'toolhead_geom',
         'hint': "Per path. Measures the three distances inside the toolhead "
                 "with this path's own encoder, and derives the other two. "
                 "Needs the Bowden step done and the toolhead EMPTY — it "
                 "starts from an unloaded head.",
         'buttons': [],
         'grid': ('toolhead_geom_mm', "%.1fmm",
                  "SA_CALIBRATE_TOOLHEAD TOOL={t}"),
         'expect': ["Two run on their own and cold: the span between the two "
                    "toolhead sensors, then the gear nip — found by retracting "
                    "until the extruder stops moving filament, which the "
                    "encoder can see because it is fixed on this lane.",
                    "Then it heats and asks you to watch the nozzle. Nudge "
                    "until filament just appears and say so; that is the last "
                    "distance and nothing but an eye can measure it.",
                    "It feeds to the toolhead sensor twice and prints both "
                    "readings. They should agree within a millimetre or two.",
                    "Ends with all five distances, three measured and two "
                    "derived, saved per path."],
         'warn': ["\"The extruder never lost grip\" — the encoder is not "
                  "counting on this lane, or the drive did not release. "
                  "Nothing was measured; no value is saved.",
                  "The two repeat readings disagree by more than a couple of "
                  "millimetres — a slipping encoder wheel or a tight tube.",
                  "If it reports parameters.cfg disagreeing with the measured "
                  "figure, believe the measurement: the defaults were three "
                  "different spans all left at 50.0.",
                  "Measure it again after any toolhead change — a different "
                  "hotend or extruder moves every one of these."]},
    ]

    _STEP_TOTAL = 12
    _STEP_NAMES = {
        1: "Motor direction",
        2: "Endstop test",
        3: "Entry sensors",
        4: "Home selector",
        5: "Selector positions",
        6: "Servo engage angle",
        7: "Drive rotation distance",
        8: "Encoder mm/pulse",
        9: "Encoder speed",
        10: "Toolhead sensors",
        11: "Bowden length",
        12: "Toolhead geometry",
    }

    # Longest prefix first: SA_CALIBRATE_ENCODER_SPEED would otherwise match
    # the per-path SA_CALIBRATE_ENCODER entry and report step 8 for step 7.
    _STEP_BY_COMMAND = (
        ("SA_BUZZ_CHECK",               1),
        ("SA_TEST_ENDSTOP",             2),
        ("SA_TEST_ENTRY_SENSORS",       3),
        ("SA_HOME",                     4),
        ("SA_CALIBRATE_SELECTOR",       5),
        ("SA_CALIBRATE_SERVO",          6),
        ("SA_CALIBRATE_DRIVE",          7),
        ("SA_CALIBRATE_ENCODER_SPEED",  9),
        ("SA_CALIBRATE_ENCODER",        8),
        ("SA_TEST_TOOLHEAD_SENSORS",   10),
        ("SA_CALIBRATE_BOWDEN",        11),
        ("SA_CALIBRATE_TOOLHEAD",      12),
    )

    # load_purge and unload_done are deliberately absent: they are load/unload
    # flows, not calibration, and numbering them "step N of 9" would be a lie.
    _STEP_BY_STATE = (
        ("dir_", 1),
        ("end_", 2),
        ("sen_entry", 3),
        ("sel_", 5),
        ("srv_", 6),
        ("drv_", 7),
        # More specific first: the loop takes the first match, and
        # "enc_speed_run" starts with "enc_" too.
        ("enc_speed", 9),
        ("enc_", 8),
        ("sen_th", 10),
        ("bow_", 11),
        ("thg_", 12),
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

    def _numeric_render(self, gcmd, restate=False):
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
            columns=len(steps), restate=restate)

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
            self._srv_render(gcmd, restate=True)
            return
        if self.owner._cal_state == 'sel_tune':
            self._sel_tune_render(gcmd, restate=True)
            return
        self._numeric_render(gcmd, restate=True)

    def _save_variables(self, updates):
        """Persist several calibration values in ONE file rewrite.

        Every SAVE_VARIABLE rewrites the whole of variables.cfg synchronously,
        and Klipper's host is single-threaded: while it is blocked in that I/O
        it is not feeding the MCUs. Twelve of them in a row is what shut the
        autoloader board down with "Timer too close" three times -- see the
        SA_SET_MATERIAL fix. A loop over six paths is the same shape.

        Values are literal_eval'd first because that is exactly what
        SAVE_VARIABLE does with its unquoted VALUE=, so "24.69" lands as a
        float and "True" as a bool. Skipping that would silently change the
        stored type of every calibration value this touches.
        """
        parsed = {}
        for key, value in updates.items():
            if isinstance(value, str):
                try:
                    value = _ast.literal_eval(value)
                except (ValueError, SyntaxError):
                    pass
            parsed[key] = value
        self.owner._persist_variables(parsed)

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
            note = ("Carriage is at path %d. Check it is centered, then try "
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
         "Test the entry sensors next?",
         "Each path has a sensor that sees filament arrive. A load waits on it "
         "and a runout is declared by it, so one that is stuck or inverted "
         "means a path that never starts, or never stops.",
         "TEST ENTRY SENSORS", "SA_TEST_ENTRY_SENSORS TOOL={TOOL}"),

        ('entry_sensors', "Entry sensors",
         "Home the selector next?",
         "Drives the carriage to the switch and calls that zero. Everything "
         "measured in millimeters from home depends on it.",
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
         "feeds or retracts is measured in those millimeters, so nothing "
         "downstream is trustworthy until it is set.",
         "CALIBRATE DRIVE", "SA_CALIBRATE_DRIVE"),

        ('drive',      "Drive rotation distance",
         "Calibrate encoder mm/pulse next?",
         "Per path. Sets what one encoder count means, which every slip check "
         "and every park depends on. It comes before the speed sweep because "
         "that sweep reports its answer in mm/s, and mm/s is counts times this "
         "number.",
         "CALIBRATE ENCODER T{TOOL}", "SA_CALIBRATE_ENCODER TOOL={TOOL}"),

        ('encoder',    "Encoder mm/pulse",
         "Calibrate encoder speed next?",
         "Finds the fastest feed the encoder can still count reliably, which "
         "is what the Bowden measurement then uses. It feeds at a fixed "
         "25mm/s, so it needs nothing from the sweep -- the sweep needs the "
         "scale above.",
         "CALIBRATE ENCODER SPEED", "SA_CALIBRATE_ENCODER_SPEED"),

        ('enc_speed',  "Encoder max speed",
         "Test the toolhead sensors next?",
         "Per path, and worth doing before the Bowden measurement rather than "
         "after: that one blasts filament most of a meter at speed and stops "
         "on the extruder sensor. If the two sensors are crossed or inverted "
         "it stops on one the filament has not reached, at the gears.",
         "TEST TOOLHEAD SENSORS T{TOOL}", "SA_TEST_TOOLHEAD_SENSORS TOOL={TOOL}"),

        ('toolhead_sensors', "Toolhead sensors",
         "Calibrate Bowden length next?",
         "Per path. Measures the tube from the drive gear to the toolhead, "
         "which is the distance a load feeds before it expects the filament "
         "to arrive.",
         "CALIBRATE BOWDEN T{TOOL}", "SA_CALIBRATE_BOWDEN TOOL={TOOL}"),

        ('bowden',     "Bowden length",
         "Measure the toolhead geometry next?",
         "The last distances in the machine are still defaults -- three of "
         "them sit at 50.0 while describing different spans. This measures "
         "three with the encoder and derives the other two, so the tip former "
         "stops aiming at a figure nobody checked.",
         "MEASURE TOOLHEAD", "SA_CALIBRATE_TOOLHEAD TOOL={TOOL}"),

        ('toolhead_geom', "Toolhead geometry",
         None, None, None, None),
    ]

    def _guide_status(self, key, st):
        """The live one-liner for a page: (text, tone).

        Resolved here rather than in each UI, so both screens answer "is this
        done yet" the same way. tone is 'ok' | 'warn' | 'idle'.
        """
        owner = self.owner
        if key == 'motors':
            drv = bool(st.get('drive_dir_invert'))
            sel = bool(st.get('selector_dir_invert'))
            return ("Direction: drive %s · selector %s"
                    % ("INVERTED" if drv else "normal",
                       "INVERTED" if sel else "normal"),
                    'warn' if (drv or sel) else 'idle')
        if key == 'toolhead_geom':
            ok  = list(st.get('toolhead_geom_ok') or [])
            num = int(st.get('num_paths') or 0)
            done = sum(1 for v in ok[:num] if v)
            if done == 0:
                return ("Not measured — using the config defaults", 'warn')
            stg = list(st.get('sensor_to_gear') or [])
            stt = list(st.get('sensor_to_toolhead') or [])
            ttn = list(st.get('toolhead_to_nozzle') or [])
            # Every measured path, not the first one found. This used to
            # `return` inside the loop, so it named T0 for ever and looked
            # frozen while the grid beside it filled in.
            vals = []
            for i in range(min(num, len(stg), len(stt), len(ttn))):
                if stg[i] and stt[i] and ttn[i]:
                    vals.append((max(0.0, stt[i] - stg[i]) + ttn[i], i))
            if not vals:
                return ("%d/%d measured" % (done, num),
                        'ok' if done >= num else 'warn')
            lo, hi = min(vals), max(vals)
            tone = 'ok' if done >= num else 'warn'
            if len(vals) == 1:
                return ("%d/%d measured — T%d gear to tip %.1fmm"
                        % (done, num, lo[1], lo[0]), tone)
            spread = hi[0] - lo[0]
            # These are nominally identical toolheads, so the spread is the
            # reading that matters -- a single number hides the one that is
            # out, which is the only thing worth acting on.
            txt = ("%d/%d measured — gear to tip %.1f-%.1fmm"
                   % (done, num, lo[0], hi[0]))
            if spread > 5.0:
                txt += ", T%d is %.1fmm off the rest" % (hi[1], spread)
                tone = 'warn'
            return (txt, tone)
        if key == 'homed':
            if owner._selector_homed:
                return ("Homed", 'ok')
            if getattr(owner, '_selector_position_restored', False):
                # Worth spelling out rather than showing a bare "Not homed":
                # the machine does have a position, it just has no evidence
                # for it, and that is a different thing to say.
                return ("Position restored from last session — not homed", 'warn')
            return ("Not homed", 'warn')
        if key == 'selector':
            pos = list(st.get('selector_positions') or [])
            done = bool(pos) and any(abs(pos[i] - i * 21.0) > 1.0
                                     for i in range(len(pos)))
            if not done:
                return ("Using defaults — run to calibrate", 'warn')
            return ("  ".join("T%d %.1f" % (i, pos[i])
                              for i in range(len(pos))), 'ok')
        if key == 'servo':
            return ("Engaged %.0f°   Disengaged %.0f°"
                    % (float(st.get('servo_engaged_angle') or 0.0),
                       float(st.get('servo_disengaged_angle') or 0.0)), 'idle')
        if key == 'drive':
            rd = float(st.get('drive_rotation_distance') or 0.0)
            return (("rotation_distance %.4f" % rd) if rd > 0
                    else "Not calibrated", 'ok' if rd > 0 else 'warn')
        if key == 'endstop':
            # Whether it has been proved, not what the pin reads now: reading
            # the pin means QUERY_ENDSTOPS, and this runs on every status
            # query. Same answer the two sensor pages give.
            if bool(st.get('endstop_ok')):
                return ("Proved — both states seen", 'ok')
            return ("Not tested", 'warn')
        if key == 'enc_speed':
            mx = float(st.get('encoder_max_speed') or 0.0)
            if mx <= 0:
                return ("Not calibrated — blast defaults to 75mm/s", 'warn')
            # The blast runs AT the saved figure now, so this no longer
            # recomputes a derate the code does not apply -- that is exactly
            # the kind of second copy that goes stale.
            return ("Max %.0fmm/s — blasts at this speed" % mx, 'ok')
        return ("", 'idle')

    def guide_pages(self, st):
        """The whole guide, resolved, for whichever UI is asking.

        Rebuilt only when something it displays has changed -- this is read on
        every status query and the text does not move between calibrations.
        """
        sig = (len(self._GUIDE),
               tuple(st.get('selector_positions') or ()),
               tuple(st.get('encoder_mpp') or ()),
               tuple(st.get('bowden_lengths') or ()),
               tuple(st.get('sensor_to_gear') or ()),
               tuple(st.get('sensor_to_toolhead') or ()),
               tuple(st.get('toolhead_to_nozzle') or ()),
               tuple(st.get('toolhead_geom_mm') or ()),
               tuple(st.get('entry_sensor_ok') or ()),
               tuple(st.get('toolhead_sensor_ok') or ()),
               bool(st.get('endstop_ok')),
               st.get('drive_rotation_distance'), st.get('encoder_max_speed'),
               st.get('servo_engaged_angle'), st.get('servo_disengaged_angle'),
               st.get('drive_dir_invert'), st.get('selector_dir_invert'),
               bool(self.owner._selector_homed),
               bool(getattr(self.owner, '_selector_position_restored', False)),
               int(st.get('num_paths') or 0))
        if getattr(self, '_guide_sig', None) == sig:
            return self._guide_cache

        num   = int(st.get('num_paths') or 0)
        pages = []
        for i, g in enumerate(self._GUIDE):
            text, tone = self._guide_status(g['status'], st)
            grid = None
            if g['grid'] is not None:
                field, fmt, cmd = g['grid']
                vals = list(st.get(field) or []) if field else []
                cells = []
                for t in range(num):
                    v = vals[t] if t < len(vals) else None
                    # A pass/fail field has no number to print, so its format
                    # is the word itself. Anything with a placeholder is a
                    # measurement and gets formatted.
                    if field and v:
                        cell = (fmt % v) if '%' in fmt else fmt
                    else:
                        cell = ""
                    cells.append({
                        'tool': t,
                        'value': cell,
                        'done': bool(field and v),
                        'gcode': cmd.replace('{t}', str(t)),
                    })
                grid = cells
            pages.append({
                'n': i + 1, 'title': g['title'],
                'status': text, 'tone': tone, 'hint': g['hint'],
                'buttons': [{'label': l, 'gcode': c} for l, c in g['buttons']],
                'grid': grid,
                'expect': list(g['expect']), 'warn': list(g['warn']),
            })
        self._guide_sig   = sig
        self._guide_cache = pages
        return pages

    def _offer_command(self, gcmd, question, detail, label, cmd,
                       decline="STOP HERE", path=0):
        """Leave a prompt behind that will run `cmd` if accepted.

        Every offer in this file goes through here. The three that existed
        before -- next step, next path, and the endstop retry -- had drifted
        into three copies of the same four lines, and a copy that forgets to
        set _cal_state is an offer whose button does nothing.

        {TOOL} is filled in here rather than by the callers, so a per-path
        template cannot reach a button unsubstituted. SKIP STEP took the other
        route and shipped a literal "TOOL={TOOL}" the moment the table stopped
        hardcoding a zero.
        """
        tool  = str(int(path))
        label = (label or '').replace('{TOOL}', tool)
        cmd   = (cmd or '').replace('{TOOL}', tool)
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

    def _to_guide(self, gcmd, step_n, note=""):
        """Put the guide on *step_n* and show it, on every UI at once.

        Replaces the "shall I run X next?" prompt. The guide page is the same
        content with more of it, and it is where the operator was before the
        step started.
        """
        if note:
            gcmd.respond_info(note)
        try:
            self.owner.gcode.run_script_from_command(
                "SA_GUIDE OPEN=1 STEP=%d" % int(step_n))
        except Exception:
            logging.exception("SA CAL: could not return to the guide")

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

        # Back to this step's own page rather than a prompt naming the next
        # path. That page carries a button per path and marks the ones already
        # done, which answers "what is left" better than a sentence can.
        step_n = self._step_for_command(cmd_fmt % nxt)
        self._clear()
        self._to_guide(
            gcmd, step_n or 1,
            "SA CAL: %s done for path %d of %d. The guide shows which paths "
            "are still to do." % (label, int(path) + 1,
                                  int(self.owner.num_paths)))

    def _offer_next(self, gcmd, step, path=0):
        """After a calibration completes, offer the one that follows it.

        *path* fills the {TOOL} slot in the per-path entries. It used to be
        written 0 into the table, so finishing a step on path 3 offered the
        next one on path 0 -- the tool was dropped at every hand-off between
        steps, and the button quietly sent you back to the start.
        """
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
        step_n = self._step_for_command(
            btn_cmd.replace('{TOOL}', str(int(path))))
        self._clear()
        self._to_guide(gcmd, step_n or 1, "SA CAL: %s saved." % done_label)

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
        self._to_guide(gcmd, (step_n or 0) + 1)

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

    def _sel_tune_render(self, gcmd, restate=False):
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
            columns=3, restate=restate)
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
            batch = {}
            for i, pos in enumerate(positions):
                owner._selector_positions[i] = pos
                batch['selector_position_%d' % i] = round(float(pos), 2)
            if d.get('_tune') == 'offset':
                owner.selector_end_offset = float(d.get('_np_val', 0.0))
                batch['sa_selector_end_offset'] = round(
                    float(owner.selector_end_offset), 2)
            self._save_variables(batch)
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
                self._save_variables({
                    'sa_servo_engaged_angle':    round(float(eng), 1),
                    'sa_servo_disengaged_angle': round(float(d['dis']), 1),
                })
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
                "SA CAL: Servo calibration canceled. Returned to %.0f deg."
                % d['dis'])
            return

    def _srv_render(self, gcmd, restate=False):
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
            columns=3, restate=restate)
        owner._cal_prompt = "Servo: %.1f deg" % ang


    # ── Endstop: prove the mapping, not just the movement ─────────────────────

    _END_TIMEOUT = 180.0

    def _end_meaning(self, triggered):
        """What a reading is supposed to mean about the carriage."""
        return ("the carriage is ON the switch" if triggered
                else "the carriage is OFF the switch")

    def _end_word(self, triggered):
        return "TRIGGERED" if triggered else "open"

    # ══════════════════════════════════════════════════════════════════════
    # SA_TEST_ENTRY_SENSORS / SA_TEST_TOOLHEAD_SENSORS
    # ══════════════════════════════════════════════════════════════════════

    _SEN_TIMEOUT = 240.0

    _SEN_LABEL = {
        'entry':    "Entry sensor",
        'extruder': "Extruder sensor (before the gears)",
        'toolhead': "Toolhead sensor (past the gears)",
    }
    _SEN_TITLE = {'entry': "Entry sensor test", 'th': "Toolhead sensor test"}

    def _sen_read(self, path, key):
        """(configured, reading) for one sensor on one path.

        The owner's accessors answer False for a sensor that is not configured,
        which is indistinguishable from one reading clear -- so configuration is
        checked against the name list, not the reading.
        """
        owner = self.owner
        try:
            names, fn = {
                'entry':    (owner._entry_sensor_names,    owner._entry_sensor_active),
                'extruder': (owner._extruder_sensor_names, owner._extruder_sensor_active),
                'toolhead': (owner._toolhead_sensor_names, owner._toolhead_sensor_active),
            }[key]
            name = names[path]
        except Exception:
            return False, None
        if not name:
            return False, None
        try:
            return True, bool(fn(path))
        except Exception:
            return True, None

    def _sen_word(self, v):
        return "FILAMENT" if v else ("CLEAR" if v is not None else "unreadable")

    def _sen_plan(self, group, path):
        """The stages, in the order that makes each one meaningful."""
        if group == 'entry':
            return [
                {'want': {'entry': False},
                 'confirm': "Path %d is empty" % path,
                 'ask': "Take any filament out of path %d's entry, then "
                        "confirm." % path,
                 'why': "Nothing else can check this one: CLEAR reads the "
                        "same whether the sensor works, is unplugged, or is "
                        "backwards. Your answer is what tells them apart."},
                {'want': {'entry': True},
                 'ask': "Now push a piece of filament into path %d's entry, "
                        "past the sensor." % path},
                {'want': {'entry': False},
                 'ask': "Now pull it back out."},
            ]
        return [
            {'want': {}, 'action': 'toolchange',
             'confirm': "Printer is clear",
             'ask': "About to change to toolhead %d and move it to the middle "
                    "of the bed, where you can reach it." % path,
             'why': "A real toolchange and a real move. Check the bed is "
                    "clear and nothing is in the gantry's way."},
            {'want': {'extruder': False, 'toolhead': False},
             'confirm': "Toolhead %d is empty" % path,
             'ask': "Toolhead %d is in front of you. Detach its Bowden and "
                    "take out any filament, then confirm." % path,
             'why': "Nothing else can check this one: CLEAR reads the same "
                    "whether a sensor works, is unplugged, or is backwards. "
                    "Your answer is what tells them apart."},
            {'want': {'extruder': True},
             'wrong_first': 'toolhead',
             'ask': "Push a scrap of filament into the toolhead inlet until it "
                    "reaches the extruder gears."},
            {'want': {'toolhead': True},
             'ask': "Now turn the extruder knob to feed it past the gears."},
            {'want': {'extruder': False, 'toolhead': False},
             'ask': "Now pull the filament back out."},
        ]

    def _sen_action(self, gcmd, name, path):
        """Run whatever a confirmed stage asked for. Raises on refusal."""
        if name != 'toolchange':
            return
        owner = self.owner
        th    = owner.printer.lookup_object('toolhead')
        st    = th.get_status(owner.reactor.monotonic())

        homed = st.get('homed_axes') or ''
        if not all(a in homed for a in 'xyz'):
            # Not a failure, just a thing that has to happen first -- and the
            # machine can do it. Sending the operator away to run G28 and start
            # over is a dead end dressed as a safety check.
            return 'need_home'

        amax = st.get('axis_maximum') or []
        try:
            x = float(amax[0]) / 2.0
            y = float(amax[1]) / 2.0
        except Exception:
            raise owner.printer.command_error(
                "SA: could not read the bed size, so there is nowhere known to "
                "put the toolhead. Check the printer's stepper limits.")
        z = float(owner.load_park_z)

        gcmd.respond_info("SA: changing to T%d and moving to %.0f, %.0f at Z%.0f..."
                          % (path, x, y, z))
        owner.gcode.run_script_from_command("T%d" % path)
        owner.gcode.run_script_from_command("G90")
        owner.gcode.run_script_from_command(
            "G1 X%.1f Y%.1f Z%.1f F6000" % (x, y, z))
        owner.gcode.run_script_from_command("M400")

    def _sen_advance(self, gcmd):
        """Move to the next stage, which may be another question."""
        owner = self.owner
        d     = owner._cal_data
        d['stage'] += 1
        d['shown']  = None
        d['deadline'] = owner.reactor.monotonic() + self._SEN_TIMEOUT
        # This test asks twice before it reads anything, so the next stage is
        # not necessarily a watch.
        nxt = d['plan'][d['stage']]
        owner._cal_state = ('sen_%s_confirm' % d['group'] if nxt.get('confirm')
                            else 'sen_%s_wait' % d['group'])
        self._sen_render(gcmd)
        self._sen_arm()

    def _sen_ask_home(self, gcmd):
        """Offer to home rather than sending the operator away to do it."""
        owner = self.owner
        d     = owner._cal_data
        owner._cal_state = 'sen_%s_home' % d['group']
        self._emit_ui_prompt(
            gcmd, self._ui_title(),
            ("%s — path %d" % (self._SEN_TITLE[d['group']], d['path'])
             + NL + NL
             + "The printer is not homed, so there is nowhere known to put the "
               "toolhead." + NL + NL
             + "Home it now and carry on?" + NL + NL
             + "Runs G28, and any homing override the printer defines."),
            [("HOME", "home", "primary")],
            footer=[("STOP", "abort", "error")])

    def _sen_arm(self, delay=0.25):
        try:
            self.owner.gcode.run_script_from_command(
                "UPDATE_DELAYED_GCODE ID=sa_sensor_poll DURATION=%.2f" % delay)
        except Exception:
            logging.exception("SA CAL: could not arm the sensor poll")

    def _sen_disarm(self):
        try:
            self.owner.gcode.run_script_from_command(
                "UPDATE_DELAYED_GCODE ID=sa_sensor_poll DURATION=0")
        except Exception:
            pass

    def test_entry_sensors(self, gcmd):
        self._sen_start(gcmd, 'entry')

    def test_toolhead_sensors(self, gcmd):
        self._sen_start(gcmd, 'th')

    def _sen_start(self, gcmd, group):
        owner = self.owner
        if owner._cal_state is not None:
            self._busy(gcmd)
            return

        path = gcmd.get_int('TOOL', None, minval=0, maxval=owner.num_paths - 1)
        if path is None:
            path = owner.current_path if owner.current_path >= 0 else 0

        keys = ['entry'] if group == 'entry' else ['extruder', 'toolhead']
        missing = [k for k in keys if not self._sen_read(path, k)[0]]
        if missing:
            gcmd.respond_info(
                "SA: path %d has no %s configured, so there is nothing to "
                "test.%s    Add %s to [autoloader]."
                % (path, " or ".join(missing), NL,
                   ", ".join("%s_sensor_%d" % (k, path) for k in missing)))
            return

        owner._cal_data = {
            'group': group, 'path': path, 'keys': keys, 'stage': 0,
            'plan': self._sen_plan(group, path),
            'deadline': owner.reactor.monotonic() + self._SEN_TIMEOUT,
        }
        owner._cal_state = ('sen_%s_confirm' % group
                            if owner._cal_data['plan'][0].get('confirm')
                            else 'sen_%s_wait' % group)
        gcmd.respond_info(
            "SA %s — path %d%s"
            "===========================================%s"
            "Nothing is driven. Move the filament by hand; this only watches."
            % (self._SEN_TITLE[group].upper(), path, "\n", "\n"))
        self._sen_render(gcmd)
        self._sen_arm()

    def _sen_render(self, gcmd, now=None):
        owner = self.owner
        d     = owner._cal_data
        path  = d['path']
        if now is None:
            now = dict((k, self._sen_read(path, k)[1]) for k in d['keys'])
        stage  = d['plan'][d['stage']]
        asking = bool(stage.get('confirm')) and \
            (self.owner._cal_state or '').endswith('_confirm')

        # Nothing to say if neither the question nor the readings have moved.
        sig = (d['stage'], tuple((k, now.get(k)) for k in d['keys']))
        if d.get('shown') == sig:
            return
        d['shown'] = sig

        lines = ["  %-36s %s" % (self._SEN_LABEL[k], self._sen_word(now.get(k)))
                 for k in d['keys']]
        self._emit_ui_prompt(
            gcmd, self._ui_title(),
            ("%s — path %d" % (self._SEN_TITLE[d['group']], path) + NL + NL
             + NL.join(lines) + NL + NL
             + stage['ask']
             + ((NL + NL + stage['why']) if stage.get('why') else "")
             + NL + NL
             + ("Nothing is driven." if asking else
                "Nothing is driven — this waits for the readings to change.")
             + NL + "Stage %d of %d." % (d['stage'] + 1, len(d['plan']))),
            ([(stage['confirm'], 'yes', 'primary'),
              ("NOT YET", 'no', 'secondary')] if asking else []),
            footer=[("STOP", "abort", "error")])

    def sensor_poll(self, gcmd):
        """One read. Re-armed by the delayed_gcode while the test runs."""
        owner = self.owner
        st    = owner._cal_state or ''
        waiting  = st.startswith('sen_') and st.endswith('_wait')
        asking   = st.startswith('sen_') and st.endswith('_confirm')
        if not (waiting or asking):
            return

        if asking:
            # Keep the readings live so they can be watched changing, but do
            # not advance on them: this stage is answered by the operator.
            d = owner._cal_data
            now = dict((k, self._sen_read(d['path'], k)[1]) for k in d['keys'])
            if owner.reactor.monotonic() > d['deadline']:
                self._sen_fault(gcmd, 'stuck', now, None)
                return
            self._sen_render(gcmd, now)
            self._sen_arm()
            return

        d     = owner._cal_data
        path  = d['path']
        stage = d['plan'][d['stage']]
        now   = dict((k, self._sen_read(path, k)[1]) for k in d['keys'])

        satisfied = all(now.get(k) == v for k, v in stage['want'].items())

        # The far sensor leading the near one means they are crossed. This is
        # the fault worth catching: during a Bowden blast the stop signal would
        # come from a sensor the filament has not reached.
        wrong = stage.get('wrong_first')
        if wrong and now.get(wrong) and not satisfied:
            self._sen_fault(gcmd, 'swapped', now, wrong)
            return

        if satisfied:
            d['stage'] += 1
            d['deadline'] = owner.reactor.monotonic() + self._SEN_TIMEOUT
            if d['stage'] >= len(d['plan']):
                self._sen_done(gcmd)
                return
            self._sen_render(gcmd)
            self._sen_arm()
            return

        if owner.reactor.monotonic() > d['deadline']:
            self._sen_fault(gcmd, 'stuck', now, None)
            return

        # Only when something actually moved. A prompt is delivered as
        # prompt_end + prompt_begin, so re-raising it every poll tears the
        # dialog down and rebuilds it four times a second -- which is what the
        # flashing was. The endstop test has always worked this way.
        self._sen_render(gcmd, now)
        self._sen_arm()

    def _sen_fault(self, gcmd, kind, now, wrong):
        owner = self.owner
        d     = owner._cal_data
        path  = d['path']
        self._sen_disarm()
        owner._cal_state = 'sen_%s_fault' % d['group']

        readings = NL.join("  %-36s %s" % (self._SEN_LABEL[k],
                                           self._sen_word(now.get(k)))
                           for k in d['keys'])
        if kind == 'inverted':
            body = ("You said it is empty, but %s reads FILAMENT."
                    % self._SEN_LABEL[wrong] + NL + NL
                    + "Usually the pin polarity: add or remove the '!' on that "
                      "sensor's switch_pin." + NL
                    + "If the pin is right, the switch or lever is stuck."
                    + NL + NL
                    + "Left alone, this path would be recorded as proved.")
        elif kind == 'swapped':
            near = [k for k in d['plan'][d['stage']]['want']][0]
            body = ("%s read FILAMENT first. These two are crossed."
                    % self._SEN_LABEL[wrong] + NL + NL
                    + "The filament reaches the near sensor first, so swap the "
                      "two connectors at the toolhead -- or swap "
                      "extruder_sensor_%d and toolhead_sensor_%d." % (path, path)
                    + NL + NL
                    + "Fix this before the Bowden step: it stops on the "
                      "extruder sensor at speed.")
        else:
            stage = d['plan'][d['stage']]
            body = ("Nothing changed in %.0f seconds." % self._SEN_TIMEOUT
                    + NL + NL
                    + "If the filament moved and the reading did not, check "
                      "the connector at both ends and that the lever actually "
                      "moves." + NL
                    + "If it is stuck on FILAMENT while empty, the pin needs "
                      "inverting.")

        self._emit_ui_prompt(
            gcmd, self._ui_title(),
            ("%s — path %d" % (self._SEN_TITLE[d['group']], path) + NL + NL
             + readings + NL + NL + body),
            [("TRY AGAIN", "retry", "primary")],
            footer=[("STOP", "abort", "error")])

    def _sen_done(self, gcmd):
        owner = self.owner
        d     = owner._cal_data
        path  = d['path']
        group = d['group']
        self._sen_disarm()
        proved = (["Empty read CLEAR, and filament read FILAMENT.",
                   "It cleared again when you pulled it out."]
                  if group == 'entry' else
                  ["Both read CLEAR when empty.",
                   "The extruder sensor saw the filament first, then the "
                   "toolhead sensor — so they are the right way round.",
                   "Both cleared again when you pulled it out."])
        gcmd.respond_info("SA: %s path %d — all checks passed."
                          % (self._SEN_TITLE[group], path))

        # Record it. Nothing else can: a sensor reading CLEAR looks the same
        # whether it is working or not wired, which is what this test exists to
        # tell apart, so the answer only exists because someone did it by hand.
        key = ('entry_sensor_ok_%d' if group == 'entry'
               else 'toolhead_sensor_ok_%d') % path
        self._save_variable(key, 'True')
        try:
            lst = (owner._entry_sensor_ok if group == 'entry'
                   else owner._toolhead_sensor_ok)
            lst[path] = True
        except Exception:
            logging.exception("SA CAL: could not record the sensor result")

        # Say so on screen, not just in the console. Going straight to the
        # next-path offer made a test that passed look like one that was
        # skipped -- and the list of what it proved was being built and thrown
        # away rather than shown.
        owner._cal_state = 'sen_%s_pass' % group
        self._emit_ui_prompt(
            gcmd, self._ui_title(),
            ("%s — path %d" % (self._SEN_TITLE[group], path) + NL + NL
             + "PASSED. This path's wiring is proved:" + NL + NL
             + NL.join("  \u2713 " + line for line in proved)
             + NL + NL
             + "It stays ticked in the guide, so you can see at a glance which "
               "paths are still to do."),
            [("CONTINUE", "next", "primary")],
            footer=[("STOP", "abort", "error")])

    def _sen_respond(self, gcmd, state, value):
        owner = self.owner
        d     = owner._cal_data

        if state.endswith('_pass'):
            path, group = d.get('path', 0), d.get('group', 'entry')
            self._clear()
            self._offer_next_path(
                gcmd,
                'entry_sensors' if group == 'entry' else 'toolhead_sensors',
                path,
                'SA_TEST_ENTRY_SENSORS TOOL=%d' if group == 'entry'
                else 'SA_TEST_TOOLHEAD_SENSORS TOOL=%d',
                self._SEN_TITLE[group])
            return

        if state.endswith('_home'):
            # G28, deliberately, and not a hunt for a HOME_ALL-ish macro.
            # Klipper's [homing_override] and a [gcode_macro G28] with
            # rename_existing both work by INTERCEPTING G28, so issuing it is
            # what runs whatever the printer defines -- on this machine that is
            # a homing_override covering xyz which initialises the toolchanger
            # and checks the probe first. A printer with no override gets the
            # built-in homing from the same command.
            gcmd.respond_info("SA: homing (G28)...")
            owner.gcode.run_script_from_command("G28")
            owner.gcode.run_script_from_command("M400")
            path  = d['path']
            stage = d['plan'][d['stage']]
            if self._sen_action(gcmd, stage['action'], path) == 'need_home':
                # G28 ran and the axes still are not homed. Something is wrong
                # with homing itself, and this test is not the place to chase it.
                self._sen_ask_home(gcmd)
                return
            self._sen_advance(gcmd)
            return

        if state.endswith('_confirm'):
            v = str(value).strip().lower()
            if v not in ('yes', 'y', '1', 'true', 'ok'):
                d['shown'] = None          # redraw the question
                self._sen_render(gcmd)
                self._sen_arm()
                return

            path  = d['path']
            stage = d['plan'][d['stage']]

            # Some stages do something once permission is given. It runs before
            # the readings are judged, because on this test the thing it does
            # is bring the sensors being judged into the room.
            if stage.get('action'):
                if self._sen_action(gcmd, stage['action'], path) == 'need_home':
                    self._sen_ask_home(gcmd)
                    return

            # The operator says it is empty. Now the reading means something:
            # anything not CLEAR is the sensor being wrong, and this is the
            # only moment in the test when that can be established.
            now = dict((k, self._sen_read(path, k)[1]) for k in d['keys'])
            bad = [k for k, want in stage['want'].items() if now.get(k) != want]
            if bad:
                self._sen_fault(gcmd, 'inverted', now, bad[0])
                return

            self._sen_advance(gcmd)
            return

        if str(value).strip().lower() == 'retry':
            d['stage'] = 0
            d['shown'] = None
            d['deadline'] = owner.reactor.monotonic() + self._SEN_TIMEOUT
            # Back to stage 0 means back to its question, if it has one --
            # otherwise a retry would walk straight past the empty check that
            # the retry usually exists to redo.
            owner._cal_state = (
                'sen_%s_confirm' % d['group']
                if d['plan'][0].get('confirm') else 'sen_%s_wait' % d['group'])
            self._sen_render(gcmd)
            self._sen_arm()
            return
        self._sen_disarm()
        self._clear()
        gcmd.respond_info("SA: sensor test stopped.")

    def start_endstop_test(self, gcmd):
        owner = self.owner
        state, name = owner._selector_endstop_state()
        if state is None:
            gcmd.respond_info(
                "SA: Could not read an endstop for the selector (looked for "
                "'%s').%s    Check that the selector's manual_stepper has an "
                "endstop_pin in hardware.cfg." % (name, NL))
            return
        # Start by confirming the state it is ALREADY in, rather than waiting
        # blind for a change. The switch is in one of two states right now and
        # the operator can see which -- so ask about that one, then ask them to
        # move to the other. Waiting first meant the screen opened with an
        # instruction to move somewhere the carriage might already be.
        owner._cal_data = {
            'name': name,
            'first': bool(state),
            'seen': [bool(state)],
            'deadline': owner.reactor.monotonic() + self._END_TIMEOUT,
        }
        owner._cal_state = 'end_confirm'
        self._end_render_confirm(gcmd)

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
        # Action first, and no fault language: nothing has gone wrong yet, and
        # leading with what to check when it does reads as though something
        # has. The stuck screen says all that, at the point where it is true.
        do = ("Now push the carriage ON to the switch." if want else
              "Now move the carriage OFF the switch.")
        self._emit_ui_prompt(
            gcmd, self._ui_title(),
            (do + " It reads %s until you do." % self._end_word(now).upper()),
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
                     + "It stayed on %s the whole time."
                       % self._end_word(prev).upper() + NL + NL
                     + "Either the carriage never reached the switch, or the "
                       "switch is not reaching the board." + NL + NL
                     + "Check the wiring and the SA_SELECTOR_STOP pin."),
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
            # Short on purpose. Four buttons leave a few lines of room on a
            # 480px screen, and this used to run long enough that the part
            # saying what the reading MEANS scrolled off the top -- leaving a
            # yes/no question with the answer above the fold. What to do when
            # it is backwards has its own screen; it does not belong here.
            ("It reads %s, which means %s. Is it?"
             % (self._end_word(now).upper(), self._end_meaning(now))),
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
            self.owner._endstop_ok = True
            self._save_variable('endstop_ok', 'True')
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
                batch = {}
                for i, pos in enumerate(positions):
                    owner._selector_positions[i] = pos
                    batch['selector_position_%d' % i] = round(float(pos), 2)
                self._save_variables(batch)
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

        # No select here: this routine ASKS which path has filament, so there
        # is nothing to select yet. _drv_respond does it once the answer is in.
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
                      "exactly how far it traveled."),
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
                    "traveled." + NL + NL
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
                # While the gear still holds it: after servo_disengage there
                # is nothing left to drive the filament with.
                self._enc_return(gcmd, measured)
                motion.servo_disengage()
                owner._cal_state = 'drv_save'
                self._prompt(gcmd,
                    "Save rotation_distance=%.4f?" % new_rd,
                    "SA_RESPOND VALUE=yes",
                    "SA_RESPOND VALUE=no")
            else:
                # Back to the datum. The pass left the tip proud of the gate by
                # what was measured, so wind that back before releasing rather
                # than making the operator turn the knob 100mm every pass.
                # _ENC_CAL_LEAVE is left for them to nudge flush.
                self._enc_return(gcmd, measured)
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
                # Live, and persisted where the updater cannot reach it. Writing
                # hardware.cfg instead meant the value was lost on the next pull
                # and the drive quietly ran on the repo's default until a second
                # restart put it back.
                self.owner.apply_drive_rotation_distance(new_rd)
                ok, result = True, ''
                if ok:
                    gcmd.respond_info(
                        "SA CAL: rotation_distance=%.4f saved and applied — no "
                        "restart needed. 100mm now means 100mm." % new_rd)
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

    # Feed per pass. Long enough that eyeballing the tip flush and reading the
    # rule -- a fixed few mm either way -- stops dominating: +/-3mm is 3% of
    # 100mm and 1% of 300mm. 300 still fits a 12in rule.
    _ENC_CAL_LENGTH = 300.0

    # Left sticking out of the gate for the operator to nudge flush by hand.
    # Enough to see and pinch, little enough to be quick.
    _ENC_CAL_LEAVE = 10.0
    # How much of the datum is approached in small steps. The rest is one
    # continuous move: stepping the whole way means a full stop every 10mm,
    # which is 25 of them for a 300mm datum and most of the time this took.
    # The stepping exists so the encoder can be read between moves -- reading
    # it once after a long move is the same thing with less stopping.
    _ENC_CAL_PECK = 50.0

    def _enc_return(self, gcmd, actual):
        """Drive the filament back to roughly the datum.

        Needs the motor energised, so it must run before drive_disable() --
        and, on the last pass, before the servo lets go of the filament.
        """
        owner = self.owner
        back  = actual - self._ENC_CAL_LEAVE
        if back <= 0.0:
            return 0.0
        owner.motion.drive_move(-back, speed=owner.feed_speed * 0.5)
        gcmd.respond_info(
            "SA CAL: wound back %.0fmm — about %.0fmm left to set by hand."
            % (back, self._ENC_CAL_LEAVE))
        return back

    def calibrate_encoder(self, gcmd):
        """Phase 0 — select path, engage, release the motor, set the datum."""
        owner = self.owner
        path  = gcmd.get_int('TOOL', minval=0, maxval=owner.num_paths - 1)
        length = gcmd.get_float('LENGTH', self._ENC_CAL_LENGTH, minval=50.)

        if owner._cal_state is not None:
            self._busy(gcmd)
            return

        if not owner._selector_homed:
            gcmd.respond_info("SA CAL: Selector not homed — homing now...")
            owner.motion.selector_home()

        gcmd.respond_info(
            "SA ENCODER CALIBRATION — Path %d\n"
            "==================================\n"
            "Feeds until the encoder reads %.0fmm, you measure what actually\n"
            "came out of the gate — 3 passes, averaged. No mark or tape needed.\n"
            "\n"
            "Requirements: filament through drive gear AND encoder for path %d,\n"
            "with ~%.0fmm free past the gate, and a rule that long."
            % (path, length, path, length + 50.0))

        gcmd.respond_info("SA CAL: Selecting path %d..." % path)
        self._safe_selector_move(owner.motion, owner._selector_positions[path])
        owner.current_path = path

        # Gear holding, motor released — that is what makes the knob feed the
        # filament by hand. Engaging without releasing locks it solid, which is
        # exactly what this step is asking the operator to work against.
        owner.motion.servo_engage()
        owner.motion.drive_disable()

        enc = owner._encoder(path)
        owner._cal_data  = {
            'path':         path,
            'attempt':      0,
            'target':       length,
            'ratios':       [],
            'best_mpp':     enc.mm_per_pulse,
            'original_mpp': enc.mm_per_pulse,
        }
        owner._cal_state = 'enc_mark_%d' % path

        self._prompt(gcmd,
            "Set the filament tip flush with the gate exit.",
            "SA_RESPOND VALUE=yes",
            detail=("The drive gear is holding the filament and the motor is "
                    "released, so the knob feeds it by hand." + NL
                    + "Then it feeds until the encoder reads %.0fmm and you "
                      "measure what came out." % length))

    def _enc_respond(self, gcmd, state, value):
        owner  = self.owner
        motion = owner.motion
        data   = owner._cal_data
        path   = int(state.rsplit('_', 1)[-1])
        enc    = owner._encoder(path)

        if state.startswith('enc_mark_'):
            attempt        = data['attempt'] + 1
            data['attempt'] = attempt
            target         = data.get('target') or self._ENC_CAL_LENGTH
            max_travel     = target * 2.0 + 100.0
            poll_interval  = 0.05   # seconds between encoder checks
            cal_speed      = owner.feed_speed * 0.5

            # Every pass runs at the SAME scale — the one we started with — so
            # the three are independent samples of one ratio and can be
            # averaged. Feeding each pass the previous pass's answer made them
            # a chain instead, where only the last one really counted.
            enc.mm_per_pulse = data['original_mpp']

            # Seat the gear FIRST. servo_engage jitters the drive ±0.8mm three
            # times, and resetting before that counted all 4.8mm of it as feed
            # — five counts of distance the filament never travelled, which
            # made every pass read about 1.6% low.
            dn = owner._drv_name()
            motion.servo_engage()
            enc.set_direction(forward=True)
            enc.reset_distance()
            motion._cancel_timeout(dn)
            owner.gcode.run_script_from_command(
                "MANUAL_STEPPER STEPPER=%s ENABLE=1" % dn)

            gcmd.respond_info(
                "SA CAL: Attempt %d/3 — stepping until encoder reads "
                "%.0fmm (mm_per_pulse=%.5f)..."
                % (attempt, target, data['original_mpp']))

            # Step-by-step: motor stops fully between steps so encoder
            # pulses are delivered one-by-one (no CAN batching issue).
            # Fast approach until 80% of target, then 3mm precision steps.
            fast_step     = 10.0
            slow_step     = 3.0
            slow_threshold = target - 15.0
            travelled     = 0.0

            # The bulk in one move, the last _ENC_CAL_PECK in steps. Guarded
            # so a short LENGTH= still pecks the whole way rather than making
            # one blind move at a datum too small to correct afterwards.
            opening = target - self._ENC_CAL_PECK
            if opening > fast_step:
                motion.drive_move(opening, speed=cal_speed)
                travelled += opening

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
                "How much filament is sticking out of the gate?",
                "SA_RESPOND VALUE=%.0f  (replace with what you measured)"
                % target,
                detail=("The gear and motor are both holding, so nothing will "
                        "move while you measure." + NL
                        + "The encoder counted %.2fmm. Measure from the gate "
                          "exit to the tip." % enc_reading),
                numeric={'value': round(target, 0), 'unit': 'mm'})

        elif state.startswith('enc_meas_'):
            # The motor stays energised for now: it has to drive the filament
            # back before it can be released. Releasing here, as this used to,
            # would leave 300mm to wind by hand.
            try:
                actual = float(value)
            except ValueError:
                gcmd.respond_info("SA CAL: Enter a number (e.g. 199.5).")
                return
            if actual <= 0.0:
                gcmd.respond_info("SA CAL: Must be > 0.")
                return

            orig_mpp    = data['original_mpp']
            attempt     = data['attempt']
            enc_reading = data['enc_reading']
            target      = data.get('target') or self._ENC_CAL_LENGTH

            # One sample, not a correction. enc_reading rather than the target
            # because the feed steps in 3mm chunks and overshoots slightly.
            ratio = actual / enc_reading
            data.setdefault('ratios', []).append(ratio)
            ratios  = data['ratios']
            new_mpp = orig_mpp * (sum(ratios) / len(ratios))
            data['best_mpp'] = new_mpp

            done = (attempt >= 3)
            gcmd.respond_info(
                "SA CAL: Pass %d/3 — encoder %.2fmm  measured %.2fmm  "
                "(%.2f%% out)\n"
                "  running mean of %d: mm_per_pulse %.5f → %.5f%s"
                % (attempt, enc_reading, actual, (ratio - 1.0) * 100.0,
                   len(ratios), orig_mpp, new_mpp, "  ✓ done" if done else ""))

            if done:
                # Three numbers that disagree badly are not worth averaging --
                # say so rather than handing back a confident-looking mean.
                spread = (max(ratios) - min(ratios)) * 100.0
                if spread > 4.0:
                    self._enc_return(gcmd, actual)
                    motion.drive_disable()
                    data['attempt'] = 0
                    data['ratios']  = []
                    owner._cal_state = 'enc_mark_%d' % path
                    self._prompt(gcmd,
                        "Those three disagree by %.1f%% — start over?" % spread,
                        "SA_RESPOND VALUE=yes",
                        detail=("Measured %s against %.0fmm."
                                % (", ".join("%.0f" % (r * enc_reading)
                                             for r in ratios), target)
                                + NL + NL
                                + "That is measurement scatter, not encoder "
                                  "error, and averaging it just hides it. The "
                                  "usual causes are the tip not being truly "
                                  "flush at the gate to start, and the "
                                  "filament bowing rather than lying straight "
                                  "when measured." + NL + NL
                                + "It is wound back for you — nudge the last "
                                  "%.0fmm flush and run the three again."
                                  % self._ENC_CAL_LEAVE))
                    return

                # Before the gear lets go, or there is nothing to drive it
                # with and the path is left with 300mm hanging out.
                self._enc_return(gcmd, actual)
                motion.drive_disable()
                motion.servo_disengage()
                owner._cal_state = 'enc_save_%d' % path
                self._prompt(gcmd,
                    "Save mm_per_pulse=%.5f?" % new_mpp,
                    "SA_RESPOND VALUE=yes",
                    "SA_RESPOND VALUE=no",
                    detail=("Mean of 3 passes, spread %.1f%%  (%s)"
                            % ((max(ratios) - min(ratios)) * 100.0,
                               ", ".join("%+.1f%%" % ((r - 1.0) * 100.0)
                                         for r in ratios))
                            + NL
                            + "Was %.5f, %+.1f%%."
                              % (orig_mpp, (new_mpp / orig_mpp - 1.0) * 100.0)))
            else:
                # Drive it back first, then release so the knob can do the
                # last few mm against the gate.
                self._enc_return(gcmd, actual)
                motion.drive_disable()
                owner._cal_state = 'enc_mark_%d' % path
                self._prompt(gcmd,
                    "Nudge the last %.0fmm flush with the gate exit."
                    % self._ENC_CAL_LEAVE,
                    "SA_RESPOND VALUE=yes",
                    detail=("Wound back for you; the motor is released and the "
                            "gear is still holding, so the knob does the rest."
                            + NL + "Pass %d of 3 next." % (attempt + 1)))

        elif state.startswith('enc_save_'):
            new_mpp  = data['best_mpp']
            orig_mpp = data.get('original_mpp') or new_mpp
            self._clear()

            if self._yes(value):
                enc.mm_per_pulse = new_mpp
                # Record which edge counting produced it, so a later change of
                # mode can tell a measured value from a legacy one. Written
                # WITH the scale in one rewrite: they describe the same
                # measurement and a file rewrite each is the pattern that
                # starved the autoloader MCU.
                try:
                    edges = 2 if self.owner._encoder(path).count_both_edges else 1
                except Exception:
                    edges = 2
                self._save_variables({
                    'encoder_mpp_%d'   % path: round(float(new_mpp), 5),
                    'encoder_edges_%d' % path: int(edges),
                })
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
                # Back to the guide FIRST, then park. The UI shows the guide
                # only while guide_open and no prompt is waiting, so parking
                # before this ran left it hidden for the whole move -- which
                # reads as "you are finished" rather than "wait". Now the page
                # is already up and the park happens underneath it.
                self._offer_next_path(gcmd, 'encoder', path,
                                      'SA_CALIBRATE_ENCODER TOOL=%d',
                                      'Encoder mm/pulse')
                # Say it before it moves: filament moving on its own with no
                # explanation is worse than the wait.
                gcmd.respond_info("SA CAL: Parking path %d..." % path)
                try:
                    self.owner.sequences.park_filament(gcmd, path)
                except Exception as e:
                    gcmd.respond_info(
                        "SA CAL: mm_per_pulse saved, but parking path %d "
                        "failed: %s" % (path, e))
            else:
                enc.mm_per_pulse = orig_mpp
                gcmd.respond_info(
                    "SA CAL: Not saved. mm_per_pulse remains %.5f." % orig_mpp)

    # ══════════════════════════════════════════════════════════════════════════
    # SA_CALIBRATE_ENCODER_SPEED
    # ══════════════════════════════════════════════════════════════════════════

    # ══════════════════════════════════════════════════════════════════════
    # SA_VERIFY_FEED — check a feed speed against a ruler
    # ══════════════════════════════════════════════════════════════════════

    def verify_feed(self, gcmd):
        """Drive one pass at a chosen speed and have the operator measure it.

        The speed test can only compare the encoder against the stepper, so a
        failing pass is ambiguous: a motor losing steps and an encoder missing
        counts produce the same short reading. A ruler is outside both.
        """
        owner  = self.owner
        motion = owner.motion

        if owner._cal_state is not None:
            self._busy(gcmd)
            return

        path = gcmd.get_int('TOOL', None, minval=0, maxval=owner.num_paths - 1)
        if path is None:
            path = owner.current_path if owner.current_path >= 0 else 0

        speed = gcmd.get_float('SPEED', None, above=0.)
        if speed is None:
            speed = self._vf_default_speed(path)

        cap   = self._encspeed_cap(path)
        floor = self._encspeed_floor(path)
        dist  = gcmd.get_float('DIST', None, above=0.)
        if dist is None:
            dist, _ = self._encspeed_distance(speed, cap, floor)
            if dist is None:
                dist = cap
        dist = min(dist, cap)

        if not owner._selector_homed:
            gcmd.respond_info("SA CAL: Selector not homed — homing now...")
            motion.selector_home()

        gcmd.respond_info(
            "SA FEED VERIFICATION — path %d at %.0fmm/s\n"
            "===========================================\n"
            "The speed test compares the encoder against the stepper, so a\n"
            "failure could be either one. This measures the filament instead."
            % (path, speed))

        owner._cal_data = {'path': path, 'speed': speed, 'dist': dist,
                           'counted': None}
        motion.servo_disengage()
        motion.selector_move_to(owner._selector_positions[path])
        owner.current_path = path
        self._vf_setup(gcmd)

    def _vf_default_speed(self, path):
        """The rung above the one this channel passed — the disputed speed.

        Testing at a speed that already passed proves little; the interesting
        one is the first that did not.
        """
        try:
            sv = self.owner.printer.lookup_object('save_variables', None)
            safe = float(sv.allVariables.get('encoder_max_speed_%d' % path, 0.0))
        except Exception:
            safe = 0.0
        passed = safe / 0.80 if safe else 0.0
        for sp in self._ENC_SPEEDS:
            if sp > passed + 0.5:
                return float(sp)
        return float(self._ENC_SPEEDS[-1])

    def _vf_setup(self, gcmd):
        """Servo holding, motor released: the knob feeds it by hand."""
        owner  = self.owner
        motion = owner.motion
        d      = owner._cal_data

        motion.servo_engage()
        motion.drive_disable()
        owner._cal_state = 'vf_setup'
        self._emit_ui_prompt(
            gcmd, self._ui_title(),
            ("Feed check — path %d at %.0fmm/s" % (d['path'], d['speed'])
             + NL + NL
             + "The drive gear is holding the filament and the motor is "
               "released, so the knob feeds it by hand." + NL + NL
             + "Set the filament tip flush with the gate exit." + NL + NL
             + "Then it drives %.0fmm at %.0fmm/s and you measure what came "
               "out. No tape or marker — the gate is the datum."
               % (d['dist'], d['speed'])),
            [("FEED IT", "go", "primary")],
            footer=[("STOP", "abort", "error")])

    def _vf_drive(self, gcmd):
        """One measured pass at the speed under test."""
        owner  = self.owner
        motion = owner.motion
        d      = owner._cal_data
        enc    = owner._encoder(d['path'])

        enc.set_direction(forward=True)
        enc.reset_distance()
        motion.drive_move(d['dist'], speed=float(d['speed']))
        owner.reactor.pause(owner.reactor.monotonic() + 0.25)
        d['counted'] = enc.get_distance()

        gcmd.respond_info(
            "SA CAL: drove %.1fmm at %.0fmm/s; encoder counted %.1fmm"
            % (d['dist'], d['speed'], d['counted']))

        owner._cal_state = 'vf_meas'
        self._prompt(
            gcmd, "How much filament came out of the gate?",
            "SA_RESPOND VALUE=<measured mm>",
            detail=("Drove %.1fmm at %.0fmm/s. The encoder counted %.1fmm."
                    % (d['dist'], d['speed'], d['counted'])
                    + NL + "Measure from the gate exit to the tip."),
            numeric={'value': round(d['dist'], 0), 'unit': 'mm'})

    def _vf_verdict(self, gcmd, measured):
        """Three numbers, and which of them disagree."""
        owner = self.owner
        d     = owner._cal_data
        cmd_mm  = d['dist']
        counted = d['counted'] or 0.0
        path    = d['path']

        try:
            mpp = float(owner._encoder(path).mm_per_pulse)
        except Exception:
            mpp = 0.0

        # The encoder cannot do better than its own resolution; the operator
        # cannot do better than a couple of mm with a tape measure.
        enc_tol   = max(2.0 * mpp, cmd_mm * 0.01)
        ruler_tol = max(3.0, cmd_mm * 0.01)

        moved_ok = abs(measured - cmd_mm) <= ruler_tol
        enc_ok   = abs(counted - cmd_mm) <= enc_tol
        enc_matches_ruler = abs(counted - measured) <= enc_tol + ruler_tol

        if moved_ok and enc_ok:
            verdict = ("Both agree with the ruler. %.0fmm/s is genuinely good "
                       "on this path." % d['speed'])
        elif moved_ok and not enc_ok:
            # Work the ceiling out from this measurement rather than from the
            # tooth pitch. The first version assumed the sensor was high for
            # half of each tooth and produced a figure well below what the
            # machine had already passed -- the duty cycle is not 50%, and
            # guessing it is worse than measuring it.
            #
            # Klipper samples the pin every SAMPLE seconds, so a state must
            # last that long to be seen. Missing a fraction L of the counts
            # puts the active window at (1-L)*SAMPLE, and the speed at which
            # misses begin is that window divided by SAMPLE again -- which is
            # just (1-L) times the speed that was tested.
            SAMPLE = 0.002
            lost = ((measured - counted) / measured) if measured > 0 else 0.0
            lost = min(max(lost, 0.0), 0.99)
            window = (1.0 - lost) * SAMPLE * d['speed']
            ceiling = (1.0 - lost) * d['speed']
            verdict = ("The filament moved the full distance — the encoder is "
                       "what fell short. This is an ENCODER ceiling, not a "
                       "drive one." + NL + NL
                       + "It missed %.1f%% of its counts. Klipper samples that "
                         "pin every %.0fms, so a state has to last that long "
                         "to be seen; losing that many puts this sensor's "
                         "active window at about %.2fmm of travel — so counts "
                         "start going missing around %.0fmm/s."
                         % (lost * 100.0, SAMPLE * 1000.0, window, ceiling)
                       + NL + NL
                       + "Feeding faster than that works. Reading it does not.")
        elif not moved_ok and enc_matches_ruler:
            verdict = ("The filament really did not move that far, and the "
                       "encoder said so. This is a DRIVE ceiling: steps lost "
                       "at speed, or the gear slipping on the filament."
                       + NL + NL
                       + "Lower accel, more run_current, or a lower feed "
                         "speed. The encoder is reporting honestly.")
        else:
            verdict = ("The filament is short and the encoder does not agree "
                       "with it either. That points at the gear slipping "
                       "underneath the encoder wheel while the wheel keeps "
                       "turning — check the wheel's grip and its tension.")

        owner._cal_state = 'vf_done'
        self._emit_ui_prompt(
            gcmd, self._ui_title(),
            ("Feed check — path %d at %.0fmm/s" % (path, d['speed'])
             + NL + NL
             + "  commanded   %7.1fmm" % cmd_mm + NL
             + "  encoder     %7.1fmm   (%+.1fmm)" % (counted, counted - cmd_mm)
             + NL
             + "  ruler       %7.1fmm   (%+.1fmm)" % (measured, measured - cmd_mm)
             + NL + NL + verdict),
            [("TEST AGAIN", "again", "secondary"),
             ("DONE", "done", "primary")],
            footer=[("STOP", "abort", "error")])

    def _vf_respond(self, gcmd, state, value):
        owner = self.owner
        v     = str(value).strip().lower()

        if state == 'vf_setup':
            self._vf_drive(gcmd)
            return

        if state == 'vf_meas':
            try:
                measured = float(value)
            except (TypeError, ValueError):
                gcmd.respond_info("SA CAL: Enter the measured length in mm.")
                return
            if measured < 0.0:
                gcmd.respond_info("SA CAL: That cannot be negative.")
                return
            self._vf_verdict(gcmd, measured)
            return

        if state == 'vf_done':
            if v == 'again':
                owner._cal_data['counted'] = None
                self._vf_setup(gcmd)
                return
            owner.motion.servo_disengage()
            self._clear()
            gcmd.respond_info("SA CAL: Feed check finished.")
            return

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
            "Tests 25→%dmm/s, 3 passes each. Pass length follows the speed "
            "and this path's encoder resolution."
            % ("path %d" % one if one is not None
               else "all %d paths" % owner.num_paths,
               self._ENC_SPEEDS[-1]))

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
                   # Finer through the region the ceiling actually falls in:
                   # 2ms pin sampling puts the design limit near 219mm/s, and
                   # a single 200 -> 250 rung recorded everything in that band
                   # as 200. Coarse again above it, where the answer is only
                   # "faster than anything this will be asked for".
                   215, 230, 245, 265, 285, 305, 325,
                   350, 400, 450, 500]

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

    # A pass has to be long enough for the encoder to resolve it. These are
    # coarse -- around 1.9mm per pulse, so a 100mm pass is 53 counts and a
    # single miscount is already 1.9% of a 5% tolerance. At 200 counts two
    # miscounts are 1.0%, which leaves the tolerance measuring slip rather than
    # quantisation.
    _ENC_MIN_PULSES = 200

    # Ceiling on the return move. It only has to be safe, not slow, and at
    # these pass lengths a fixed 25mm/s would have doubled the sweep.
    _ENC_RETURN_MAX = 100.0

    # Driven slowly before each measured pass, and not measured. Every pass
    # follows a reversal, and the gear spends the first few mm taking slack out
    # of the filament rather than feeding it -- charged to the pass as error if
    # the encoder is reset before it happens. Measured at ~3.8mm on a 1270mm
    # tube; 10mm covers that with room for a longer or tighter one.
    _ENC_TAKEUP = 10.0

    def _encspeed_floor(self, path):
        """Shortest pass that this path's encoder can resolve, in mm."""
        try:
            mpp = float(self.owner._encoder(path).mm_per_pulse)
        except Exception:
            mpp = 0.0
        if mpp <= 0.0:
            return self._ENC_MIN_DIST
        return max(self._ENC_MIN_DIST, self._ENC_MIN_PULSES * mpp)

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

    def _encspeed_distance(self, speed, cap, floor=None):
        """How far to drive so *speed* is held, not merely touched.

        A move ramps up, maybe cruises, then ramps down. Accelerating to v and
        back costs v^2/a of travel and spends none of it at v. The cruise on top
        is what the test is actually reading.

        Returns (distance, cruise_mm). Distance is None when it does not fit in
        *cap*, and the second value is then the distance it would have needed --
        so the rung is reported as untested rather than passed on a speed the
        move never reached.
        """
        if floor is None:
            floor = self._ENC_MIN_DIST
        floor = min(floor, cap)               # a short tube still wins
        accel = self._drive_accel()
        if accel <= 0.0:
            return floor, 0.0                 # accel unknown: just use the floor
        ramp = (speed * speed) / accel        # up and down together
        want = ramp * (1.0 + self._ENC_CRUISE_FRAC)
        if want <= floor:
            # The floor already dwarfs the ramp; all the rest is cruise.
            return round(floor, 0), floor - ramp
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
        # Short because it is repeated on every screen of the sweep. Why the
        # slowest pass is the reference, and why that cancels a scale error,
        # is on the guide page for this step where there is room for it.
        return ("Figures are how far the encoder was from the distance "
                "driven. Under 5% passes; two of three must pass.")

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

        d.update({'at': path, 'si': 0, 'ai': 0, 'errors': [], 'errors_mm': [],
                  'per_speed': [], 'max_pass': 0, 'ref_ratio': None})
        owner._cal_state = 'enc_speed_run'
        self._encspeed_show(gcmd)
        self._encspeed_arm()

    def _encspeed_show(self, gcmd, note=""):
        d    = self.owner._cal_data
        # A row per rung again: Mainsail renders each as its own paragraph,
        # so this is a readable table there. The touchscreen gets the head
        # line instead, passed as ks_line below.
        done = d.get('per_speed', [])
        rows = ["%3dmm/s  %s" % (sp, txt) for sp, txt in done]
        si   = d.get('si', 0)
        speed = (self._ENC_SPEEDS[si] if si < len(self._ENC_SPEEDS) else 0)
        dist, cruise = d.get('dist', 0.0), d.get('cruise', 0.0)
        geom = ("  %.0fmm pass, %.0fmm at speed" % (dist, cruise)
                if dist else "")
        if dist:
            try:
                mpp = float(self.owner._encoder(d.get('at', 0)).mm_per_pulse)
                geom += ", %d counts" % int(dist / mpp)
            except Exception:
                pass
        head = (note or ("Now %dmm/s, pass %d/3%s"
                         % (speed, d.get('ai', 0) + 1, geom)))
        self._emit_ui_prompt(
            self.owner.gcode if gcmd is None else gcmd, self._ui_title(),
            ("Encoder speed test — path %d" % d.get('at', 0)
             + (NL + NL.join(rows) if rows else "")),
            [],
            footer=[("STOP", "abort", "error")],
            # Last, and self-sufficient: names the path's speed, which pass it
            # is on and how much of the move was at speed. A touchscreen
            # showing only this still knows what the machine is doing.
            ks_line="Path %d — %s" % (d.get('at', 0), head))

    def encspeed_step(self, gcmd):
        """One pass. Length follows the speed and the encoder's resolution.

        Called by the delayed_gcode while a sweep runs.
        """
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
        floor = self._encspeed_floor(path)
        dist, cruise = self._encspeed_distance(speed, cap, floor)

        if dist is None:
            # Will not fit in the tube this path feeds. Say so, and say what
            # would change it -- the travel needed falls as v^2/a, so accel is
            # the lever here, not a longer move.
            d['per_speed'].append(
                (speed, "not tested - needs %.0fmm, this path allows %.0fmm "
                        "(accel %.0f would fit it)"
                        % (cruise, cap, self._encspeed_accel_for(speed, cap))))
            d['errors'] = []
            d['errors_mm'] = []
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

        # The fastest speed this channel has already passed is safe to move
        # at, so the return does not have to crawl. 25 until something passes.
        back = max(25.0, min(self._ENC_RETURN_MAX, float(d.get('max_pass') or 0)))

        # Take the slack out first, slowly, with the encoder not yet reset.
        # Measured at ~0 on this drivetrain -- the 3.8mm turned out to be
        # encoder quantisation, not slack -- but a reversal is still the wrong
        # place to start a measurement, and 10mm is cheap on another machine.
        motion.drive_move(self._ENC_TAKEUP, speed=25.0)
        owner.reactor.pause(owner.reactor.monotonic() + 0.1)

        enc.reset_distance()
        motion.drive_move(dist, speed=float(speed))
        owner.reactor.pause(owner.reactor.monotonic() + 0.15)
        counted = enc.get_distance()
        ratio   = (counted / dist) if dist > 0 else 0.0

        # The first pass of a channel is the reference. It runs at the slowest
        # speed on the ladder, where a state lasts several sample periods and
        # aliasing cannot happen, so whatever it reads short is scale -- and
        # scale is present at every speed equally. Comparing later passes to it
        # rather than to the stepper cancels that out.
        if d.get('ref_ratio') is None:
            d['ref_ratio'] = ratio if ratio > 0 else 1.0
        ref = d['ref_ratio'] or 1.0
        err = abs(ratio - ref) / ref
        d['errors'].append(err * 100.0)
        d.setdefault('errors_mm', []).append((ref - ratio) * dist)

        # Give back the take-up as well, so the pass is position-neutral and
        # the filament does not walk down the tube over a fourteen-rung ladder.
        enc.set_direction(forward=False)
        enc.reset_distance()
        motion.drive_move(-(dist + self._ENC_TAKEUP), speed=back)
        owner.reactor.pause(owner.reactor.monotonic() + 0.2)

        d['ai'] = ai + 1
        if d['ai'] < 3:
            self._encspeed_show(gcmd)
            self._encspeed_arm()
            return

        errors = d['errors']
        mms    = d.get('errors_mm') or [0.0] * len(errors)
        passes = sum(1 for e in errors if e <= 5.0)
        ok     = passes >= 2
        avg_mm = sum(mms) / len(mms)
        gcmd.respond_info(
            "  path %d  %3dmm/s: %s  (off by %s%%  avg %.1f%%  %.1fmm)"
            % (path, speed, "PASS" if ok else "FAIL",
               [round(e, 1) for e in errors], sum(errors) / len(errors),
               avg_mm))
        # mm as well as percent: a fixed offset -- slack, backlash, a stiff
        # tube -- stays the same number of mm while the percent moves with the
        # pass length, which is what tells it apart from real slip.
        d['per_speed'].append(
            (speed, "%s  off by %s%%  (%.1fmm)"
                    % ("PASS" if ok else "FAIL",
                       [round(e, 1) for e in errors], avg_mm)))
        d['errors'] = []
        d['errors_mm'] = []
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
        ref  = d.get('ref_ratio') or 1.0
        scale_off = (1.0 - ref) * 100.0        # +ve = reads low at every speed
        d.setdefault('results', {})[path] = {
            'max': max_pass, 'safe': safe, 'scale': scale_off,
            'rows': list(d.get('per_speed', []))}
        if max_pass:
            self._save_variable('encoder_max_speed_%d' % path, '%.1f' % safe)

        owner._cal_state = 'enc_speed_done'
        more = bool(d.get('queue'))
        scale_note = ""
        if abs(scale_off) >= 2.0:
            scale_note = (NL + NL
                          + "Note: at the slowest speed, where aliasing cannot "
                            "happen, this encoder still read %.1f%% %s. That is "
                            "mm_per_pulse being out, not a speed problem — it "
                            "is canceled out of the figures above, but run "
                            "SA_CALIBRATE_ENCODER TOOL=%d to fix the distances "
                            "this path reports everywhere else."
                          % (abs(scale_off), "low" if scale_off > 0 else "high",
                             path))

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
            ("Encoder speed test — path %d done" % path
             + NL + verdict
             + NL + NL.join("%3dmm/s  %s" % (sp, txt)
                            for sp, txt in d.get('per_speed', []))
             + scale_note
             + NL + NL + self._encspeed_explain()),
            buttons,
            footer=[("STOP", "abort", "error")],
            # The verdict alone is the answer this screen exists to give, and
            # it names the path, so it holds up as the only line a touchscreen
            # keeps.
            ks_line="Path %d — %s" % (path, verdict))

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
        slowest = ("shared speed %.0fmm/s (slowest path)" % (min(speeds) * 0.8)
                   if speeds else "no path counted accurately")
        self._emit_ui_prompt(
            gcmd, self._ui_title(),
            ("Encoder speed — all paths"
             + NL + NL.join(rows) + note + NL + NL
             + "Inspect, clean or repair a path and retest just that one; the "
               "others keep their results."),
            buttons,
            footer=[("STOP", "abort", "error")],
            columns=3,
            # The shared speed is the whole point of the sweep: every path runs
            # at the slowest one's pace, so that is the number to carry away.
            ks_line="All paths done — %s" % slowest)

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
            # Carry the path forward before _clear() throws the data away. A
            # sweep of every channel hands on path 0, because the next step is
            # its own per-path run from the start; a sweep of one channel hands
            # on that channel, because that is the one being worked on.
            nxt_path = int(d.get('at') or 0) if d.get('single') else 0
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
            self._offer_next(gcmd, 'enc_speed', path=nxt_path)
            return

    # ══════════════════════════════════════════════════════════════════════════
    # SA_CALIBRATE_BOWDEN
    # ══════════════════════════════════════════════════════════════════════════

    # ══════════════════════════════════════════════════════════════════════
    # Step 12 — toolhead geometry, measured with the path's own encoder
    # ══════════════════════════════════════════════════════════════════════
    #
    # Three measured, two derived:
    #
    #   extruder sensor --[a]-- gear nip --...-- toolhead sensor --[b]-- tip
    #   \________________________[c]________________________/
    #
    #   c  fine sync feed between the two sensors
    #   a  retract until the extruder stops moving filament -- that is the nip
    #   b  extrude until the operator sees filament leave the nozzle
    #
    # Order is c, a, b and it is not arbitrary. `a` has to be measured while
    # the tip is short of the melt zone, so it happens straight after `c` and
    # before anything is heated: pulling a hot tip back past the gears is what
    # tip forming exists for, and doing it here would need the tip former,
    # whose own "clear past gears" move destroys the very event `a` measures.
    # After `a` the tip sits at the extruder sensor edge, so the re-feed for
    # `b` is only `c` millimetres -- and it doubles as a repeatability check.

    _THG_STEP       = 2.0    # mm per increment while hunting an edge
    _THG_SYNC_MAX   = 200.0  # cap: extruder sensor -> toolhead sensor
    _THG_GRIP_MAX   = 200.0  # cap: retract hunting the gear nip
    _THG_CLEAR_MAX  = 200.0  # cap: drive retract to the extruder sensor edge
    _THG_NOZZLE_MAX = 250.0  # cap: total extruded hunting the nozzle tip
    _THG_COARSE     = 10.0   # mm per press, coarse
    _THG_FINE       = 1.0    # mm per press, fine

    def calibrate_toolhead(self, gcmd):
        """Measure c and a cold, then heat and ask the operator for b."""
        owner = self.owner
        seq   = owner.sequences
        path  = gcmd.get_int('TOOL', minval=0, maxval=owner.num_paths - 1)

        if owner._cal_state is not None:
            self._busy(gcmd)
            return

        if not owner._extruder_sensor_names[path]:
            raise gcmd.error(
                "SA CAL: No extruder_sensor_%d configured — step 12 needs it."
                % path)
        if not owner._toolhead_sensor_names[path]:
            raise gcmd.error(
                "SA CAL: No toolhead_sensor_%d configured — step 12 needs it."
                % path)
        if not owner._entry_sensor_active(path):
            raise gcmd.error(
                "SA CAL: No filament at entry of path %d. Load a spool first."
                % path)
        if owner._bowden_lengths[path] <= 0:
            raise gcmd.error(
                "SA CAL: Bowden length for path %d is not calibrated — run "
                "step 11 first." % path)
        if owner._toolhead_sensor_active(path):
            raise gcmd.error(
                "SA CAL: Path %d still has filament at the toolhead. This step "
                "measures from an empty toolhead — unload it first." % path)

        gcmd.respond_info(
            "SA TOOLHEAD GEOMETRY — Path %d\n"
            "==============================" % path)

        if not seq._is_homed():
            gcmd.respond_info("SA CAL: Printer not homed — running G28...")
            owner.gcode.run_script_from_command("G28")

        # Before ANY G1 E. _allow_cold_extrude lowers the floor on THIS path's
        # heater, but G1 E moves whichever extruder the toolhead has active --
        # so with another tool mounted the allowance lands on one extruder and
        # the move on another, and Klipper rejects it with "Extrude below
        # minimum temp". Measured exactly that on the first run of this step.
        seq._switch_tool(gcmd, path)

        # Select, do not merely home. This is the bug that sent path 3's
        # measurement to path 5's gate.
        self._select_path(gcmd, path)

        owner._cal_data  = {'path': path}
        owner._cal_state = 'thg_run_%d' % path

        cold = None
        try:
            cold = seq._allow_cold_extrude(path)
            owner.gcode.run_script_from_command("M83")

            c = self._thg_measure_c(gcmd, path)
            if c is None:
                self._clear()
                return
            a = self._thg_measure_a(gcmd, path, c)
            if a is None:
                self._clear()
                return
        except Exception:
            # Never leave the state set on the way out. The first run raised
            # here and left _cal_state at 'thg_run_1', which makes every later
            # calibration answer "busy" until Klipper restarts.
            self._clear()
            raise
        finally:
            seq._restore_extrude_floor(cold)

        owner._cal_data['c'] = c
        owner._cal_data['a'] = a
        gcmd.respond_info(
            "SA CAL: extruder sensor -> toolhead sensor %.2fmm · "
            "extruder sensor -> gear nip %.2fmm." % (c, a))

        # b needs a hot nozzle and an eye on it.
        self._thg_begin_b(gcmd, path, c)

    # ── c: the span between the two toolhead sensors ─────────────────────
    def _thg_measure_c(self, gcmd, path):
        owner  = self.owner
        seq    = owner.sequences
        motion = owner.motion
        enc    = owner._encoder(path)

        # Belt and braces for the failure that produced this guard: driving
        # the wrong gate reports perfectly healthy encoder motion, because the
        # filament being pushed IS moving -- just the wrong path's.
        self._assert_on_path(gcmd, path)

        if not owner._extruder_sensor_active(path):
            gcmd.respond_info(
                "SA CAL: Feeding path %d to the extruder sensor..." % path)
            motion.servo_engage()
            if not seq._engage_check(gcmd, path):
                gcmd.respond_info("SA CAL: Could not confirm grip — aborted.")
                return None
            if not seq._blast_and_approach(gcmd, path):
                gcmd.respond_info(
                    "SA CAL: Extruder sensor never triggered — aborted.")
                return None
        else:
            motion.servo_engage()

        # Back off to the sensor's CLEAR edge and start from there.
        #
        # Without this the two readings do not measure the same span: the
        # first starts wherever the approach left the tip -- past the TRIGGER
        # point by however far its step overshot -- while the repeat starts at
        # the CLEAR point, and a switch releases at a different position from
        # where it makes. Measured 2026-09-11 on path 1: 44.08 against 49.83,
        # 5.75mm apart, which read as poor repeatability and was nothing of
        # the kind. `a` already ends on the clear edge, so using it here makes
        # every distance in this step share one datum.
        if owner._extruder_sensor_active(path):
            backed = 0.0
            enc.set_direction(forward=False)
            enc.reset_distance()
            while backed < self._THG_CLEAR_MAX:
                if not owner._extruder_sensor_active(path):
                    break
                motion.drive_move(-self._THG_STEP, speed=owner.feed_speed)
                owner.reactor.pause(
                    owner.reactor.monotonic() + owner.sensor_delay)
                backed = abs(enc.get_distance())
            else:
                gcmd.respond_info(
                    "SA CAL: Could not back off to the extruder sensor edge "
                    "in %.0fmm — aborted." % self._THG_CLEAR_MAX)
                return None

        gcmd.respond_info(
            "SA CAL: Measuring extruder sensor -> toolhead sensor in %.0fmm "
            "steps, from the sensor's release edge..." % self._THG_STEP)

        enc.set_direction(forward=True)
        enc.reset_distance()
        moved = 0.0
        dead  = 0
        said  = 0.0
        while moved < self._THG_SYNC_MAX:
            if owner._toolhead_sensor_active(path):
                break
            prev = moved
            motion.drive_move(self._THG_STEP, speed=owner.feed_speed)
            owner.gcode.run_script_from_command(
                "G1 E%.3f F%d"
                % (self._THG_STEP, int(owner.feed_speed * 60.0)))
            owner.gcode.run_script_from_command("M400")
            owner.reactor.pause(
                owner.reactor.monotonic() + owner.sensor_delay)
            moved = abs(enc.get_distance())

            # Say something. Stepping 2mm at a time to a 200mm ceiling is
            # fifty seconds of total silence, which is indistinguishable from
            # a hang -- and was stopped by hand as one.
            if moved - said >= 10.0:
                said = moved
                gcmd.respond_info(
                    "SA CAL: %.0fmm fed, waiting for the toolhead sensor..."
                    % moved)

            # And stop when nothing is actually moving. The encoder is the
            # only thing here that knows the difference between feeding and
            # merely commanding a feed.
            if moved - prev < self._THG_STEP * 0.3:
                dead += 1
                if dead >= 3:
                    gcmd.respond_info(
                        "SA CAL: Drive commanded %.0fmm with no encoder motion "
                        "on path %d — the filament is not moving. Check for a "
                        "jam at the toolhead, or that the drive still has grip. "
                        "Nothing saved."
                        % (dead * self._THG_STEP, path))
                    return None
            else:
                dead = 0
        else:
            gcmd.respond_info(
                "SA CAL: Toolhead sensor never triggered in %.0fmm, though the "
                "filament kept moving. Check the sensor, or that the two are "
                "not crossed (step 10)." % self._THG_SYNC_MAX)
            return None

        return abs(enc.get_distance())

    # ── a: where the extruder gears actually are ─────────────────────────
    def _thg_measure_a(self, gcmd, path, c):
        """Retract until the extruder stops moving filament, then to the edge.

        Pull, never push. Feeding a tip INTO stationary gears would locate
        them just as well and buckles filament in the tube the moment it
        overshoots; losing grip on a retract costs nothing.
        """
        owner  = self.owner
        motion = owner.motion
        enc    = owner._encoder(path)

        gcmd.respond_info(
            "SA CAL: Finding the gear nip — retracting with the extruder "
            "while the drive is released. The encoder still counts because it "
            "is fixed on this lane.")

        motion.servo_disengage()
        owner.reactor.pause(owner.reactor.monotonic() + owner.servo_move_delay)

        enc.set_direction(forward=False)
        enc.reset_distance()
        pulled   = 0.0
        no_motion = 0
        while pulled < self._THG_GRIP_MAX:
            prev = abs(enc.get_distance())
            owner.gcode.run_script_from_command(
                "G1 E-%.3f F%d"
                % (self._THG_STEP, int(owner.feed_speed * 60.0)))
            owner.gcode.run_script_from_command("M400")
            owner.reactor.pause(
                owner.reactor.monotonic() + owner.sensor_delay)
            step_moved = abs(enc.get_distance()) - prev
            pulled = abs(enc.get_distance())
            if step_moved < self._THG_STEP * 0.3:
                no_motion += 1
                # Two in a row, not one: a single short step is quantisation.
                if no_motion >= 2:
                    break
            else:
                no_motion = 0
        else:
            gcmd.respond_info(
                "SA CAL: The extruder never lost grip in %.0fmm. Either it is "
                "gripping something it should not, or the encoder is not "
                "counting — aborted." % self._THG_GRIP_MAX)
            return None

        gcmd.respond_info(
            "SA CAL: Extruder let go after %.2fmm — the tip is at the nip. "
            "Now backing off to the extruder sensor edge." % pulled)

        # The tip sits at the nip, which is `a` DOWNSTREAM of the extruder
        # sensor, so the sensor still reads filament. Retracting until it
        # clears travels exactly that gap.
        if not owner._extruder_sensor_active(path):
            gcmd.respond_info(
                "SA CAL: Extruder sensor already clear — it cannot be between "
                "the sensor and the gears, so this reading would be zero. "
                "Aborted.")
            return None

        motion.servo_engage()
        owner.reactor.pause(owner.reactor.monotonic() + owner.servo_move_delay)
        enc.set_direction(forward=False)
        enc.reset_distance()
        backed = 0.0
        while backed < self._THG_CLEAR_MAX:
            if not owner._extruder_sensor_active(path):
                break
            motion.drive_move(-self._THG_STEP, speed=owner.feed_speed)
            owner.reactor.pause(
                owner.reactor.monotonic() + owner.sensor_delay)
            backed = abs(enc.get_distance())
        else:
            gcmd.respond_info(
                "SA CAL: Extruder sensor never cleared in %.0fmm — aborted."
                % self._THG_CLEAR_MAX)
            return None

        return abs(enc.get_distance())

    # ── b: the operator is the sensor ────────────────────────────────────
    def _thg_begin_b(self, gcmd, path, c):
        """Re-feed to the toolhead sensor, heat, then hand over to the eye."""
        owner  = self.owner
        seq    = owner.sequences
        motion = owner.motion
        enc    = owner._encoder(path)

        gcmd.respond_info(
            "SA CAL: Feeding back to the toolhead sensor — this repeats the "
            "first measurement, so the two should agree.")

        cold = None
        try:
            cold = seq._allow_cold_extrude(path)
            owner.gcode.run_script_from_command("M83")
            motion.servo_engage()
            enc.set_direction(forward=True)
            enc.reset_distance()
            moved = 0.0
            dead  = 0
            while moved < self._THG_SYNC_MAX + 50.0:
                if owner._toolhead_sensor_active(path):
                    break
                prev = moved
                motion.drive_move(self._THG_STEP, speed=owner.feed_speed)
                owner.gcode.run_script_from_command(
                    "G1 E%.3f F%d"
                    % (self._THG_STEP, int(owner.feed_speed * 60.0)))
                owner.gcode.run_script_from_command("M400")
                owner.reactor.pause(
                    owner.reactor.monotonic() + owner.sensor_delay)
                moved = abs(enc.get_distance())
                if moved - prev < self._THG_STEP * 0.3:
                    dead += 1
                    if dead >= 3:
                        gcmd.respond_info(
                            "SA CAL: No encoder motion on the way back to the "
                            "toolhead sensor — aborted, nothing saved.")
                        self._clear()
                        return
                else:
                    dead = 0
            else:
                gcmd.respond_info(
                    "SA CAL: Toolhead sensor did not trigger on the way back "
                    "— aborted.")
                self._clear()
                return
        finally:
            seq._restore_extrude_floor(cold)

        c2 = abs(enc.get_distance())
        spread = abs(c2 - c)
        owner._cal_data['c2'] = c2
        gcmd.respond_info(
            "SA CAL: Repeat reading %.2fmm against %.2fmm — %.2fmm apart."
            % (c2, c, spread))

        seq._heat_for_load(gcmd, path)
        seq._move_to_purge_position(gcmd, False)

        # The drive is released for the nozzle hunt, so the extruder alone is
        # dragging filament through a Bowden length. Read what actually moved
        # rather than what was asked for: the encoder is fixed on this lane and
        # counts regardless of the drive -- exactly how `a` is measured. Every
        # other distance in this step is encoder-referenced and this one was
        # not, which is the one place extruder slip could inflate a saved
        # number invisibly.
        motion.servo_disengage()
        owner.reactor.pause(owner.reactor.monotonic() + owner.servo_move_delay)
        enc.set_direction(forward=True)
        enc.reset_distance()
        owner._cal_data['b'] = 0.0
        owner._cal_state = 'thg_nozzle_%d' % path
        self._thg_prompt_b(gcmd, path)

    def _thg_prompt_b(self, gcmd, path):
        owner = self.owner
        b = float(owner._cal_data.get('b', 0.0))
        path_i = int(owner._cal_data.get('path', 0))
        meas = abs(owner._encoder(path_i).get_distance())
        self._prompt(
            gcmd,
            "Watch the nozzle. Extrude until filament just appears, then say "
            "so — that distance is the toolhead sensor to the tip.",
            "SA_RESPOND VALUE=coarse",
            "SA_RESPOND VALUE=fine",
            "SA_RESPOND VALUE=seen",
            detail="Encoder %.1fmm (asked for %.1f)." % (meas, b),
            choices=[("+%.0fmm" % self._THG_COARSE, "coarse", "secondary"),
                     ("+%.0fmm" % self._THG_FINE,   "fine",   "secondary"),
                     ("FILAMENT SHOWING", "seen", "primary")])

    def _thg_cooldown(self, gcmd, path):
        """Turn the heater off. This step is the only one that heats and then
        hands control back, so nothing else was going to do it -- it left a
        nozzle at 200C with the guide back on screen."""
        try:
            gcmd.respond_info("SA CAL: Turning off heater...")
            self.owner.gcode.run_script_from_command(
                "SET_HEATER_TEMPERATURE HEATER=%s TARGET=0"
                % self.owner._extruder_names[path])
        except Exception:
            logging.exception("SA CAL: could not turn the heater off")

    def _thg_respond(self, gcmd, state, value):
        owner = self.owner
        seq   = owner.sequences
        path  = int(state.rsplit('_', 1)[-1])
        v     = str(value).strip().lower()
        b     = float(owner._cal_data.get('b', 0.0))

        if v in ('coarse', 'fine'):
            step = self._THG_COARSE if v == 'coarse' else self._THG_FINE
            if b + step > self._THG_NOZZLE_MAX:
                gcmd.respond_info(
                    "SA CAL: %.0fmm extruded with nothing at the tip. That is "
                    "further than any toolhead — stopping rather than pushing "
                    "more into it." % b)
                self._thg_cooldown(gcmd, path)
                self._clear()
                return
            owner.gcode.run_script_from_command("M83")
            seq._extrude_mm(step, seq._extrude_speed_mmm())
            owner.gcode.run_script_from_command("M400")
            owner._cal_data['b'] = b + step
            owner._cal_data['last_step'] = step
            self._thg_prompt_b(gcmd, path)
            return

        if v != 'seen':
            gcmd.respond_info("SA CAL: Press one of the three buttons.")
            return

        if b <= 0.0:
            gcmd.respond_info(
                "SA CAL: Nothing has been extruded yet — nudge it first.")
            self._thg_prompt_b(gcmd, path)
            return

        enc_b = abs(owner._encoder(path).get_distance())
        if enc_b > 0.5:
            if abs(enc_b - b) > max(2.0, b * 0.05):
                gcmd.respond_info(
                    "SA CAL: The extruder was asked for %.1fmm and the encoder "
                    "saw %.1fmm. It is pulling filament through the whole "
                    "Bowden on its own here, so the difference is slip — the "
                    "measured figure is the one being saved." % (b, enc_b))
            b = enc_b
        else:
            gcmd.respond_info(
                "SA CAL: The encoder saw nothing during the nozzle hunt, so "
                "the commanded %.1fmm is being saved instead. Worth a look: "
                "this lane's encoder should count whatever moves." % b)

        # The operator presses until filament SHOWS, so the tip crossed the
        # nozzle somewhere inside the last press -- never at its end. Saving
        # the pressed total biases every reading long by up to a full step;
        # the midpoint is the unbiased estimate of a value known only to lie
        # in (b - step, b]. Mike's own read of it -- "probably 5mm out of the
        # 10mm push" -- is that midpoint exactly.
        last = float(owner._cal_data.get('last_step', 0.0))
        if last > 0.0:
            raw = b
            b = max(0.0, b - last / 2.0)
            gcmd.respond_info(
                "SA CAL: Filament showed somewhere inside the last %.0fmm "
                "press, so %.2fmm is the midpoint of %.2f-%.2f rather than "
                "the end of the push. Finish on +%.0fmm next time and that "
                "uncertainty drops to half a millimetre."
                % (last, b, raw - last, raw, self._THG_FINE))

        c = float(owner._cal_data.get('c', 0.0))
        c2 = float(owner._cal_data.get('c2', 0.0))
        if c2 > 0.0:
            # Both readings are the same span from the same datum, and c2 has
            # come in 1.9mm low on every run measured so far -- two encoder
            # pulses, systematic rather than scatter. Averaging is honest
            # about that; saving whichever happened to be first is not.
            gcmd.respond_info(
                "SA CAL: Two readings of that span, %.2f and %.2f — saving "
                "the mean %.2fmm." % (c, c2, (c + c2) / 2.0))
            c = (c + c2) / 2.0
        a = float(owner._cal_data.get('a', 0.0))
        self._save_variables({
            'sensor_to_toolhead_%d' % path: round(c, 2),
            'toolhead_to_nozzle_%d' % path: round(b, 2),
            'sensor_to_gear_%d'     % path: round(a, 2),
        })
        owner._sensor_to_toolhead[path] = c
        owner._toolhead_to_nozzle[path] = b
        owner._sensor_to_gear[path]     = a

        nozzle_to_sensor = b + c
        gear_to_nozzle   = max(0.0, c - a) + b
        gcmd.respond_info(
            "SA CAL: === TOOLHEAD GEOMETRY — path %d ===\n"
            "  extruder sensor -> gear nip        %.2fmm   MEASURED\n"
            "  extruder sensor -> toolhead sensor %.2fmm   MEASURED\n"
            "  toolhead sensor -> nozzle tip      %.2fmm   estimate (your eye)\n"
            "  nozzle -> extruder sensor          %.2fmm   estimate\n"
            "  gear nip -> nozzle tip             %.2fmm   estimate\n"
            "The first two are sensor edges and repeat to a fraction of a "
            "millimetre. The third is you calling when filament showed, "
            "so everything built on it is an estimate — which is all it "
            "needs to be: it only sizes purges, and a long purge costs a "
            "few millimetres into a bucket. A colour change purges the "
            "%.0fmm gear-to-tip column; same colour uses the profile."
            % (path, a, c, b, nozzle_to_sensor, gear_to_nozzle,
               gear_to_nozzle))

        cfg_ns = owner.nozzle_to_sensor_dist
        if abs(nozzle_to_sensor - cfg_ns) > max(5.0, cfg_ns * 0.15):
            gcmd.respond_info(
                "SA CAL: nozzle_to_sensor_dist in parameters.cfg is %.1fmm "
                "against the measured %.1fmm. The tip former aims past the "
                "extruder sensor using that figure, so until it is updated it "
                "keeps falling short and the fallback retract covers for it."
                % (cfg_ns, nozzle_to_sensor))

        self._thg_cooldown(gcmd, path)

        # Offer to unload before moving on. Measuring six paths with one roll
        # means taking it back out of each head, and without this the operator
        # has to leave the guide to do it.
        owner._cal_data  = {'path': path}
        owner._cal_state = 'thg_unload_%d' % path
        self._prompt(
            gcmd,
            "Measured. Unload this path so the roll can move to the next one?",
            "SA_RESPOND VALUE=unload",
            "SA_RESPOND VALUE=keep",
            detail="The nozzle is already cooling. Unloading now forms a tip "
                   "and parks the filament at the gate.",
            choices=[("UNLOAD IT", "unload", "primary"),
                     ("LEAVE IT LOADED", "keep", "secondary")])

    def _thg_unload_respond(self, gcmd, path, value):
        owner = self.owner
        v = str(value).strip().lower()
        self._clear()
        if v == 'unload':
            gcmd.respond_info("SA CAL: Unloading path %d..." % path)
            try:
                owner.gcode.run_script_from_command("SA_UNLOAD TOOL=%d" % path)
            except Exception:
                logging.exception("SA CAL: unload after step 12 failed")
                gcmd.respond_info(
                    "SA CAL: That unload did not complete — see above. The "
                    "measurement is saved either way.")
            return
        self._offer_next_path(
            gcmd, 'toolhead_geom', path,
            "SA_CALIBRATE_TOOLHEAD TOOL=%d", "MEASURE TOOLHEAD")

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
