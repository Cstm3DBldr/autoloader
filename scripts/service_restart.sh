#!/usr/bin/env bash
# Restart a printer service through Moonraker, and PROVE it restarted.
#
#     bash scripts/service_restart.sh KlipperScreen
#     bash scripts/service_restart.sh klipper
#
# Why this exists: `sudo systemctl restart KlipperScreen` over a non-interactive
# ssh fails with "a terminal is required to read the password" and returns 1.
# Paired with the 2>/dev/null that usually follows it, that is a restart which
# reports nothing and does nothing -- KlipperScreen ran for two days on code
# from two days earlier while every deploy said it had been restarted, and the
# symptom was a touchscreen showing a guide that had been rewritten twice.
#
# Moonraker's /machine/services/restart is wired to passwordless sudo through
# PolicyKit on this build, which is the same route scripts/klipper_service_restart.sh
# takes. This one adds the part that was missing: checking afterwards.
set -eu

SERVICE="${1:-}"
[ -n "${SERVICE}" ] || { echo "usage: $0 <service>   e.g. KlipperScreen" >&2; exit 2; }
HOST="${SA_HOST:-localhost:7125}"

# Match the actual process, not the unit: KlipperScreen's MainPID is a launcher
# and the Python that holds the imported panels is a grandchild under xinit, so
# "the unit is active" is true even when nothing reloaded.
case "${SERVICE}" in
    KlipperScreen) PAT="KlipperScreen/screen.py" ;;
    klipper)       PAT="klippy/klippy.py" ;;
    moonraker)     PAT="moonraker/moonraker.py" ;;
    *)             PAT="${SERVICE}" ;;
esac

before="$(pgrep -f "${PAT}" | head -1 || true)"
echo "[1/3] ${SERVICE}: pid before = ${before:-none}"

echo "[2/3] Asking Moonraker to restart it..."
out="$(curl -s -X POST "http://${HOST}/machine/services/restart?service=${SERVICE}" -m 30 || true)"
case "${out}" in
    *'"result":"ok"'*) : ;;
    *) echo "ERROR: Moonraker refused: ${out:-no response}" >&2
       echo "       Is '${SERVICE}' in moonraker.conf's allowed services?" >&2
       exit 1 ;;
esac

echo "[3/3] Waiting for it to come back..."
for _ in $(seq 1 20); do
    sleep 1
    after="$(pgrep -f "${PAT}" | head -1 || true)"
    if [ -n "${after}" ] && [ "${after}" != "${before}" ]; then
        echo "      pid after  = ${after}  — restarted."
        exit 0
    fi
done

after="$(pgrep -f "${PAT}" | head -1 || true)"
if [ -z "${after}" ]; then
    echo "ERROR: ${SERVICE} is not running at all after the restart." >&2
else
    echo "ERROR: ${SERVICE} still has pid ${after}; it never restarted." >&2
    echo "       Whatever it has in memory is what it had before." >&2
fi
exit 1
