#!/usr/bin/env bash
# Every "Timer too close" MCU shutdown still in the Klipper logs, one block
# per event: which board, the session it happened in, host load and CAN error
# counters from the last Stats line, when Python's garbage collector last ran,
# and the commands that ran just before.
#
# Klipper keeps about ten rotated logs, so an event drops out of reach within
# days. Run this soon after one happens and copy the block into
# docs/TIMER_TOO_CLOSE.md -- that file is the record; the logs are not.
#
#   bash ~/autoloader/scripts/timer_too_close_report.sh
#
# Read-only. SA_LOGS=<dir> to point it somewhere else.
set -u
LOGS="${SA_LOGS:-${HOME}/printer_data/logs}"
found=0
last_key=""
for f in $(ls -tr "${LOGS}"/klippy.log* 2>/dev/null); do
    for n in $(grep -an "shutdown: Timer too close" "$f" | grep -av "CommandError" \
               | cut -d: -f1); do
        # One block per event: Klipper repeats the message several times in
        # its shutdown dump, all inside the same session within seconds.
        sess=$(sed -n "1,${n}p" "$f" | grep -a '^Start printer at' | tail -1)
        up=$(sed -n "1,${n}p" "$f" | grep -ao '^Stats [0-9]*' | tail -1 | cut -d' ' -f2)
        key="${sess}|$(( ${up:-0} / 60 ))"
        [ "$key" = "$last_key" ] && continue
        last_key="$key"
        found=$((found + 1))
        stats=$(sed -n "1,${n}p" "$f" | grep -a '^Stats' | tail -1)
        echo "================================================================"
        echo "log:     $(basename "$f")  (line $n)"
        sed -n "${n}p" "$f" | cut -c1-120
        echo "session: $(echo "$sess" | cut -c1-60)"
        echo "uptime:  $(echo "$stats" | grep -oE '^Stats [0-9.]+' | cut -d' ' -f2)s"
        echo "host:    $(echo "$stats" | grep -oE 'sysload=[0-9.]+|memavail=[0-9]+' | tr '\n' ' ')"
        errs=$(echo "$stats" | grep -oE 'canstat_[a-z0-9]+: bus_state=[a-z]+ rx_error=[0-9]+ tx_error=[0-9]+ tx_retries=[0-9]+' \
               | grep -vE 'rx_error=0 tx_error=0 tx_retries=0' || true)
        echo "can:     ${errs:-no rx/tx errors or retries on any board}"
        # Python's garbage collector pauses the host. The reactor logs when
        # each generation last ran in the shutdown dump -- (gen0, gen1, gen2)
        # on the same clock as "uptime" -- so a collection just before the
        # shutdown shows here. 2026-10-09's gen1 ran ~0.1s before.
        echo "gc:      $(sed -n "${n},$((n + 3000))p" "$f" | grep -a 'Reactor garbage collection' | head -1 | cut -c1-90)"
        echo "before:"
        sed -n "$((n > 400 ? n - 400 : 1)),${n}p" "$f" \
            | grep -avE '^Stats|^Sent|^Receive|^[[:space:]]|Dumping|^queue|^gcode state|^\[|^Loaded|^webhooks|^Write|^clocksync|Timer too close|^Transition|^MCU .* shutdown' \
            | tail -8 | cut -c1-140 | sed 's/^/    /'
    done
done
echo "================================================================"
echo "${found} event(s) in $(ls "${LOGS}"/klippy.log* 2>/dev/null | wc -l) log file(s)."
