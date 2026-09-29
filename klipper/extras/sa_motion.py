# sa_motion.py — Autoloader motion primitives
#
# Handles all low-level hardware movement:
#   - Servo engage/disengage/off
#   - Selector homing, moves, and far-end detection
#   - Drive motor moves
#   - Stepper idle-timeout management
#   - Optional position persistence via save_variables

import sys, os as _os
_extras_dir = _os.path.dirname(_os.path.abspath(__file__))
if _extras_dir not in sys.path:
    sys.path.insert(0, _extras_dir)

import logging

# ══════════════════════════════════════════════════════════════════════════════
# SAMotion
# ══════════════════════════════════════════════════════════════════════════════

class SAMotion:
    """All motion primitives for the Autoloader.

    ``owner`` is the Autoloader instance.  All hardware names and
    motion parameters are read from owner attributes so this class has no
    separate config parsing.
    """

    def __init__(self, owner):
        self.owner = owner
        # stepper_name → reactor timer handle
        self._timeout_handles = {}
        self._sel_full = None   # cached selector run current
        # last known selector position in mm from home
        self._selector_position = 0.0

    # ── internal shorthand ────────────────────────────────────────────────────

    def _owner_sel_name(self):
        """Selector stepper short name (last word of selector_stepper_name)."""
        return self.owner._sel_name()

    def _owner_drv_name(self):
        """Drive stepper short name (last word of drive_stepper_name)."""
        return self.owner._drv_name()

    def _owner_srv_name(self):
        """Servo short name (last word of servo_name)."""
        return self.owner._servo_short_name()

    # ══════════════════════════════════════════════════════════════════════════
    # Servo
    # ══════════════════════════════════════════════════════════════════════════

    def servo_engage(self, force_seat=False):
        """Move servo to engaged angle and jitter drive gear to seat gear teeth.

        PWM stays active while engaged — spring-loaded servo returns to disengaged
        when PWM is cut, so we must keep the signal live to hold the engaged position.
        Call servo_disengage() or servo_off() to release.

        Jitter: ±0.8mm × 3 at 25mm/s, retract-first so final move is always forward.

        The jitter only seats teeth that are not already seated. Called again on
        an already-engaged gear it seats nothing and simply walks the filament
        ±0.8mm — which lands on any datum the operator has set by hand, and on
        any encoder reading taken across it. So an engage that finds the servo
        already engaged does nothing unless *force_seat* says otherwise.
        """
        owner = self.owner
        sn    = self._owner_srv_name()
        dn    = self._owner_drv_name()

        if getattr(owner, '_servo_is_engaged', False) and not force_seat:
            logging.debug("SAMotion: already engaged — not re-seating")
            return

        owner.gcode.run_script_from_command(
            "SET_SERVO SERVO=%s ANGLE=%.1f" % (sn, owner.servo_engaged_angle))
        owner.reactor.pause(owner.reactor.monotonic() + owner.servo_move_delay)

        owner.gcode.run_script_from_command("MANUAL_STEPPER STEPPER=%s ENABLE=1" % dn)
        for _ in range(3):
            owner.gcode.run_script_from_command(
                "MANUAL_STEPPER STEPPER=%s SET_POSITION=0 MOVE=-0.8 SPEED=25" % dn)
            owner.gcode.run_script_from_command(
                "MANUAL_STEPPER STEPPER=%s SET_POSITION=0 MOVE=0.8 SPEED=25" % dn)
        owner.gcode.run_script_from_command("M400")

        # PWM intentionally left active — do NOT cut here.
        owner._servo_is_engaged = True
        logging.debug("SAMotion: servo engaged (%.1f°), PWM active", owner.servo_engaged_angle)

    def servo_disengage(self):
        """Move servo to disengaged angle then cut PWM (spring holds at disengaged)."""
        owner = self.owner
        sn = self._owner_srv_name()
        owner.gcode.run_script_from_command(
            "SET_SERVO SERVO=%s ANGLE=%.1f" % (sn, owner.servo_disengaged_angle))
        owner.reactor.pause(owner.reactor.monotonic() + owner.servo_move_delay)
        owner.gcode.run_script_from_command("SET_SERVO SERVO=%s WIDTH=0" % sn)
        owner._servo_is_engaged = False
        logging.debug("SAMotion: servo disengaged (%.1f°), PWM cut", owner.servo_disengaged_angle)

    def servo_off(self):
        """Immediately cut servo PWM (emergency cutoff, no movement)."""
        owner = self.owner
        sn = self._owner_srv_name()
        owner.gcode.run_script_from_command("SET_SERVO SERVO=%s WIDTH=0" % sn)
        logging.info("SAMotion: servo PWM cut (emergency off)")

    # ══════════════════════════════════════════════════════════════════════════
    # Stepper idle-timeout management
    # ══════════════════════════════════════════════════════════════════════════

    def _arm_timeout(self, stepper_name):
        """Schedule auto-disable for *stepper_name* after owner.stepper_timeout seconds.

        Any previously-armed timer for this stepper is cancelled first so the
        timeout is always measured from the last motion, not the first.
        """
        self._cancel_timeout(stepper_name)
        owner = self.owner
        reactor = owner.reactor
        delay = owner.stepper_timeout

        # Capture stepper_name in closure
        _name = stepper_name

        def _timer_cb(eventtime):
            try:
                owner.gcode.run_script_from_command(
                    "MANUAL_STEPPER STEPPER=%s ENABLE=0" % _name)
                logging.info("SAMotion: auto-disabled stepper '%s' after %.0fs idle",
                             _name, delay)
                if _name == self._owner_drv_name():
                    self.note_drive_speed(0.0)
                # The carriage position was only ever trustworthy because the
                # motor was holding it. Cutting the current ends that, so the
                # home goes with it -- otherwise the next move would be
                # absolute against an origin nothing is defending any more.
                # This is the link that makes skipping the home safe at all.
                if _name == self._owner_sel_name():
                    owner._selector_homed = False
                    owner.gcode.respond_info(
                        "SA: Selector idle %.0fs — motor off, so its position "
                        "is no longer trusted. It will re-home on the next "
                        "move." % delay)
            except Exception as e:
                logging.warning("SAMotion: failed to disable stepper '%s': %s", _name, e)
            # Remove handle from dict
            self._timeout_handles.pop(_name, None)
            return reactor.NEVER

        handle = reactor.register_timer(
            _timer_cb, reactor.monotonic() + delay)
        self._timeout_handles[stepper_name] = handle

    def _cancel_timeout(self, stepper_name):
        """Cancel an existing idle-timeout timer for *stepper_name* if one is armed."""
        handle = self._timeout_handles.pop(stepper_name, None)
        if handle is not None:
            self.owner.reactor.unregister_timer(handle)

    # ══════════════════════════════════════════════════════════════════════════
    # Selector motor
    # ══════════════════════════════════════════════════════════════════════════

    def _sel_sign(self):
        """+1, or -1 when the selector is wired backwards.

        Applied to EVERY selector move, homing included. Homing is the one that
        matters: it drives toward the endstop, so a reversed motor sends the
        carriage away from the switch and into the far stop instead. A sign
        flip fixes all four moves consistently.
        """
        return -1.0 if getattr(self.owner, 'selector_dir_invert', False) else 1.0

    def _drv_sign(self):
        """+1, or -1 when the drive motor is wired backwards."""
        return -1.0 if getattr(self.owner, 'drive_dir_invert', False) else 1.0

    def _endstop_state(self):
        """(triggered, name) for the selector endstop, or (None, name).

        None means it could not be read at all, which is treated as unknown
        rather than as either answer: refusing to home because a query failed
        would be worse than homing, and claiming success on it would be worse
        still.
        """
        try:
            return self.owner._selector_endstop_state()
        except Exception:
            logging.exception("SAMotion: could not read the selector endstop")
            return None, ""

    def selector_home(self):
        """Home selector to physical endstop — double-touch for accuracy.

        Switch (SA_SELECTOR_STOP / PA15) triggers at path 0.
        Fast approach → SET_POSITION=0 → back off → slow re-approach → SET_POSITION=0.
        """
        owner = self.owner
        sn    = self._owner_sel_name()
        hs    = owner.selector_homing_speed
        bo    = owner.selector_homing_backoff
        mt    = owner.selector_max_travel

        self.servo_disengage()
        self._cancel_timeout(sn)

        owner.gcode.run_script_from_command("MANUAL_STEPPER STEPPER=%s ENABLE=1" % sn)
        owner.gcode.run_script_from_command("MANUAL_STEPPER STEPPER=%s SET_POSITION=0" % sn)

        # An endstop that is ALREADY triggered is the failure Klipper cannot
        # catch for us: STOP_ON_ENDSTOP stops the first move instantly, the
        # move "succeeded", and zero gets set wherever the carriage was
        # standing. Back off far enough to clear the switch and look again.
        pre, _n = self._endstop_state()
        if pre:
            logging.info("SAMotion: endstop already triggered — backing off "
                         "before homing")
            owner.gcode.run_script_from_command(
                "MANUAL_STEPPER STEPPER=%s MOVE=%.1f SPEED=%.1f"
                % (sn, self._sel_sign() * (bo * 4.0), hs))
            owner.gcode.run_script_from_command("M400")
            still, _n = self._endstop_state()
            if still:
                raise owner.printer.command_error(
                    "SA: the selector endstop still reads TRIGGERED after "
                    "backing off %.1fmm, so homing cannot tell where home is.\n"
                    "Run SA_TEST_ENDSTOP: either the switch is stuck, or its "
                    "polarity is inverted in hardware.cfg." % (bo * 4.0))

        # Fast approach
        sg = self._sel_sign()
        owner.gcode.run_script_from_command(
            "MANUAL_STEPPER STEPPER=%s MOVE=%.1f SPEED=%.1f STOP_ON_ENDSTOP=1"
            % (sn, sg * -(mt + 20.0), hs))
        owner.gcode.run_script_from_command("M400")
        owner.gcode.run_script_from_command(
            "MANUAL_STEPPER STEPPER=%s SET_POSITION=0" % sn)

        # Back off
        owner.gcode.run_script_from_command(
            "MANUAL_STEPPER STEPPER=%s MOVE=%.1f SPEED=%.1f" % (sn, sg * bo, hs))
        owner.gcode.run_script_from_command("M400")

        # Slow re-approach
        owner.gcode.run_script_from_command(
            "MANUAL_STEPPER STEPPER=%s MOVE=%.1f SPEED=%.1f STOP_ON_ENDSTOP=1"
            % (sn, sg * -(bo * 4.0), hs / 4.0))
        owner.gcode.run_script_from_command("M400")
        owner.gcode.run_script_from_command(
            "MANUAL_STEPPER STEPPER=%s SET_POSITION=0" % sn)

        self._arm_timeout(sn)

        # And prove it. Everything downstream is measured from this zero, so a
        # homing that did not reach the switch must not be recorded as one that
        # did -- the guide reads this flag, and so does every selector move.
        post, _n = self._endstop_state()
        if post is False:
            owner._selector_homed = False
            owner.current_path = -1
            raise owner.printer.command_error(
                "SA: homing finished but the selector endstop does not read "
                "TRIGGERED, so this is not home.\n"
                "The carriage may be jammed short of the switch. Clear it, "
                "then run SA_TEST_ENDSTOP before homing again.")

        owner.current_path = -1
        owner._selector_homed = True
        self._selector_position = 0.0
        logging.info("SAMotion: selector homed%s",
                     "" if post else " (endstop not readable — unverified)")
        self.save_position()

    # Fraction of the configured run current the selector holds at between
    # moves. It only has to resist being nudged -- nothing pushes on the
    # carriage while it sits -- and holding at full current is what makes the
    # driver and the motor hot enough to be worth avoiding.
    SELECTOR_HOLD_FRACTION = 0.5

    def _sel_run_current(self):
        """The selector's configured run current, or None if unreadable."""
        try:
            tmc = self.owner.printer.lookup_object(
                'tmc5160 manual_stepper %s' % self._owner_sel_name(), None)
            if tmc is None:
                return None
            return float(tmc.get_status(
                self.owner.reactor.monotonic())['run_current'])
        except Exception:
            return None

    def _sel_set_current(self, amps):
        try:
            self.owner.gcode.run_script_from_command(
                "SET_TMC_CURRENT STEPPER=%s CURRENT=%.3f"
                % (self._owner_sel_name(), amps))
            return True
        except Exception:
            logging.exception("SAMotion: could not set selector current")
            return False

    def selector_full_current(self):
        """Back to full current. Called before anything that moves."""
        if self._sel_full is not None:
            self._sel_set_current(self._sel_full)

    def selector_hold_current(self):
        """Drop to the holding current, staying ENERGISED.

        Energised is the point. The carriage position is only trustworthy
        while the motor has held it continuously since the last home -- the
        moment it is de-energised the position becomes a guess about whether
        anything nudged it. Holding at half current keeps the position real
        without cooking the driver, which is what lets the selector stop
        re-homing before every single move.
        """
        if self._sel_full is None:
            self._sel_full = self._sel_run_current()
        if self._sel_full is None:
            return
        self._sel_set_current(self._sel_full * self.SELECTOR_HOLD_FRACTION)

    def selector_move_to(self, position_mm):
        """Move selector carriage to *position_mm* (absolute, mm from home).

        Cancels any pending idle timer, enables stepper, moves, then re-arms
        the idle timer.
        """
        owner = self.owner
        sn = self._owner_sel_name()

        self._cancel_timeout(sn)
        owner.gcode.run_script_from_command("MANUAL_STEPPER STEPPER=%s ENABLE=1" % sn)
        if self._sel_full is None:
            self._sel_full = self._sel_run_current()
        self.selector_full_current()
        owner.gcode.run_script_from_command(
            "MANUAL_STEPPER STEPPER=%s MOVE=%.3f SPEED=%.1f"
            % (sn, self._sel_sign() * position_mm, owner.selector_speed))
        owner.gcode.run_script_from_command("M400")
        self.selector_hold_current()
        self._arm_timeout(sn)
        self._selector_position = position_mm
        logging.debug("SAMotion: selector moved to %.3fmm", position_mm)

    # ══════════════════════════════════════════════════════════════════════════
    # Drive motor
    # ══════════════════════════════════════════════════════════════════════════

    def drive_move(self, distance_mm, speed=None):
        """Move the drive stepper by *distance_mm* at *speed* (mm/s).

        Positive = feed (toward extruder).  Negative = retract.
        Cancels pending idle timer, enables, moves, re-arms timer.
        """
        owner = self.owner
        if speed is None:
            speed = owner.feed_speed
        dn = self._owner_drv_name()

        self._cancel_timeout(dn)
        self.note_drive_speed(speed)
        owner.gcode.run_script_from_command("MANUAL_STEPPER STEPPER=%s ENABLE=1" % dn)
        owner.gcode.run_script_from_command("MANUAL_STEPPER STEPPER=%s SET_POSITION=0" % dn)
        owner.gcode.run_script_from_command(
            "MANUAL_STEPPER STEPPER=%s MOVE=%.3f SPEED=%.1f"
            % (dn, self._drv_sign() * distance_mm, speed))
        owner.gcode.run_script_from_command("M400")
        self._arm_timeout(dn)

    def note_drive_speed(self, speed):
        """Record the speed the drive is being commanded at, for the UIs.

        The status screen used to show `feed_speed` -- a config value that is
        the same number whatever the machine is doing, which tells an operator
        nothing about the operation in front of them. Mike: "the drive speed
        should update based on what the process is calling for, not just a
        static title".

        Set here rather than inferred, because the speed is decided by the
        caller: a blast runs at encoder_max_speed, a creep at feed_speed, a
        sync feed at whatever the melt can take. The one thing they share is
        that they all pass a number to the stepper, so that is what is
        recorded. Cleared when the motor stops holding.
        """
        try:
            self.owner.drive_speed = float(speed or 0.0)
        except (TypeError, ValueError):
            self.owner.drive_speed = 0.0

    def drive_disable(self):
        """Immediately disable drive stepper (no timeout delay)."""
        owner = self.owner
        dn = self._owner_drv_name()
        self.note_drive_speed(0.0)
        self._cancel_timeout(dn)
        owner.gcode.run_script_from_command("MANUAL_STEPPER STEPPER=%s ENABLE=0" % dn)
        logging.info("SAMotion: drive stepper disabled")

    # ══════════════════════════════════════════════════════════════════════════
    # Position persistence via save_variables
    # ══════════════════════════════════════════════════════════════════════════

    def save_position(self):
        """Persist selector position and current_path to save_variables if available."""
        owner = self.owner
        sv = owner.printer.lookup_object('save_variables', None)
        if sv is None:
            return
        try:
            # One rewrite, not two. Same reason as SA_SET_MATERIAL: every
            # SAVE_VARIABLE rewrites the whole file synchronously, and this
            # runs after every park.
            owner._persist_variables({
                'sa_selector_pos': round(float(self._selector_position), 3),
                'sa_current_path': int(owner.current_path),
            })
            logging.debug("SAMotion: position saved (sel=%.3f path=%d)",
                          self._selector_position, owner.current_path)
        except Exception as e:
            logging.warning("SAMotion: could not save position: %s", e)

    def load_position(self):
        """Load persisted selector position and current_path.

        Returns (selector_pos_mm, current_path).
        Falls back to (0.0, -1) if save_variables unavailable or key absent.
        """
        owner = self.owner
        sv = owner.printer.lookup_object('save_variables', None)
        if sv is None:
            return 0.0, -1
        try:
            pos  = float(sv.allVariables.get('sa_selector_pos', 0.0))
            path = int(sv.allVariables.get('sa_current_path', -1))
            return pos, path
        except Exception as e:
            logging.warning("SAMotion: could not load saved position: %s", e)
            return 0.0, -1

    # ══════════════════════════════════════════════════════════════════════════
    # Startup
    # ══════════════════════════════════════════════════════════════════════════

    def on_ready(self):
        """Called from Autoloader._on_ready via reactor callback.

        - Unconditionally disengages the servo (safe boot state).
        - Attempts to restore last-known selector position from save_variables.
        - Logs the result.
        """
        owner = self.owner
        try:
            self.servo_disengage()
            logging.info("SAMotion: servo disengaged at startup")
        except Exception as e:
            logging.warning("SAMotion: servo init failed: %s", e)

        pos, path = self.load_position()
        if pos != 0.0 or path != -1:
            self._selector_position = pos
            owner.current_path = path
            # NOT homed. This is where the machine last believed the carriage
            # was, which is a guess that nothing moved while the power was off
            # -- a hand, a jam, a belt slipping off. Klipper makes every axis
            # re-home after a restart for the same reason, and this one
            # positions to gates half a millimetre wide.
            #
            # Saying "homed" here is how the guide came to report it after a
            # restart in which no homing had happened at all.
            owner._selector_homed = False
            owner._selector_position_restored = True
            logging.info("SAMotion: restored selector position=%.3fmm path=%d "
                         "from save_variables — NOT homed until the endstop "
                         "confirms it", pos, path)
        else:
            logging.info("SAMotion: no saved position found — selector position unknown")
