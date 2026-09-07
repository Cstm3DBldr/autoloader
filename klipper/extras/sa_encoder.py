# sa_encoder.py - Autoloader Rotary Encoder (Binky-style single-pulse)
#
# One instance per [sa_encoder toolX] section.
# Each encoder tracks actual filament movement independently using hardware
# interrupts via Klipper's buttons module. All 6 can accumulate counts
# simultaneously without data loss — events are queued in the reactor and
# processed in order.
#
# Usage in hardware.cfg:
#   [sa_encoder tool0]
#   sensor_pin: ^autoloader_a:SA_ENCODER_T0
#   mm_per_pulse: 1.0      # calibrate this per encoder
#
# Python API (called from filament_feed.py):
#   encoder.set_direction(forward=True)
#   encoder.reset_distance()
#   encoder.get_distance()  → mm moved since last reset

import logging

class SAEncoder:
    def __init__(self, config):
        self.printer  = config.get_printer()
        # Name is the suffix after "sa_encoder" or just "sa_encoder" for single instance
        parts = config.get_name().split()
        self.name = parts[-1] if len(parts) > 1 else 'main'

        # mm of filament per encoder count — calibrate with SA_CALIBRATE_ENCODER
        # Binky 23-tooth default: ~0.96mm per count when both edges are counted
        self.mm_per_pulse = config.getfloat('mm_per_pulse', 1.0)

        # Count both transitions of each tooth rather than just the rising one.
        # The wheel gives two edges per tooth and using one halves the
        # resolution for nothing -- a state too short to sample is missed
        # either way, so this costs no top speed. Off only for a wheel or
        # sensor with a duty cycle so uneven that one of the two states cannot
        # be sampled at all.
        self.count_both_edges = config.getboolean('count_both_edges', True)

        self._distance  = 0.0
        self._direction = 1     # +1 = forward (loading), -1 = reverse (unloading)

        # Register sensor pin for interrupt-driven pulse counting
        sensor_pin = config.get('sensor_pin')
        buttons = self.printer.load_object(config, 'buttons')
        buttons.register_buttons([sensor_pin], self._pulse_callback)

        # Load calibrated mm_per_pulse from save_variables at ready (overrides config)
        self.printer.register_event_handler('klippy:ready', self._on_ready)

        logging.info("SA Encoder '%s' ready — %.4f mm/pulse", self.name, self.mm_per_pulse)

    def _on_ready(self):
        sv = self.printer.lookup_object('save_variables', None)
        if sv is None:
            return
        allvars = sv.allVariables
        key = 'encoder_mpp_%s' % self.name
        if key not in allvars:
            return
        try:
            saved = float(allvars[key])
        except (ValueError, TypeError):
            return

        # A value with no edge marker was calibrated counting one edge. If we
        # are now counting two, each count covers half as much filament, so the
        # saved figure is twice what it should be. Halving it here keeps the
        # path usable until SA_CALIBRATE_ENCODER writes a marked value; the
        # marker is what stops this happening twice.
        edges = allvars.get('encoder_edges_%s' % self.name, None)
        if self.count_both_edges and edges is None:
            self.mm_per_pulse = saved / 2.0
            logging.info(
                "SA Encoder '%s': mm_per_pulse %.5f -> %.5f — the saved value "
                "was calibrated counting one edge and both are now counted. "
                "Re-run SA_CALIBRATE_ENCODER to measure it properly.",
                self.name, saved, self.mm_per_pulse)
            return

        self.mm_per_pulse = saved
        logging.info(
            "SA Encoder '%s': mm_per_pulse=%.5f (from save_variables)",
            self.name, self.mm_per_pulse)

    # ------------------------------------------------------------------
    # Interrupt callback — called by Klipper reactor on each pin edge
    # ------------------------------------------------------------------

    def _pulse_callback(self, eventtime, state):
        if state or self.count_both_edges:
            self._distance += self.mm_per_pulse * self._direction

    # ------------------------------------------------------------------
    # API used by filament_feed.py
    # ------------------------------------------------------------------

    def set_direction(self, forward=True):
        """Call before running the feed motor so distance accumulates correctly."""
        self._direction = 1 if forward else -1

    def reset_distance(self):
        """Zero the counter. Returns the previous value."""
        old = self._distance
        self._distance = 0.0
        return old

    def get_distance(self):
        """Total mm moved since last reset (positive = toward extruder)."""
        return self._distance

    # ------------------------------------------------------------------
    # Klipper status (readable in macros as printer['sa_encoder tool0'].distance)
    # ------------------------------------------------------------------

    def get_status(self, eventtime):
        return {
            'distance':     round(self._distance, 2),
            'mm_per_pulse': self.mm_per_pulse,
            'direction':    self._direction,
        }

    @staticmethod
    def load_config(config):
        return SAEncoder(config)

    @staticmethod
    def load_config_prefix(config):
        return SAEncoder(config)

# Support both [sa_encoder] (single) and [sa_encoder name] (named) sections
def load_config(config):
    return SAEncoder(config)

def load_config_prefix(config):
    return SAEncoder(config)
