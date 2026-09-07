# sa_sequences.py — Autoloader load/unload sequences
#
# High-level filament feed sequences that orchestrate motion primitives
# from sa_motion.py and sensor reads from autoloader.py.

import sys, os as _os
_extras_dir = _os.path.dirname(_os.path.abspath(__file__))
if _extras_dir not in sys.path:
    sys.path.insert(0, _extras_dir)

import logging
import math

# filament cross-section for 1.75mm diameter
_FILAMENT_AREA = math.pi * (1.75 / 2.0) ** 2   # ~2.405 mm²

# ══════════════════════════════════════════════════════════════════════════════
# SASequences
# ══════════════════════════════════════════════════════════════════════════════

class SASequences:
    """Load and unload sequences for the Autoloader."""

    def __init__(self, owner):
        self.owner = owner

    # ═══════════════════════════════════════════════════════════════════════════
    # Internal helpers
    # ═══════════════════════════════════════════════════════════════════════════

    def _is_homed(self):
        """True if X Y Z are all homed."""
        try:
            th = self.owner.printer.lookup_object('toolhead')
            homed = th.get_kinematics().get_status(
                self.owner.reactor.monotonic()).get('homed_axes', '')
            return ('x' in homed and 'y' in homed and 'z' in homed)
        except Exception:
            return False

    def _is_printing(self):
        """True if PRINT_START.printing variable is set."""
        try:
            ps = self.owner.printer.lookup_object('gcode_macro PRINT_START')
            return bool(ps.variables.get('printing', False))
        except Exception:
            return False

    def _current_tool(self):
        """Active toolchanger tool number, or -1."""
        try:
            tc = self.owner.printer.lookup_object('toolchanger')
            return int(tc.get_status(self.owner.reactor.monotonic()).get('tool_number', -1))
        except Exception:
            return -1

    def _z_safe(self):
        """Current Z + 2mm, capped at axis maximum."""
        try:
            th  = self.owner.printer.lookup_object('toolhead')
            pos = th.get_position()
            kin = th.get_kinematics().get_status(self.owner.reactor.monotonic())
            max_z = kin.get('axis_maximum', [0, 0, 300])[2]
            return min(pos[2] + 2.0, max_z)
        except Exception:
            return 50.0

    def _extruder_temp(self, path):
        """Current temperature of the extruder for *path*, or 0 on error."""
        extruder_name = self.owner._extruder_names[path]
        try:
            ext_obj = self.owner.printer.lookup_object(extruder_name)
            return ext_obj.get_status(self.owner.reactor.monotonic())['temperature']
        except Exception:
            return 0.0

    def _park(self, gcmd, is_printing):
        """Park active toolhead out of the way for drive work.

        No-print: raise to load_park_z then park on cooling pad.
                  Purge position (load_park_x/y) is applied AFTER heating.
        Mid-print: raise to z_safe, move to safe side position.
        """
        owner = self.owner
        if is_printing:
            z = self._z_safe()
            gcmd.respond_info(
                "SA: Mid-print park X%.1f Y%.1f Z%.1f..."
                % (owner.load_print_park_x, owner.load_print_park_y, z))
            owner.gcode.run_script_from_command("G0 Z%.3f F600" % z)
            owner.gcode.run_script_from_command(
                "G0 X%.3f Y%.3f F5000"
                % (owner.load_print_park_x, owner.load_print_park_y))
        else:
            gcmd.respond_info("SA: Raising Z to %.1f and parking on cooling pad..." % owner.load_park_z)
            owner.gcode.run_script_from_command("G0 Z%.3f F600" % owner.load_park_z)
            owner.gcode.run_script_from_command("PARK_ON_COOLING_PAD")
        owner.gcode.run_script_from_command("M400")

    def _move_to_purge_position(self, gcmd, is_printing):
        """After heating, move toolhead to the purge/extrude position."""
        owner = self.owner
        if not is_printing:
            gcmd.respond_info(
                "SA: Moving to purge position X%.1f Y%.1f..."
                % (owner.load_park_x, owner.load_park_y))
            owner.gcode.run_script_from_command(
                "G0 X%.3f Y%.3f F5000" % (owner.load_park_x, owner.load_park_y))
            owner.gcode.run_script_from_command("M400")

    def _switch_tool(self, gcmd, path):
        """Switch to toolhead *path* if not already active."""
        if self._current_tool() != path:
            gcmd.respond_info("SA: Switching to toolhead T%d..." % path)
            self.owner.gcode.run_script_from_command("T%d" % path)
            self.owner.gcode.run_script_from_command("M400")

    def _ensure_selector(self, gcmd, path):
        """Always home selector before moving to *path* — guarantees accurate position."""
        owner = self.owner
        motion = owner.motion
        gcmd.respond_info("SA: Homing selector...")
        motion.selector_home()
        motion.servo_disengage()
        motion.selector_move_to(owner._selector_positions[path])
        owner.current_path = path

    def _extrude_speed_mmm(self):
        """Volumetric-flow-limited extrusion speed in mm/min."""
        return int((self.owner.max_volumetric_flow / _FILAMENT_AREA) * 60)

    def _heat_for_load(self, gcmd, path):
        """Heat extruder to load_temperature and wait."""
        owner = self.owner
        extruder_name = owner._extruder_names[path]
        gcmd.respond_info("SA: Heating %s to %.0f°C..." % (extruder_name, owner.load_temperature))
        owner.gcode.run_script_from_command(
            "SET_TOOL_TEMPERATURE T=%d TARGET=%.0f WAIT=1" % (path, owner.load_temperature))

    def _restore_state(self, gcmd, path, is_printing, after_unload=False):
        """After load/unload: resume print or clean + park + heater off.

        after_unload=True  — nozzle is empty and cold; skip clean+cooling-pad,
                             just park at the load position and switch T0.
        after_unload=False — nozzle is hot+primed; clean then park on cooling pad.
        """
        owner = self.owner
        if is_printing:
            gcmd.respond_info("SA: Resuming print...")
            owner.gcode.run_script_from_command("RESUME")
        else:
            # Re-assert load height — macros below must not lower Z
            owner.gcode.run_script_from_command(
                "G0 Z%.3f F600" % owner.load_park_z)
            owner.gcode.run_script_from_command("M400")
            gcmd.respond_info("SA: Turning off heater...")
            owner.gcode.run_script_from_command(
                "SET_HEATER_TEMPERATURE HEATER=%s TARGET=0"
                % owner._extruder_names[path])
            if after_unload:
                # Nozzle is empty — park on cooling pad if enabled, else load position
                if owner.cooling_pad_enabled:
                    gcmd.respond_info("SA: Parking on cooling pad...")
                    owner.gcode.run_script_from_command("PARK_ON_COOLING_PAD")
                else:
                    gcmd.respond_info("SA: Parking at load position...")
                    owner.gcode.run_script_from_command(
                        "G0 X%.3f Y%.3f F5000"
                        % (owner.load_park_x, owner.load_park_y))
                    owner.gcode.run_script_from_command("M400")
            else:
                # Nozzle is hot+primed — wipe then cool
                if owner.clean_nozzle_enabled:
                    gcmd.respond_info("SA: Cleaning nozzle...")
                    try:
                        owner.gcode.run_script_from_command("SA_CLEAN_NOZZLE")
                    except Exception as e:
                        gcmd.respond_info(
                            "SA: WARNING — SA_CLEAN_NOZZLE failed (%s). "
                            "Define it in macros.cfg." % str(e))
                if owner.cooling_pad_enabled:
                    gcmd.respond_info("SA: Parking on cooling pad...")
                    owner.gcode.run_script_from_command("PARK_ON_COOLING_PAD")
            owner.gcode.run_script_from_command("T0")

    # ═══════════════════════════════════════════════════════════════════════════
    # Wiggle checks
    # ═══════════════════════════════════════════════════════════════════════════

    def _wiggle_check_encoder(self, gcmd, path):
        """Retract *wiggle_distance* mm and check encoder for motion.

        Returns True if filament is confirmed real; False if no encoder motion
        (possible broken piece or jam).
        Servo must already be engaged before calling this.
        """
        owner = self.owner
        motion = owner.motion
        enc = owner._encoder(path)
        retract = owner.wiggle_distance

        gcmd.respond_info("SA: Wiggle check — retracting %.1fmm on path %d..." % (retract, path))
        enc.set_direction(forward=False)
        enc.reset_distance()
        motion.drive_move(-retract, speed=25.0)
        owner.reactor.pause(owner.reactor.monotonic() + 0.3)
        distance = abs(enc.get_distance())
        gcmd.respond_info("SA: Wiggle encoder: %.2fmm motion detected." % distance)

        # Push back to restore position
        enc.set_direction(forward=True)
        motion.drive_move(retract, speed=25.0)
        owner.reactor.pause(owner.reactor.monotonic() + 0.15)

        if distance < 0.5:
            gcmd.respond_info(
                "SA: WARNING — no encoder motion on path %d. "
                "Filament may be broken or missing in tube." % path)
            return False
        return True

    def _wiggle_check_toolhead(self, gcmd, path, retract_mm=5.0):
        """Verify toolhead sensor by small extruder retract + re-feed.

        Extruder must be at temperature before calling.
        Returns True if sensor responds correctly (or is plausibly real).
        """
        owner = self.owner
        gcmd.respond_info(
            "SA: Wiggle check toolhead sensor path %d (%.1fmm retract)..."
            % (path, retract_mm))

        owner.gcode.run_script_from_command("M83")
        owner.gcode.run_script_from_command("G1 E-%.2f F300" % retract_mm)
        owner.gcode.run_script_from_command("M400")
        owner.reactor.pause(owner.reactor.monotonic() + 0.2)

        still_triggered = owner._toolhead_sensor_active(path)

        # Push back
        owner.gcode.run_script_from_command("G1 E%.2f F300" % retract_mm)
        owner.gcode.run_script_from_command("M400")
        owner.reactor.pause(owner.reactor.monotonic() + 0.2)

        if still_triggered:
            gcmd.respond_info(
                "SA: WARNING — toolhead sensor path %d still active after %.1fmm retract. "
                "Possible jam near sensor — proceeding." % (path, retract_mm))
            return True

        re_triggered = owner._toolhead_sensor_active(path)
        if re_triggered:
            gcmd.respond_info("SA: Toolhead sensor confirmed on path %d." % path)
            return True

        gcmd.respond_info(
            "SA: WARNING — toolhead sensor path %d did not retrigger after push-back. "
            "Filament may be short or sensor fault." % path)
        return False

    # ═══════════════════════════════════════════════════════════════════════════
    # Park filament
    # ═══════════════════════════════════════════════════════════════════════════

    def _park_filament_at_encoder(self, gcmd, path, from_load=True):
        """Park filament tip at a consistent position just before the encoder.

        Two paths because the call sites have different starting conditions:

        from_load=True (default — fresh-insert / load Branch C):
            Filament is barely inserted at the entry sensor; we don't yet know
            if the drive gear has gripped it. Original 4-step logic
            (feed-forward → retract-quiet → Pass 1 find → back-off → Pass 2 find
            → final retract) is well-tested for this case and handles
            barely-gripped filament gracefully. DO NOT change this path
            without testing all load + auto-insert flows.

        from_load=False (unload):
            Filament tip is somewhere inside the bowden after a long blast
            retract; servo is engaged with confirmed grip. Use the 3-phase
            algorithm (debounced retract-while-motion → feed-find →
            calibrated park retract). Removed the early-return on Phase 2
            failure: even if the find phase doesn't see the encoder, still
            do the calibrated park retract so the function never leaves the
            filament in an unknown position.

        Servo must already be engaged before calling this.
        """
        owner  = self.owner
        motion = owner.motion
        enc    = owner._encoder(path)
        mpp    = enc.mm_per_pulse or 1.5

        gcmd.respond_info("SA: Parking filament at encoder — path %d..." % path)

        if from_load:
            # ── Load-path park (6 steps; see PARKING SEQUENCE in parameters.cfg) ─

            # Step 1 — feed forward to engage drive gear and push past encoder.
            enc.set_direction(forward=True)
            enc.reset_distance()
            motion.drive_move(
                owner.encoder_to_gear_distance + owner.park_load_initial_extra,
                speed=owner.park_load_initial_speed)
            owner.reactor.pause(owner.reactor.monotonic() + 0.3)

            # Step 2 — retract until encoder is quiet (filament cleared).
            # One pulse = mm_per_pulse; less than that in a chunk = wheel
            # didn't rotate = filament no longer in encoder contact.
            enc.set_direction(forward=False)
            max_chunks = int(owner.park_load_retract_max / owner.park_load_retract_chunk)
            for _ in range(max_chunks):
                enc.reset_distance()
                motion.drive_move(-owner.park_load_retract_chunk,
                                  speed=owner.park_load_retract_speed)
                owner.reactor.pause(
                    owner.reactor.monotonic() + owner.park_load_retract_pause)
                if abs(enc.get_distance()) < mpp:
                    break

            # Step 3 — Pass 1: feed forward until encoder detects.
            # Cumulative distance (no per-chunk reset) so sub-pulse motion
            # across iterations still trips the threshold.
            enc.set_direction(forward=True)
            enc.reset_distance()
            max_chunks = int(owner.park_load_find_max / owner.park_load_find_chunk)
            found = False
            for _ in range(max_chunks):
                motion.drive_move(owner.park_load_find_chunk,
                                  speed=owner.park_load_find_speed)
                owner.reactor.pause(
                    owner.reactor.monotonic() + owner.park_load_find_pause)
                if abs(enc.get_distance()) >= mpp:
                    found = True
                    break
            if not found:
                gcmd.respond_info(
                    "SA: WARNING — Pass 1 fed %.0fmm without encoder detection "
                    "on path %d." % (owner.park_load_find_max, path))

            # Step 4 — back off so Pass 2 has room to re-detect.
            motion.drive_move(
                -(owner.park_offset + owner.park_load_backoff_extra),
                speed=owner.park_offset_speed)
            owner.reactor.pause(owner.reactor.monotonic() + 0.2)

            # Step 5 — Pass 2: same logic as Pass 1, confirm position.
            enc.set_direction(forward=True)
            enc.reset_distance()
            found = False
            for _ in range(max_chunks):
                motion.drive_move(owner.park_load_find_chunk,
                                  speed=owner.park_load_find_speed)
                owner.reactor.pause(
                    owner.reactor.monotonic() + owner.park_load_find_pause)
                if abs(enc.get_distance()) >= mpp:
                    found = True
                    break
            # Step 6 — retract to park_offset. Runs either way: leaving the
            # filament wherever the failed search left it is worse than backing
            # it off to a known offset.
            motion.drive_move(-owner.park_offset, speed=owner.park_offset_speed)
            owner.reactor.pause(owner.reactor.monotonic() + 0.2)

            if not found:
                # Do NOT claim success. This used to print "Filament parked"
                # straight after admitting the encoder never saw the filament,
                # so a park that fed 100mm into thin air reported exactly the
                # same line as one that worked -- which is why it went
                # unnoticed until someone checked the encoder by hand.
                gcmd.respond_info(
                    ("SA: PARK FAILED on path %d — fed %.0fmm twice and the "
                     "encoder never moved, so the filament was never gripped."
                     % (path, owner.park_load_find_max)))
                gcmd.respond_info(
                    "SA: The path is NOT parked. Usual causes: filament not "
                    "pushed in far enough to reach the drive gear, the drive "
                    "gear not gripping, or a dead encoder on this channel.")
                gcmd.respond_info(
                    "SA: Push the filament in until it stops, then run: "
                    "SA_PARK TOOL=%d" % path)
                return False

            gcmd.respond_info(
                "SA: Filament parked %.1fmm before encoder (path %d)."
                % (owner.park_offset, path))
            return True

        # ── Unload-path park (3 phases; see PARKING SEQUENCE in parameters.cfg) ─

        # Phase 1 — retract while encoder shows motion (debounced).
        # Break only after park_unload_quiet_iters consecutive sub-pulse
        # chunks; a single dropped pulse can't end the retract early.
        enc.set_direction(forward=False)
        max_chunks = int(owner.park_unload_max / owner.park_unload_chunk)
        quiet_iters  = 0
        retracted_mm = 0.0
        for _ in range(max_chunks):
            enc.reset_distance()
            motion.drive_move(-owner.park_unload_chunk,
                              speed=owner.park_unload_speed)
            owner.reactor.pause(
                owner.reactor.monotonic() + owner.park_unload_pause)
            retracted_mm += owner.park_unload_chunk
            if abs(enc.get_distance()) < mpp:
                quiet_iters += 1
                if quiet_iters >= owner.park_unload_quiet_iters:
                    gcmd.respond_info(
                        "SA: Encoder quiet %d× after %.0fmm retract — "
                        "filament cleared (path %d)."
                        % (owner.park_unload_quiet_iters, retracted_mm, path))
                    break
            else:
                quiet_iters = 0
        else:
            gcmd.respond_info(
                "SA: WARNING — retract limit (%.0fmm) reached on path %d "
                "without encoder going quiet." % (owner.park_unload_max, path))

        # Phase 2 — feed forward to re-find tip. If not found, still proceed
        # to Phase 3 so filament always ends at a defined offset.
        enc.set_direction(forward=True)
        max_chunks = int(owner.park_unload_find_max / owner.park_unload_find_chunk)
        found   = False
        feed_mm = 0.0
        for _ in range(max_chunks):
            enc.reset_distance()
            motion.drive_move(owner.park_unload_find_chunk,
                              speed=owner.park_unload_find_speed)
            owner.reactor.pause(
                owner.reactor.monotonic() + owner.park_unload_find_pause)
            feed_mm += owner.park_unload_find_chunk
            if enc.get_distance() >= mpp:
                found = True
                break
        if found:
            gcmd.respond_info(
                "SA: Encoder re-acquired filament after %.1fmm feed (path %d)."
                % (feed_mm, path))
        else:
            gcmd.respond_info(
                "SA: WARNING — fed %.0fmm forward without encoder triggering "
                "on path %d. Continuing with park anyway." % (feed_mm, path))

        # Phase 3 — final retract to park_offset (always runs).
        motion.drive_move(-owner.park_offset, speed=owner.park_offset_speed)
        owner.reactor.pause(owner.reactor.monotonic() + 0.2)

        gcmd.respond_info(
            "SA: Filament parked %.1fmm before encoder (path %d)."
            % (owner.park_offset, path))
        # The unload park always retracts to a known offset, so it is a real
        # park either way -- but report whether the encoder actually confirmed
        # the filament, so the caller is not told "parked" on faith alone.
        return found

    def park_filament(self, gcmd, path):
        """Public: park filament on *path* — selects path, parks, disengages.

        Called by SA_PARK and the state monitor's auto-park queue.
        """
        self.owner._op_paths.add(path)
        try:
            return self._park_filament_inner(gcmd, path)
        finally:
            self.owner._op_paths.discard(path)

    def _park_filament_inner(self, gcmd, path):
        owner = self.owner
        motion = owner.motion

        if not owner._entry_sensor_active(path):
            gcmd.respond_info(
                "SA: No filament at entry of path %d — nothing to park." % path)
            return

        self._ensure_selector(gcmd, path)
        motion.servo_engage()
        ok = self._park_filament_at_encoder(gcmd, path)
        motion.servo_disengage()
        motion.save_position()

        # Only claim the path is parked if it is. This used to set 'partial'
        # and print "Filament parked" unconditionally, so a park that never
        # gripped the filament still wrote a state a later SA_LOAD would act
        # on -- the machine believing filament sat at the drive gear while it
        # was still at the entry sensor.
        if not ok:
            return False

        owner.path_states[path] = 'partial'
        gcmd.respond_info(
            "SA: Filament parked on path %d. "
            "Run SA_LOAD TOOL=%d to load." % (path, path))
        return True

    # ═══════════════════════════════════════════════════════════════════════════
    # Drive phases (shared helpers to avoid duplication)
    # ═══════════════════════════════════════════════════════════════════════════

    def _retract_to_clear(self, gcmd, path):
        """Retract-to-clear encoder: 5mm steps until encoder goes quiet."""
        owner = self.owner
        motion = owner.motion
        enc = owner._encoder(path)
        gcmd.respond_info("SA: Clearing encoder for consistent start...")
        enc.set_direction(forward=False)
        for _ in range(20):
            enc.reset_distance()
            motion.drive_move(-5.0, speed=25.0)
            owner.reactor.pause(owner.reactor.monotonic() + 0.15)
            if abs(enc.get_distance()) < 0.5:
                break

    def _engage_check(self, gcmd, path):
        """Feed until encoder confirms grip. Returns False if grip not achieved."""
        owner = self.owner
        motion = owner.motion
        enc = owner._encoder(path)
        gcmd.respond_info("SA: Confirming grip on filament...")
        enc.set_direction(forward=True)
        enc.reset_distance()
        driven    = 0.0
        mpp       = enc.mm_per_pulse
        threshold = (mpp * 3.0) if mpp else 1.5

        while enc.get_distance() < threshold and driven < owner.engage_max_distance:
            motion.drive_move(owner.feed_step_size)
            driven += owner.feed_step_size
            owner.reactor.pause(owner.reactor.monotonic() + owner.sensor_delay)

        if enc.get_distance() < threshold:
            motion.servo_disengage()
            gcmd.respond_info(
                "SA: ERROR — encoder %d not responding after %.0fmm. "
                "Check filament position and encoder wiring." % (path, driven))
            return False

        gcmd.respond_info("SA: Grip confirmed (%.2fmm)." % enc.get_distance())
        return True

    def _blast_and_approach(self, gcmd, path):
        """Blast 98% + sensor-polling approach. Returns False on sensor miss."""
        owner = self.owner
        motion = owner.motion
        enc = owner._encoder(path)

        sv = owner.printer.lookup_object('save_variables', None)
        saved_max   = float(sv.allVariables.get('encoder_max_speed', 0)) if sv else 0
        blast_speed = (saved_max * 0.75) if saved_max > 0 else 75.0
        target      = owner._bowden_lengths[path]

        remaining = (target * 0.98) - enc.get_distance()
        if remaining > 0:
            gcmd.respond_info("SA: Blasting %.1fmm at %.0fmm/s..." % (remaining, blast_speed))
            motion.drive_move(remaining, speed=blast_speed)

        gcmd.respond_info(
            "SA: Blast complete (enc=%.1fmm). Approaching extruder sensor..."
            % enc.get_distance())

        has_sensor   = bool(owner._extruder_sensor_names[path])
        overshoot    = target * 0.10
        inched       = 0.0
        triggered    = False

        while not triggered and inched < overshoot:
            if has_sensor and owner._extruder_sensor_active(path):
                triggered = True
                break
            if enc.get_distance() >= target and not has_sensor:
                break
            motion.drive_move(owner.feed_step_size)
            inched += owner.feed_step_size
            owner.reactor.pause(owner.reactor.monotonic() + owner.sensor_delay)

        if has_sensor and not triggered:
            motion.servo_disengage()
            gcmd.respond_info(
                "SA: ERROR — extruder sensor path %d not triggered. "
                "Re-run SA_CALIBRATE_BOWDEN TOOL=%d." % (path, path))
            return False

        gcmd.respond_info(
            "SA: Filament at extruder (enc=%.1fmm). Releasing drive gear."
            % enc.get_distance())
        return True

    def _allow_cold_extrude(self, path, floor=0.0):
        """Temporarily lower this extruder's min_extrude_temp.

        Returns a token to hand back to _restore_extrude_floor, or None if the
        heater could not be found.

        The guard exists to stop cold filament being forced into a nozzle. Two
        places here legitimately move filament colder than that: forming a tip,
        which is the whole point of forming below the melt, and dragging an
        already-formed tip back past the gears with the heater off. Neither is
        pushing into a cold nozzle.
        """
        owner = self.owner
        try:
            heater = owner.printer.lookup_object(
                owner._extruder_names[path]).get_heater()
        except Exception:
            return None

        saved = heater.min_extrude_temp
        if floor >= saved:
            return None

        heater.min_extrude_temp = floor
        # can_extrude only refreshes on a temperature callback; set it directly
        # rather than racing the next one.
        heater.can_extrude = (heater.smoothed_temp >= floor)

        return (heater, saved)

    def _restore_extrude_floor(self, token):
        if token is None:
            return
        heater, saved = token
        heater.min_extrude_temp = saved
        heater.can_extrude = (heater.smoothed_temp >= saved)

    def _extrude_mm(self, total_mm, speed_mmm, chunk=49.0):
        """Extrude *total_mm* in ≤49mm chunks to stay under max_extrude_only_distance.

        Handles both positive (extrude) and negative (retract) values.
        """
        owner = self.owner
        remaining = abs(total_mm)
        sign = 1.0 if total_mm >= 0 else -1.0
        while remaining > 0.0:
            move = min(remaining, chunk)
            owner.gcode.run_script_from_command(
                "G1 E%.2f F%d" % (sign * move, speed_mmm))
            remaining -= move
        owner.gcode.run_script_from_command("M400")

    def _fill_and_purge(self, gcmd, path):
        """Fill nozzle + purge at volumetric flow rate. Extruder must be hot."""
        owner = self.owner
        f = self._extrude_speed_mmm()
        gcmd.respond_info(
            "SA: Filling nozzle %.1fmm + purge %.1fmm at %dmm/min..."
            % (owner.fill_nozzle_length, owner.purge_length, f))
        owner.gcode.run_script_from_command("M83")
        self._extrude_mm(owner.fill_nozzle_length, f)
        self._extrude_mm(owner.purge_length, f)

    def _sync_feed_to_toolhead_sensor(self, gcmd, path):
        """Run drive motor and extruder together at feed_speed until toolhead sensor fires.

        Covers the dead zone between extruder sensor and extruder gear engagement
        (~20mm), then continues until filament is confirmed at the toolhead.

        Servo must be engaged before calling.  Disengages servo on return.
        Falls back to fill_nozzle_length fixed extrusion if no toolhead sensor.
        """
        owner  = self.owner
        motion = owner.motion
        dn     = owner._drv_name()

        has_sensor = bool(owner._toolhead_sensor_names[path])
        sync_speed = owner.feed_speed
        sync_f     = int(sync_speed * 60)
        step       = owner.feed_step_size
        # Safety ceiling: 2× fill_nozzle_length or 200mm, whichever is larger
        max_dist   = max(owner.fill_nozzle_length * 2.0, 200.0)

        if not has_sensor:
            gcmd.respond_info(
                "SA: No toolhead sensor — extruding %.1fmm to fill nozzle..."
                % owner.fill_nozzle_length)
            owner.gcode.run_script_from_command("M83")
            self._extrude_mm(owner.fill_nozzle_length, self._extrude_speed_mmm())
            motion.servo_disengage()
            return True

        if owner._toolhead_sensor_active(path):
            gcmd.respond_info("SA: Toolhead sensor already active on path %d." % path)
            motion.servo_disengage()
            return True

        gcmd.respond_info(
            "SA: Sync feed — drive + extruder at %.0fmm/s until toolhead sensor (path %d)..."
            % (sync_speed, path))

        owner.gcode.run_script_from_command("M83")
        motion._cancel_timeout(dn)
        owner.gcode.run_script_from_command("MANUAL_STEPPER STEPPER=%s ENABLE=1" % dn)

        driven    = 0.0
        triggered = False

        while driven < max_dist:
            # SYNC=0 starts drive move immediately without waiting for the extruder queue.
            # G1 E queues right after — both execute in parallel, same distance and speed.
            owner.gcode.run_script_from_command(
                "MANUAL_STEPPER STEPPER=%s SET_POSITION=0 MOVE=%.2f SPEED=%.1f SYNC=0"
                % (dn, step, sync_speed))
            owner.gcode.run_script_from_command(
                "G1 E%.2f F%d" % (step, sync_f))
            owner.gcode.run_script_from_command("M400")
            driven += step
            owner.reactor.pause(owner.reactor.monotonic() + owner.sensor_delay)

            if owner._toolhead_sensor_active(path):
                gcmd.respond_info(
                    "SA: Toolhead sensor triggered after %.1fmm sync feed on path %d."
                    % (driven, path))
                triggered = True
                break

        motion._arm_timeout(dn)
        motion.servo_disengage()

        if not triggered:
            gcmd.respond_info(
                "SA: ERROR — toolhead sensor path %d not triggered after %.0fmm. "
                "Check sensor wiring or re-run SA_CALIBRATE_BOWDEN TOOL=%d. "
                "Aborting load." % (path, max_dist, path))
            return False

        return True

    # ═══════════════════════════════════════════════════════════════════════════
    # Post-load purge prompt (state machine phase)
    # ═══════════════════════════════════════════════════════════════════════════

    def _prompt_purge(self, gcmd, path):
        """Print the post-load purge-more / park prompt."""
        owner = self.owner
        n = owner.num_paths - 1
        gcmd.respond_info(
            "SA: Load complete — path %d. Filament purging at nozzle.\n"
            "\n"
            "  SA_RESPOND VALUE=more      — purge %.0fmm again\n"
            "  SA_RESPOND VALUE=park      — clean nozzle and park on cooling pad\n"
            "  SA_RESPOND VALUE=load:N    — switch to path N and load (0-%d)\n"
            "  SA_RESPOND VALUE=unload:N  — switch to path N and unload (0-%d)\n"
            "  SA_RESPOND VALUE=exit      — disengage servo, heater off, leave toolhead in place"
            % (path, owner.purge_length, n, n))

    def _load_purge_respond(self, gcmd, value):
        """Handle SA_RESPOND during the load_purge state."""
        owner = self.owner
        data  = owner._cal_data
        path        = data['path']
        is_printing = data['is_printing']

        v = value.strip().lower()
        n = owner.num_paths

        def _parse_target(s):
            try:
                t = int(s)
                if 0 <= t < n:
                    return t
                gcmd.respond_info(
                    "SA: Path %d out of range (0-%d)." % (t, n - 1))
            except ValueError:
                gcmd.respond_info("SA: Unknown path '%s'." % s)
            return None

        if v == 'exit':
            owner._cal_state = None
            owner._cal_data  = {}
            owner.motion.servo_disengage()
            owner.gcode.run_script_from_command(
                "SET_HEATER_TEMPERATURE HEATER=%s TARGET=0"
                % owner._extruder_names[path])
            gcmd.respond_info(
                "SA: Exited — servo disengaged, heater off. "
                "Toolhead left in current position.")
            return
        elif v == 'more':
            f      = self._extrude_speed_mmm()
            more_l = 60.0
            gcmd.respond_info("SA: Purging %.0fmm more..." % more_l)
            owner.gcode.run_script_from_command("M83")
            self._extrude_mm(more_l, f)
            self._prompt_purge(gcmd, path)
        elif v.startswith('load:') or v.startswith('unload:'):
            action, _, n_str = v.partition(':')
            target = _parse_target(n_str)
            if target is not None:
                owner._cal_state = None
                owner._cal_data  = {}
                owner.gcode.run_script_from_command(
                    "SET_HEATER_TEMPERATURE HEATER=%s TARGET=0"
                    % owner._extruder_names[path])
                if action == 'load':
                    self.do_load(gcmd, target)
                else:
                    self.do_unload(gcmd, target)
            else:
                self._prompt_purge(gcmd, path)
        else:
            owner._cal_state = None
            owner._cal_data  = {}
            gcmd.respond_info("SA: === LOAD COMPLETE — path %d ===" % path)
            self._restore_state(gcmd, path, is_printing)

    def _prompt_unload_park(self, gcmd, path):
        """Print the post-unload options prompt."""
        owner = self.owner
        n = owner.num_paths - 1
        gcmd.respond_info(
            "SA: Unload complete — path %d. What next?\n"
            "\n"
            "  SA_RESPOND VALUE=park        — clean nozzle and park on cooling pad\n"
            "  SA_RESPOND VALUE=load        — load new filament on path %d (same path)\n"
            "  SA_RESPOND VALUE=load:N      — load filament on path N (0-%d)\n"
            "  SA_RESPOND VALUE=unload:N    — unload filament on path N (0-%d)\n"
            "  SA_RESPOND VALUE=exit        — disengage servo, heater off, leave toolhead in place"
            % (path, path, n, n))

    def _unload_done_respond(self, gcmd, value):
        """Handle SA_RESPOND during the unload_done state."""
        owner = self.owner
        data  = owner._cal_data
        path        = data['path']
        is_printing = data['is_printing']
        owner._cal_state = None
        owner._cal_data  = {}

        v = value.strip().lower()
        n = owner.num_paths

        def _parse_target(s):
            try:
                t = int(s)
                if 0 <= t < n:
                    return t
                gcmd.respond_info(
                    "SA: Path %d out of range (0-%d) — parking instead." % (t, n - 1))
            except ValueError:
                gcmd.respond_info("SA: Unknown response '%s' — parking instead." % s)
            return None

        if v == 'exit':
            owner.motion.servo_disengage()
            owner.gcode.run_script_from_command(
                "SET_HEATER_TEMPERATURE HEATER=%s TARGET=0"
                % owner._extruder_names[path])
            gcmd.respond_info(
                "SA: Exited — servo disengaged, heater off. "
                "Toolhead left in current position.")
            return
        elif v == 'load':
            self.do_load(gcmd, path)
        elif v.startswith('load:'):
            target = _parse_target(v[5:])
            if target is not None:
                self.do_load(gcmd, target)
            else:
                self._restore_state(gcmd, path, is_printing, after_unload=True)
        elif v.startswith('unload:'):
            target = _parse_target(v[7:])
            if target is not None:
                self.do_unload(gcmd, target)
            else:
                self._restore_state(gcmd, path, is_printing, after_unload=True)
        else:
            self._restore_state(gcmd, path, is_printing, after_unload=True)

    # ═══════════════════════════════════════════════════════════════════════════
    # Load sequence
    # ═══════════════════════════════════════════════════════════════════════════

    def do_load(self, gcmd, path):
        """Marks the path in-flight, then runs the load sequence.

        The state monitor must not act on entry-sensor readings for a
        path while it is being driven: mid-sequence the sensor goes
        clear and comes back, and a load can outlast
        material_select_timeout, which would let the monitor wipe the
        very profile the load is using.
        """
        self.owner._op_paths.add(path)
        try:
            return self._do_load_inner(gcmd, path)
        finally:
            self.owner._op_paths.discard(path)

    def do_unload(self, gcmd, path):
        """Marks the path in-flight, then runs the unload sequence.

        Same reasoning as do_load: transient sensor readings during the
        sequence are not runout evidence.
        """
        self.owner._op_paths.add(path)
        try:
            return self._do_unload_inner(gcmd, path)
        finally:
            self.owner._op_paths.discard(path)

    def _do_load_inner(self, gcmd, path):
        """Full filament load sequence for *path*.

        Sensor state determines which phases are skipped:
          entry only            → park at encoder → blast → approach → heat → fill+purge
          entry + extruder      → wiggle verify → retract past extruder → heat → fill+purge
          entry + extruder + th → wiggle toolhead → heat → purge only
          empty / broken        → abort with message
        """
        owner  = self.owner
        motion = owner.motion

        gcmd.respond_info("SA: === LOAD path %d ===" % path)

        # ── Sensor state ──────────────────────────────────────────────────────
        has_entry    = owner._entry_sensor_active(path)
        has_extruder = owner._extruder_sensor_active(path)
        has_toolhead = owner._toolhead_sensor_active(path)

        gcmd.respond_info("SA: Sensors — entry:%s extruder:%s toolhead:%s" % (
            "Y" if has_entry else "N",
            "Y" if has_extruder else "N",
            "Y" if has_toolhead else "N"))

        # Stale partial state: filament was parked but user pulled the roll
        if owner.path_states[path] == 'partial' and not has_entry:
            gcmd.respond_info(
                "SA: Parked filament on path %d was removed (entry sensor inactive). "
                "Setting path to empty." % path)
            owner.path_states[path] = 'empty'
            return

        if not has_entry and not has_extruder and not has_toolhead:
            gcmd.respond_info(
                "SA: No filament on path %d. Insert roll and retry." % path)
            return

        if not has_entry and (has_extruder or has_toolhead):
            gcmd.respond_info(
                "SA: ERROR — extruder/toolhead sensor active without entry on path %d. "
                "Possible broken filament piece in tube." % path)
            return

        # ── Pre-flight ────────────────────────────────────────────────────────
        if not self._is_homed():
            gcmd.respond_info("SA: Printer not homed — running G28...")
            self.owner.gcode.run_script_from_command("G28")
            self.owner.gcode.run_script_from_command("M400")

        is_printing = self._is_printing()
        gcmd.respond_info("SA: Print state: %s." % ("PRINTING" if is_printing else "idle"))
        self._park(gcmd, is_printing)
        self._switch_tool(gcmd, path)
        self._ensure_selector(gcmd, path)

        # ══════════════════════════════════════════════════════════════════════
        # Branch A: ALL 3 SENSORS — filament loaded to nozzle area
        # Skip to heat + purge only
        # ══════════════════════════════════════════════════════════════════════
        if has_entry and has_extruder and has_toolhead:
            gcmd.respond_info(
                "SA: All sensors active — heating and verifying toolhead...")
            self._heat_for_load(gcmd, path)
            self._move_to_purge_position(gcmd, is_printing)
            self._wiggle_check_toolhead(gcmd, path)

            gcmd.respond_info("SA: Purging %.1fmm..." % owner.purge_length)
            f = self._extrude_speed_mmm()
            owner.gcode.run_script_from_command("M83")
            self._extrude_mm(owner.purge_length, f)

            owner.path_states[path] = 'loaded'
            gcmd.respond_info(
                "SA: === LOAD COMPLETE (resumed from nozzle) — path %d ===" % path)
            self._restore_state(gcmd, path, is_printing)
            return

        # ══════════════════════════════════════════════════════════════════════
        # Branch B: ENTRY + EXTRUDER — filament at extruder gears
        # Wiggle verify, retract clear of extruder sensor, then heat+fill+purge
        # ══════════════════════════════════════════════════════════════════════
        if has_entry and has_extruder and not has_toolhead:
            gcmd.respond_info("SA: Filament at extruder gears — wiggle verifying...")
            motion.servo_engage()

            if not self._wiggle_check_encoder(gcmd, path):
                gcmd.respond_info(
                    "SA: ERROR — no encoder motion on path %d. "
                    "Filament may be broken. Check tube." % path)
                motion.servo_disengage()
                return

            # Retract until extruder sensor clears
            gcmd.respond_info("SA: Retracting to clear extruder sensor...")
            enc = owner._encoder(path)
            enc.set_direction(forward=False)
            enc.reset_distance()
            limit     = 200.0
            retracted = 0.0
            no_motion = 0
            while owner._extruder_sensor_active(path) and retracted < limit:
                prev = abs(enc.get_distance())
                motion.drive_move(-owner.feed_step_size, speed=owner.feed_speed)
                owner.reactor.pause(owner.reactor.monotonic() + owner.sensor_delay)
                moved = abs(enc.get_distance()) - prev
                retracted += owner.feed_step_size
                if moved < owner.feed_step_size * 0.2:
                    no_motion += 1
                    if no_motion >= 3:
                        gcmd.respond_info(
                            "SA: ERROR — encoder not moving for 3 steps on path %d "
                            "(%.0fmm driven, %.1fmm encoder). "
                            "Drive gear lost grip or filament jammed."
                            % (path, retracted, abs(enc.get_distance())))
                        motion.servo_disengage()
                        return
                else:
                    no_motion = 0

            if owner._extruder_sensor_active(path):
                gcmd.respond_info(
                    "SA: ERROR — could not clear extruder sensor after %.0fmm on path %d. "
                    "Check for jam." % (limit, path))
                motion.servo_disengage()
                return

            gcmd.respond_info(
                "SA: Confirmed — extruder sensor cleared (%.1fmm retracted). "
                "Filament tip just before extruder gears." % retracted)

            motion.servo_disengage()
            owner.path_states[path] = 'partial'
            motion.save_position()
            # Fall through to heat + fill + purge

        # ══════════════════════════════════════════════════════════════════════
        # Branch C: ENTRY ONLY — filament in bowden (or fresh insert or parked)
        # ══════════════════════════════════════════════════════════════════════
        elif has_entry and not has_extruder and not has_toolhead:
            if owner.path_states[path] == 'partial':
                # Filament parked at drive gears from previous unload.
                # Skip park+clear: engage and verify grip, then blast through bowden.
                gcmd.respond_info(
                    "SA: Parked filament on path %d — engaging and verifying grip..."
                    % path)
                motion.servo_engage()
            else:
                # Fresh filament inserted: park at encoder for consistent start.
                gcmd.respond_info(
                    "SA: Entry sensor only — parking filament for consistent start...")
                motion.servo_engage()
                self._park_filament_at_encoder(gcmd, path)
                self._retract_to_clear(gcmd, path)

            if not self._engage_check(gcmd, path):
                return

            if not self._blast_and_approach(gcmd, path):
                return

            # Keep servo engaged — common section needs it for sync feed
            owner.path_states[path] = 'partial'
            motion.save_position()
            # Fall through to heat + sync feed + purge

        # ══════════════════════════════════════════════════════════════════════
        # Common: cooling pad → heat → fill nozzle → purge → restore
        # ══════════════════════════════════════════════════════════════════════
        # Heat (cooling pad already set by _park for no-print loads)
        self._heat_for_load(gcmd, path)
        # Move to purge position (no-print: cooling pad → X175 Y0)
        self._move_to_purge_position(gcmd, is_printing)

        # Re-engage servo if Branch B disengaged it; Branch C is already engaged
        if not owner._servo_is_engaged:
            motion.servo_engage()

        # Sync drive + extruder together until toolhead sensor confirms grip.
        # Handles dead zone (extruder sensor → extruder gears, ~20mm) and beyond.
        # Disengages servo on return.
        if not self._sync_feed_to_toolhead_sensor(gcmd, path):
            return

        # Ensure servo is disengaged before extruder-only fill+purge
        motion.servo_disengage()

        # Fill nozzle (extruder gears → nozzle tip) then initial purge
        self._fill_and_purge(gcmd, path)

        owner.path_states[path] = 'loaded'

        # Refresh this toolhead's status LEDs now that it's loaded —
        # _SA_LED_FROM_STATE picks ACTIVE/PARKED/UNLOADED based on
        # whether this path is currently mounted, has a color set, etc.
        owner.gcode.run_script_from_command(
            "_SA_LED_FROM_STATE TOOL=%d" % path)

        # Set up purge confirmation — _restore_state is deferred until user responds
        owner._cal_state = 'load_purge'
        owner._cal_data  = {'path': path, 'is_printing': is_printing}
        self._prompt_purge(gcmd, path)

    # ═══════════════════════════════════════════════════════════════════════════
    # Unload sequence
    # ═══════════════════════════════════════════════════════════════════════════

    def form_tip(self, gcmd, path, is_printing, ov=None, material=None):
        """Shape the filament tip so it can be pulled back through the gears.

        Follows the ERCF / Happy Hare sequence, which this previously did not:

            ram      optional push, to pressurise the melt
            sever    ONE fast pull, long enough to break the melt and no longer
            ease     ramped slow pull back to the cooling zone
            cool     oscillate in the cooling zone, speeding up as it stiffens
            clear    past the gears once the tip is solid

        The oscillation is the part that actually forms the tip. Without it a
        hot pull just necks the melt and lets surface tension ball up whatever
        is behind it -- which is what the old routine produced: a 2.25mm blob
        on 1.75mm filament with a 1.4mm neck.

        The previous version also ran its fast pull for 48mm rather than
        stopping once the melt was severed, dragging the tip through the whole
        cooling zone at 70mm/s with nothing shaping it, and its third phase was
        unreachable (slow_dist computed negative).

        `ov` is an optional dict of overrides so SA_FORM_TIP can sweep values
        without a config edit and a restart. `material` forces a particular
        material's values instead of the loaded profile's, so one can be tuned
        without its spool in the machine.
        """
        owner = self.owner
        ov    = dict(ov or {})

        # A tip forms at a temperature the polymer chooses, not one the
        # machine does: what shears cleanly for PLA merely stretches ASA. So
        # the loaded profile's material selects its own values, layered under
        # any explicit SA_FORM_TIP override -- a tuning sweep still wins -- and
        # over the tuned globals, which stay the fallback for a material with
        # nothing configured.
        mat_ov, mat_note = owner.tip_form_overrides(path, material)
        for k, v in mat_ov.items():
            ov.setdefault(k, v)
        gcmd.respond_info("SA: %s" % mat_note)

        def cfg(name):
            return ov.get(name, getattr(owner, 'tip_form_' + name))

        temp          = cfg('temp')
        push_length   = cfg('push_length')
        push_speed    = cfg('push_speed')
        sever_dist    = cfg('sever_dist')
        sever_speed   = cfg('retract_speed')
        ease_speed    = cfg('slow_speed')
        cooling_pos   = cfg('cooling_pos')
        cooling_len   = cfg('cooling_len')
        cooling_moves = int(cfg('cooling_moves'))
        cool_speed_in = cfg('cool_speed_in')
        cool_speed_out = cfg('cool_speed_out')
        shear_temp     = cfg('shear_temp')
        shear_speed    = cfg('shear_speed')
        extruder_name = owner._extruder_names[path]
        current_temp  = self._extruder_temp(path)

        # A good tip forms below klipper's min_extrude_temp, which it enforces
        # on every E move -- and it fails part way in, once the toolhead has
        # already parked and cooled. So lower the threshold for the duration
        # and restore it in a finally.
        #
        # Dropped to a fixed floor rather than to the target: setting it equal
        # to the target leaves no margin, and the hotend rides a degree or two
        # either side of setpoint.
        heater    = None
        saved_min = None
        try:
            heater = owner.printer.lookup_object(extruder_name).get_heater()
        except Exception:
            pass
        if heater is not None and temp < heater.min_extrude_temp:
            if temp < owner.TIP_FORM_TEMP_FLOOR:
                gcmd.respond_info(
                    "SA: tip_form_temp %.0f is below the %.0f°C floor — refusing "
                    "to form that cold." % (temp, owner.TIP_FORM_TEMP_FLOOR))
                return
            saved_min = heater.min_extrude_temp
            heater.min_extrude_temp = owner.TIP_FORM_TEMP_FLOOR
            # can_extrude only updates on a temperature callback; let one land
            # rather than racing the first move.
            heater.can_extrude = (heater.smoothed_temp >= owner.TIP_FORM_TEMP_FLOOR)
            owner.reactor.pause(owner.reactor.monotonic() + 0.5)
            gcmd.respond_info(
                "SA: min_extrude_temp %.0f → %.0f for tip forming; restored after."
                % (saved_min, owner.TIP_FORM_TEMP_FLOOR))

        try:
            self._form_tip_moves(gcmd, path, is_printing, temp, extruder_name,
                                 current_temp, push_length, push_speed,
                                 sever_dist, sever_speed, ease_speed,
                                 cooling_pos, cooling_len, cooling_moves,
                                 cool_speed_in, cool_speed_out,
                                 shear_temp, shear_speed)
        finally:
            if saved_min is not None:
                heater.min_extrude_temp = saved_min
                heater.can_extrude = (heater.smoothed_temp >= saved_min)
                gcmd.respond_info(
                    "SA: min_extrude_temp restored to %.0f." % saved_min)

    def _form_tip_moves(self, gcmd, path, is_printing, temp, extruder_name,
                        current_temp, push_length, push_speed, sever_dist,
                        sever_speed, ease_speed, cooling_pos, cooling_len,
                        cooling_moves, cool_speed_in, cool_speed_out,
                        shear_temp=0.0, shear_speed=3.0):
        """The moves themselves. Split out so form_tip can wrap them in the
        min_extrude_temp override without a long try block."""
        owner = self.owner

        # ---- temperature ------------------------------------------------
        # In shear mode the heater is switched off a few lines below, so
        # driving to tip_form_temp first is a settle that buys nothing -- it
        # cooled 205 to 165, waited, then turned off and waited again down to
        # 150. All that is needed here is enough heat to push the ram; the
        # shear stage does its own single wait on the way down.
        if shear_temp > 0:
            ram_floor = max(shear_temp, owner.TIP_FORM_TEMP_FLOOR)
            if current_temp < ram_floor:
                gcmd.respond_info(
                    "SA: Heating %s %.0f → %.0f°C so the ram can move..."
                    % (extruder_name, current_temp, temp))
                owner.gcode.run_script_from_command(
                    "SET_HEATER_TEMPERATURE HEATER=%s TARGET=%.0f"
                    % (extruder_name, temp))
                owner.gcode.run_script_from_command(
                    "TEMPERATURE_WAIT SENSOR=%s MINIMUM=%.0f"
                    % (extruder_name, ram_floor))
            else:
                gcmd.respond_info(
                    "SA: %s at %.0f°C, hot enough to ram — going straight to the shear."
                    % (extruder_name, current_temp))
        else:
            self._hold_temp_for_forming(gcmd, extruder_name, temp, current_temp)



        self._move_to_purge_position(gcmd, is_printing)
        owner.gcode.run_script_from_command("M83")

        # ---- ram ---------------------------------------------------------
        if push_length > 0:
            gcmd.respond_info(
                "SA: Tip ram %.1fmm at %.0fmm/s..." % (push_length, push_speed))
            self._extrude_mm(push_length, int(push_speed * 60))

        # ---- cold shear (optional) ---------------------------------------
        # Switch the heater off and let the hotend fall, then draw the filament
        # out slowly. It parts at the boundary between what is bonded to the
        # bore and what is not, instead of stretching out of a melt -- so no
        # bead forms at all. The cost is the cooldown wait, and the risk is
        # that a fully cold pull grips harder than the extruder can pull, so
        # step the temperature down rather than starting at the bottom.
        if shear_temp > 0:
            gcmd.respond_info(
                "SA: Cold shear — heater off, waiting for %s to reach %.0f°C "
                "(up to %.0fs)..."
                % (extruder_name, shear_temp, owner.tip_form_shear_timeout))
            owner.gcode.run_script_from_command(
                "SET_HEATER_TEMPERATURE HEATER=%s TARGET=0" % extruder_name)

            deadline = owner.reactor.monotonic() + owner.tip_form_shear_timeout
            while owner.reactor.monotonic() < deadline:
                if self._extruder_temp(path) <= shear_temp:
                    break
                owner.reactor.pause(owner.reactor.monotonic() + 1.0)

            reached = self._extruder_temp(path)
            gcmd.respond_info("SA: Cold shear — at %.0f°C, drawing out at %.1fmm/s..."
                              % (reached, shear_speed))

            # Nothing is being pushed into a cold nozzle here, so the extrude
            # guard is lifted entirely rather than to the forming floor.
            enc = owner._encoder(path)
            try:
                enc.set_direction(forward=False)
                enc.reset_distance()
            except Exception:
                enc = None

            token = self._allow_cold_extrude(path, 0.0)
            try:
                self._extrude_mm(-(cooling_pos + push_length),
                                 max(1, int(shear_speed * 60)))
            finally:
                self._restore_extrude_floor(token)

            if enc is not None:
                moved = abs(enc.get_distance())
                want  = cooling_pos + push_length
                if moved < want * 0.5:
                    gcmd.respond_info(
                        "SA: WARNING — encoder saw %.1fmm of %.1fmm. The tip is "
                        "probably gripping and the extruder is stripping it. "
                        "Raise SHEAR." % (moved, want))
                else:
                    gcmd.respond_info("SA: Cold shear — encoder %.1fmm." % moved)

            self._clear_past_gears(gcmd, path, cooling_pos, ease_speed)
            return

        # ---- sever -------------------------------------------------------
        # Everything from here is measured as distance of the tip back from the
        # nozzle, so the ram has to be paid back before any of it counts.
        to_cooling = push_length + cooling_pos
        sever      = min(sever_dist, to_cooling)
        gcmd.respond_info(
            "SA: Sever %.1fmm at %.0fmm/s (break the melt)..." % (sever, sever_speed))
        self._extrude_mm(-sever, int(sever_speed * 60))

        # ---- ease back to the cooling zone -------------------------------
        # Ramped 1.0 / 0.5 / 0.3 over 70 / 20 / 10 percent of what is left, the
        # same taper Happy Hare uses: the tip is still soft here and pulling at
        # one flat speed is what stretches the neck.
        remaining = to_cooling - sever
        if remaining > 0:
            gcmd.respond_info(
                "SA: Ease %.1fmm to cooling zone at %.0f/%.0f/%.0f mm/s..."
                % (remaining, ease_speed, ease_speed * 0.5, ease_speed * 0.3))
            for fraction, scale in ((0.7, 1.0), (0.2, 0.5), (0.1, 0.3)):
                seg = remaining * fraction
                if seg > 0:
                    self._extrude_mm(-seg, max(1, int(ease_speed * scale * 60)))

        # ---- cooling moves -----------------------------------------------
        # In and out on the spot, accelerating as the plastic stiffens. Speed
        # steps across every half-move, so a 4-move run has 8 steps.
        if cooling_moves > 0 and cooling_len > 0:
            steps = max(1, 2 * cooling_moves - 1)
            increment = (cool_speed_out - cool_speed_in) / float(steps)
            gcmd.respond_info(
                "SA: %d cooling moves of %.1fmm, %.0f→%.0f mm/s..."
                % (cooling_moves, cooling_len, cool_speed_in, cool_speed_out))
            speed = cool_speed_in
            for _ in range(cooling_moves):
                self._extrude_mm(cooling_len, max(1, int(speed * 60)))
                speed += increment
                self._extrude_mm(-cooling_len, max(1, int(speed * 60)))
                speed += increment

        self._clear_past_gears(gcmd, path, cooling_pos, ease_speed)

    def _hold_temp_for_forming(self, gcmd, extruder_name, temp, current_temp):
        """Pin the heater at the forming temperature and wait for it.

        The target is always set, not only when the reading sits outside a
        band: a heater that is off and drifting can read in range at the start
        and fall below min_extrude_temp part way through the moves, which
        killed the sequence on the ease with no heating or cooling step ever
        logged.
        """
        owner = self.owner
        owner.gcode.run_script_from_command(
            "SET_HEATER_TEMPERATURE HEATER=%s TARGET=%.0f" % (extruder_name, temp))

        if current_temp < temp - 5:
            gcmd.respond_info("SA: Heating %s %.0f → %.0f°C for tip forming..."
                              % (extruder_name, current_temp, temp))
            owner.gcode.run_script_from_command(
                "TEMPERATURE_WAIT SENSOR=%s MINIMUM=%.0f" % (extruder_name, temp - 2))
        elif current_temp > temp + 5:
            gcmd.respond_info("SA: Cooling %s %.0f → %.0f°C for tip forming..."
                              % (extruder_name, current_temp, temp))
            owner.gcode.run_script_from_command(
                "TEMPERATURE_WAIT SENSOR=%s MAXIMUM=%.0f" % (extruder_name, temp + 5))
        else:
            gcmd.respond_info("SA: %s already at %.0f°C, holding for tip forming."
                              % (extruder_name, current_temp))

    def _clear_past_gears(self, gcmd, path, cooling_pos, speed):
        """Take the finished tip from the cooling zone out past the extruder
        gears and the sensor, so the drive motor can take over.

        Always runs with the extrude guard lifted: after a shear the hotend is
        already well below it, and this move pulls filament outwards rather
        than pushing it into a cold nozzle.
        """
        owner  = self.owner
        target = owner.nozzle_to_sensor_dist * 1.05
        clear  = target - cooling_pos
        if clear <= 0:
            gcmd.respond_info(
                "SA: Tip already past the sensor at %.0fmm — no clearing move."
                % cooling_pos)
            return

        gcmd.respond_info(
            "SA: Clear %.1fmm at %.0fmm/s (past gears, tip at %.0fmm)..."
            % (clear, speed, target))
        token = self._allow_cold_extrude(path, 0.0)
        try:
            self._extrude_mm(-clear, max(1, int(speed * 60)))
        finally:
            self._restore_extrude_floor(token)


    def _do_unload_inner(self, gcmd, path):
        """Full filament unload sequence for *path*.

        Sensor state determines what's done:
          all sensors / toolhead active → temp check, tip form, fast retract, drive to entry
          entry + extruder only          → wiggle verify, drive retract to entry
          entry only                     → drive retract to entry (no heat needed)
          empty                          → nothing to do
        """
        owner  = self.owner
        motion = owner.motion

        gcmd.respond_info("SA: === UNLOAD path %d ===" % path)

        # ── Sensor state ──────────────────────────────────────────────────────
        has_entry    = owner._entry_sensor_active(path)
        has_extruder = owner._extruder_sensor_active(path)
        has_toolhead = owner._toolhead_sensor_active(path)

        gcmd.respond_info("SA: Sensors — entry:%s extruder:%s toolhead:%s" % (
            "Y" if has_entry else "N",
            "Y" if has_extruder else "N",
            "Y" if has_toolhead else "N"))

        if not has_entry and not has_extruder and not has_toolhead:
            gcmd.respond_info("SA: Path %d appears empty — nothing to unload." % path)
            owner.path_states[path] = 'empty'
            return

        # ── Pre-flight ────────────────────────────────────────────────────────
        if not self._is_homed():
            gcmd.respond_info("SA: Printer not homed — running G28...")
            self.owner.gcode.run_script_from_command("G28")
            self.owner.gcode.run_script_from_command("M400")

        is_printing = self._is_printing()
        gcmd.respond_info("SA: Print state: %s." % ("PRINTING" if is_printing else "idle"))
        self._park(gcmd, is_printing)
        self._switch_tool(gcmd, path)
        self._ensure_selector(gcmd, path)

        extruder_name = owner._extruder_names[path]

        # ══════════════════════════════════════════════════════════════════════
        # Branch A: TOOLHEAD ACTIVE — filament at/near nozzle
        # Temp check → tip form → fast retract past gears → drive to entry
        # ══════════════════════════════════════════════════════════════════════
        if has_toolhead:
            self.form_tip(gcmd, path, is_printing)

            owner.path_states[path] = 'partial'

            # Heater off — tip is past heatbreak (60mm+), safe to cool now
            gcmd.respond_info("SA: Heater off — filament clear of melt zone.")
            owner.gcode.run_script_from_command(
                "SET_HEATER_TEMPERATURE HEATER=%s TARGET=0" % extruder_name)

            # Engage drive servo — filament tip is past the heatbreak and extruder
            # gears.  From here all retraction is done by the drive motor.
            motion.servo_engage()

            enc = owner._encoder(path)
            enc.set_direction(forward=False)
            enc.reset_distance()

            # If extruder sensor still triggered: filament tip has passed the gears
            # but hasn't fully cleared the sensor.  The extruder motor can no longer
            # grip it — sync drive + extruder together in one continuous move.
            has_ext_sensor = bool(owner._extruder_sensor_names[path])
            if has_ext_sensor and owner._extruder_sensor_active(path):
                gcmd.respond_info(
                    "SA: Extruder sensor still active — sync drive+extruder "
                    "to pull filament clear...")

                dn       = owner._drv_name()
                sync_spd = owner.tip_form_slow_speed
                sync_f   = int(sync_spd * 60)
                max_sync = owner.sensor_retry_dist * 3   # e.g. 60mm

                owner.gcode.run_script_from_command("M83")
                motion._cancel_timeout(dn)
                owner.gcode.run_script_from_command(
                    "MANUAL_STEPPER STEPPER=%s ENABLE=1" % dn)

                # Single continuous move — drive starts async, extruder follows,
                # M400 inside _extrude_mm waits for both to complete.
                owner.gcode.run_script_from_command(
                    "MANUAL_STEPPER STEPPER=%s SET_POSITION=0 "
                    "MOVE=%.2f SPEED=%.1f SYNC=0"
                    % (dn, -max_sync, sync_spd))
                # The heater was switched off a few lines above and the tip is
                # already past the gears, so this move is always below
                # min_extrude_temp. It is pulling filament out, not pushing it
                # into a cold nozzle.
                cold = self._allow_cold_extrude(path)
                try:
                    self._extrude_mm(-max_sync, sync_f)
                finally:
                    self._restore_extrude_floor(cold)
                motion._arm_timeout(dn)

                # Encoder grip check
                enc_dist = abs(enc.get_distance())
                if enc_dist < max_sync * 0.3:
                    gcmd.respond_info(
                        "SA: WARNING — low encoder motion (%.1fmm / %.0fmm) "
                        "on path %d. Drive gear may not have grip."
                        % (enc_dist, max_sync, path))

                if owner._extruder_sensor_active(path):
                    motion.servo_disengage()
                    gcmd.respond_info(
                        "SA: ERROR — extruder sensor path %d still active after "
                        "%.0fmm sync retract.\n"
                        "Check for jam near extruder_sensor_%d or verify "
                        "sensor wiring.\n"
                        "Clear manually then re-run SA_UNLOAD TOOL=%d."
                        % (path, max_sync, path, path))
                    owner._cal_state = None
                    owner._cal_data  = {}
                    return

                gcmd.respond_info(
                    "SA: Extruder sensor cleared (encoder: %.1fmm)." % enc_dist)
            else:
                gcmd.respond_info("SA: Extruder sensor already clear.")

            # ── Zero at extruder sensor ──────────────────────────────────────────
            # Push filament forward slowly until the extruder sensor re-triggers.
            # This gives an exact reference position so the bowden retract distance
            # is based on the calibrated bowden_length from a known point.
            if has_ext_sensor:
                gcmd.respond_info(
                    "SA: Zeroing — pushing forward to extruder sensor...")
                enc.set_direction(forward=True)
                enc.reset_distance()
                zeroed   = False
                max_zero = owner.sensor_retry_dist * 3   # 60mm ceiling
                while abs(enc.get_distance()) < max_zero:
                    motion.drive_move(5.0, speed=owner.tip_form_slow_speed)
                    owner.reactor.pause(
                        owner.reactor.monotonic() + owner.sensor_delay)
                    if owner._extruder_sensor_active(path):
                        zeroed = True
                        gcmd.respond_info(
                            "SA: Zero confirmed — %.1fmm forward to sensor."
                            % abs(enc.get_distance()))
                        break
                if not zeroed:
                    gcmd.respond_info(
                        "SA: WARNING — extruder sensor did not re-trigger "
                        "after %.0fmm forward. "
                        "Proceeding with bowden_length as estimate." % max_zero)

            # ── Fast bowden blast — pull filament 95% of bowden length ──────────
            # Filament tip is now clear of the extruder sensor.  One fast continuous
            # drive move brings the tip to just inside the drive gear area.
            # The entry sensor is on the roll side of the drive gears so the
            # filament exits the gears before the entry sensor ever clears —
            # we park here and let the user physically remove the filament.
            sv          = owner.printer.lookup_object('save_variables', None)
            saved_max   = float(sv.allVariables.get('encoder_max_speed', 0)) if sv else 0
            blast_spd   = (saved_max * 0.75) if saved_max > 0 else owner.feed_speed
            bowden      = owner._bowden_lengths[path]
            blast_dist  = bowden * 0.95
            gcmd.respond_info(
                "SA: Blast retract %.0fmm at %.0fmm/s "
                "(95%% of bowden %.0fmm)..."
                % (blast_dist, blast_spd, bowden))
            enc.reset_distance()
            motion.drive_move(-blast_dist, speed=blast_spd)

            # Park precisely at drive gear encoder (servo still engaged)
            gcmd.respond_info("SA: Positioning filament precisely at drive gear...")
            self._park_filament_at_encoder(gcmd, path, from_load=False)

            motion.servo_disengage()
            owner.path_states[path] = 'partial'
            motion.save_position()
            gcmd.respond_info(
                "SA: Filament parked at drive gear — path %d. "
                "Pull from roll end to remove." % path)

            # Path is empty — force LEDs to UNLOADED (dim white logo,
            # nozzle off) regardless of any stale color still set in
            # the autoloader status object. sa_load_unload's UI clears
            # the color via SA_SET_MATERIAL on its next status update.
            owner.gcode.run_script_from_command(
                "_SA_LED_UNLOADED TOOL=%d" % path)

            if is_printing:
                gcmd.respond_info("SA: Resuming print...")
                owner.gcode.run_script_from_command("RESUME")
            else:
                owner._cal_state = 'unload_done'
                owner._cal_data  = {'path': path, 'is_printing': is_printing}
                self._prompt_unload_park(gcmd, path)
            return  # Branch A complete — do not fall through to entry-sensor loop

        # ══════════════════════════════════════════════════════════════════════
        # Branch B: ENTRY + EXTRUDER — filament at gears, not at nozzle
        # Wiggle verify, drive retract to entry
        # ══════════════════════════════════════════════════════════════════════
        elif has_entry and has_extruder and not has_toolhead:
            gcmd.respond_info(
                "SA: Filament at extruder gears — wiggle verifying...")
            motion.servo_engage()

            if not self._wiggle_check_encoder(gcmd, path):
                gcmd.respond_info(
                    "SA: ERROR — no encoder motion on path %d. "
                    "Filament may be broken." % path)
                motion.servo_disengage()
                return

            gcmd.respond_info("SA: Filament confirmed. Retracting to entry sensor...")

        # ══════════════════════════════════════════════════════════════════════
        # Branch C: ENTRY ONLY — filament in bowden
        # ══════════════════════════════════════════════════════════════════════
        elif has_entry and not has_extruder and not has_toolhead:
            gcmd.respond_info(
                "SA: Filament in bowden only — retracting to entry sensor...")
            motion.servo_engage()

        # ── Drive retract until entry sensor clears ───────────────────────────
        enc = owner._encoder(path)
        enc.set_direction(forward=False)
        enc.reset_distance()
        retracted = 0.0
        limit     = owner._bowden_lengths[path] + 100.0
        no_motion = 0

        while owner._entry_sensor_active(path) and retracted < limit:
            prev = abs(enc.get_distance())
            motion.drive_move(-owner.feed_step_size)
            owner.reactor.pause(owner.reactor.monotonic() + owner.sensor_delay)
            moved = abs(enc.get_distance()) - prev
            retracted += owner.feed_step_size
            if moved < owner.feed_step_size * 0.2:
                no_motion += 1
                if no_motion >= 3:
                    gcmd.respond_info(
                        "SA: ERROR — encoder not moving for 3 steps on path %d "
                        "(%.0fmm driven, %.1fmm encoder). "
                        "Drive gear lost grip or filament jammed."
                        % (path, retracted, abs(enc.get_distance())))
                    motion.servo_disengage()
                    owner.path_states[path] = 'unknown'
                    return
            else:
                no_motion = 0

        if owner._entry_sensor_active(path):
            gcmd.respond_info(
                "SA: WARNING — entry sensor still active after %.0fmm on path %d. "
                "Check for jam." % (retracted, path))

        motion.servo_disengage()
        owner.path_states[path] = 'empty'
        motion.save_position()
        gcmd.respond_info(
            "SA: Drive retract complete — path %d (%.1fmm retracted)."
            % (path, abs(enc.get_distance())))

        # Path is empty — force LEDs to UNLOADED. Same rationale as the
        # Branch A path above.
        owner.gcode.run_script_from_command(
            "_SA_LED_UNLOADED TOOL=%d" % path)

        if is_printing:
            gcmd.respond_info("SA: Resuming print...")
            owner.gcode.run_script_from_command("RESUME")
        else:
            owner._cal_state = 'unload_done'
            owner._cal_data  = {'path': path, 'is_printing': is_printing}
            self._prompt_unload_park(gcmd, path)
