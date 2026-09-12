#!/bin/bash
# Restart the Klipper service via Moonraker, which DOES reload Python
# extras (FIRMWARE_RESTART does not — it only re-parses cfg).
#
# Usage:
#   bash ~/autoloader/scripts/klipper_service_restart.sh        # on the printer
#   SA_HOST=192.168.1.214 bash scripts/klipper_service_restart.sh   # from a dev box
#
# Why this exists:
#   FIRMWARE_RESTART is the Klipper-internal restart command. It re-reads
#   printer.cfg and any [include]'d files, then resets the MCU. It does
#   NOT reload Python modules — the running klippy process keeps the
#   in-memory copy of every Python extra it imported at startup. So if
#   you edit ~/klipper/klippy/extras/foo.py and then FIRMWARE_RESTART,
#   your changes do NOT take effect.
#
#   sudo systemctl restart klipper does reload Python, but requires
#   sudo password.
#
#   Moonraker's /machine/services/restart endpoint hits PolicyKit /
#   sudoers config that grants the moonraker user passwordless restart
#   of specific services. This is the documented way to restart Klipper
#   from a script without an interactive sudo prompt.
#
# Use this for any change to:
#   - klipper/extras/*.py (autoloader, sa_motion, sa_sequences,
#     sa_calibration, sa_encoder, sa_led_animator)
#   - moonraker/sa_moonraker.py (Moonraker also reloads on this)
#
# For .cfg-only changes, FIRMWARE_RESTART is fine and faster.

# Refuse under a hot heater or a running operation -- see can_restart.py for
# why each one matters. SA_FORCE=1 overrides both.
HOST="${SA_HOST:-localhost}"
if [ "${SA_FORCE:-0}" != "1" ]; then
    REASON=$(python3 "$(dirname "$0")/can_restart.py" "$HOST")
    if [ $? -ne 0 ]; then
        echo "REFUSING to restart Klipper: $REASON"
        echo "  A toolhead MCU shuts down when the host goes away with its"
        echo "  heater on, and only FIRMWARE_RESTART clears that."
        echo "  Wait, or TURN_OFF_HEATERS, or re-run with SA_FORCE=1."
        exit 1
    fi
fi

curl -s -X POST "http://$HOST:7125/machine/services/restart" \
    -H 'Content-Type: application/json' \
    -d '{"service":"klipper"}'
echo
