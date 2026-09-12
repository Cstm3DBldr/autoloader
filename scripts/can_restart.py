#!/usr/bin/env python3
"""Is it safe to restart Klipper right now?

Exit 0 = safe. Exit 1 = refuse, with the reason on stdout.

TWO reasons to refuse, both learned the hard way on 2026-09-12:

  * A heater is on, or a nozzle is still hot. A toolhead MCU shuts ITSELF
    down when the host disappears while one of its heaters is active --
    the EBB36 doing its job, not a fault. Afterwards every connect says
    "Can not update MCU 'etN' config as it is shutdown" and only
    FIRMWARE_RESTART clears it. This happened twice in one day, to et4 and
    then et0, both times because a restart followed a load that left a
    nozzle hot.

  * Something is running. Restarting under a live sequence loses whatever
    prompt the operator was looking at -- which is what happened during a
    T5 toolchange.

Usage:  python3 can_restart.py [host]        (default localhost)
"""
import json
import sys
import urllib.request

HOST = sys.argv[1] if len(sys.argv) > 1 else "localhost"
BASE = "http://%s:7125" % HOST

# A nozzle above this is hot enough that the MCU's watchdog cares, even with
# the target already at zero -- a heater that was just switched off is still
# a heater the firmware is managing.
HOT_C = 60.0


def query(objects):
    url = "%s/printer/objects/query?%s" % (
        BASE, "&".join(o.replace(" ", "%20") for o in objects))
    with urllib.request.urlopen(url, timeout=5) as r:
        return json.load(r)["result"]["status"]


def main():
    try:
        st = query(["idle_timeout", "heaters"])
    except Exception as e:
        print("cannot reach Moonraker at %s (%s)" % (BASE, e))
        return 1

    state = (st.get("idle_timeout") or {}).get("state", "unknown")
    if state not in ("Ready", "Idle"):
        print("idle_timeout is '%s' - something is running" % state)
        return 1

    names = (st.get("heaters") or {}).get("available_heaters") or []
    if names:
        try:
            h = query(names)
        except Exception:
            h = {}
        hot = []
        for n in names:
            d = h.get(n) or {}
            t = d.get("temperature") or 0.0
            if (d.get("target") or 0.0) > 0.0:
                hot.append("%s target %.0fC" % (n, d["target"]))
            elif t > HOT_C:
                hot.append("%s at %.0fC" % (n, t))
        if hot:
            print("a heater is active or still hot - " + ", ".join(hot))
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
