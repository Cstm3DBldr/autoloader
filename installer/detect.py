#!/usr/bin/env python3
"""Look at the printer and pre-fill the setup menu with what is actually there.

Run by install.sh before menuconfig opens:

    python3 installer/detect.py --config-dir ~/printer_data/config \
                               --answers ~/printer_data/config/autoloader/.autoloader-config

Everything here exists to turn typing into confirming. A user installing this
for the first time does not know their CAN UUID, what their LED chains are
called, or whether they have `stealthburner_leds.cfg` -- but the printer does,
and it is sitting right there. Asking them to type what can be read is how
wrong answers get in.

Two rules:

  * Detection only ever sets a DEFAULT. Anything already answered is left
    alone, so a re-run never overwrites a deliberate choice.
  * A detection that fails is silent about the value and loud about the fact.
    Guessing here produces a config that looks right and does not work.
"""

import argparse
import glob
import os
import re
import subprocess
import sys

NL = chr(10)


# ── reading the user's existing config ───────────────────────────────────────


def config_text(config_dir):
    """Every .cfg under the config directory, as (path, text) pairs.

    Klipper configs are a tree of includes; rather than resolve them, read the
    lot. A section defined in a file nobody includes still matters here --
    knowing it exists is what stops us proposing a colliding name.
    """
    out = []
    for path in glob.glob(os.path.join(config_dir, "**", "*.cfg"), recursive=True):
        if ".bak" in path or os.sep + "autoloader" + os.sep in path:
            continue
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                out.append((path, f.read()))
        except OSError:
            continue
    return out


def detect_extruders(files):
    """Return (prefix, count) from [extruder] / [extruderN] sections."""
    nums = set()
    prefix = None
    for _path, text in files:
        for m in re.finditer(r"^\[([a-zA-Z_]+?)(\d*)\]\s*$", text, re.M):
            name, num = m.group(1), m.group(2)
            if name != "extruder":
                continue
            prefix = "extruder"
            nums.add(int(num) if num else 0)
    if not nums:
        return None, None
    return prefix, max(nums) + 1


def detect_toolchanger(files):
    """(present, tool_count)."""
    present = False
    tools = set()
    for _path, text in files:
        if re.search(r"^\[toolchanger\]", text, re.M):
            present = True
        for m in re.finditer(r"^\[tool\s+\S+\]", text, re.M):
            present = True
        for m in re.finditer(r"^\s*tool_number\s*:\s*(\d+)", text, re.M):
            tools.add(int(m.group(1)))
    return present, (max(tools) + 1 if tools else None)


def detect_led_chains(files):
    """Every LED object name, plus a (prefix, suffix) if they are numbered."""
    names = []
    for _path, text in files:
        for m in re.finditer(
            r"^\[(?:neopixel|dotstar|led|pca9533|pca9632)\s+(\S+?)\]\s*$", text, re.M
        ):
            names.append(m.group(1))
    names = sorted(set(names))

    # Look for a family like et0_leds..et5_leds: same text either side of a
    # digit, appearing at least twice.
    families = {}
    for n in names:
        m = re.match(r"^(.*?)(\d+)(.*)$", n)
        if m:
            families.setdefault((m.group(1), m.group(3)), []).append(n)
    best = None
    for (pre, suf), members in families.items():
        if len(members) >= 2 and (best is None or len(members) > len(best[2])):
            best = (pre, suf, members)
    return names, best


def detect_status_collision(files):
    """Files defining the STATUS_* macros our LED example also defines.

    Klipper uppercases macro aliases, so a lowercase `status_ready` in the
    stock stealthburner_leds.cfg and our `STATUS_READY` register the same
    command -- and the second one refuses to register, so the printer will not
    start. This is the one detection that can prevent a bricked boot.
    """
    ours = (
        "status_ready", "status_printing", "status_heating", "status_busy",
        "status_homing", "status_leveling", "status_meshing", "status_cleaning",
        "status_calibrating_z", "status_off",
    )
    hits = {}
    for path, text in files:
        found = set()
        for m in re.finditer(r"^\[gcode_macro\s+(\S+?)\]\s*$", text, re.M):
            if m.group(1).lower() in ours:
                found.add(m.group(1))
        if found:
            hits[path] = sorted(found)
    return hits


def detect_can_uuid(files, config_dir):
    """(uuids_found, note). Never guesses which one is ours.

    Checks the existing autoloader config FIRST. A CAN board already listed in
    printer.cfg does not answer a scan, so on a re-install the scan finds
    nothing and the config is the only reliable source. `files` deliberately
    excludes the autoloader directory -- that keeps the LED collision check
    from flagging our own macros -- so this reads it directly.
    """
    # Look in user.cfg BEFORE hardware.cfg. A user whose board was already
    # assigned had to type the UUID into user.cfg by hand, and only that file
    # holds it -- hardware.cfg still says CHANGE_ME. Reading it here means the
    # next regeneration bakes it into hardware.cfg, so the printer stops
    # depending on user.cfg surviving. Overwriting user.cfg at the installer
    # prompt used to take the only working UUID with it.
    for name in ("user.cfg", "hardware.cfg"):
        path = os.path.join(config_dir, "autoloader", name)
        if not os.path.exists(path):
            continue
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                for m in re.finditer(r"^\s*canbus_uuid\s*:\s*(\S+)",
                                     f.read(), re.M):
                    val = m.group(1).strip()
                    if re.fullmatch(r"[0-9a-fA-F]{6,}", val):
                        return [val], "from your existing %s" % name, False
        except OSError:
            pass

    # Then the most recent uninstall backup. Reinstalling after an uninstall is
    # exactly when the live config is gone and the scan cannot help, because a
    # board that is powered and configured does not answer one.
    backups = sorted(glob.glob(os.path.expanduser("~/autoloader-config-backup-*")))
    for b in reversed(backups):
        hw = os.path.join(b, "hardware.cfg")
        if not os.path.exists(hw):
            continue
        try:
            with open(hw, "r", encoding="utf-8", errors="replace") as f:
                m = re.search(r"^\s*canbus_uuid\s*:\s*([0-9a-fA-F]{6,})",
                              f.read(), re.M)
            if m:
                return [m.group(1)], "recovered from %s" % os.path.basename(b), False
        except OSError:
            pass

    script = os.path.expanduser("~/klipper/scripts/canbus_query.py")
    if not os.path.exists(script):
        return [], "canbus_query.py not found — is Klipper installed?", False

    # canbus_query imports python-can, which lives in Klipper's virtualenv and
    # NOT in system python3. Run under sys.executable and it dies with
    # ModuleNotFoundError every time -- which this code then reported as "no
    # nodes answered", indistinguishable from a real empty result. The scan had
    # never once worked.
    interp = None
    for cand in (os.path.expanduser("~/klippy-env/bin/python"),
                 os.path.expanduser("~/klippy-env/bin/python3")):
        if os.path.exists(cand):
            interp = cand
            break
    if interp is None:
        return [], ("Klipper's python environment (~/klippy-env) not found, so "
                    "the CAN scan cannot run"), False

    for iface in ("can0", "can1"):
        try:
            r = subprocess.run(
                [interp, script, iface],
                capture_output=True, text=True, timeout=25,
            )
        except Exception as e:
            return [], "CAN scan failed: %s" % e, False
        uuids = re.findall(r"canbus_uuid=([0-9a-f]+)", r.stdout)
        if uuids:
            return uuids, "found on %s" % iface, True
    return [], ("no unassigned CAN nodes answered. A board already listed in "
                "printer.cfg will not answer a scan, which is normal."), False


def detect_assigned_uuids(files):
    """{uuid: mcu name} for every board already named in the config.

    A scan only reports UNASSIGNED boards, so on a working printer it finds
    nothing. Listing what is already taken is the other half of the answer:
    it tells the user which UUIDs are not the one they are looking for.
    """
    out = {}
    for _path, text in files:
        section = None
        for line in text.split(NL):
            st = line.strip()
            m = re.match(r"^\[mcu\s*([^\]]*)\]$", st)
            if m:
                section = m.group(1).strip() or "mcu"
                continue
            if st.startswith("["):
                section = None
                continue
            m = re.match(r"^canbus_uuid\s*:\s*([0-9a-fA-F]{6,})", st)
            if m and section:
                out[m.group(1).lower()] = section
    return out


def write_uuid_menu(path, found, assigned):
    """Put the CAN picture into the menu itself, not just the terminal.

    Kconfig cannot express a list only known at run time, so this is generated
    and pulled in with `osource` -- optional, so a printer with nothing to show
    still parses.

    Two parts:

      * `comment` lines naming every UUID already spoken for. Comments render
        as visible rows in menuconfig, which a `help` block on MCU_UUID would
        not: a fragment can attach help to that symbol, but the attached node
        has no prompt, so it never appears under the cursor and `?` never
        reaches it.
      * a `choice` of boards a live scan found unclaimed -- only when there
        are any. A UUID read out of a config file is by definition already in
        use; offering it here would invite picking the board that is already
        configured.
    """
    if not found and not assigned:
        try:
            if os.path.exists(path):
                os.remove(path)
        except OSError:
            pass
        return False

    L = ["# Generated by installer/detect.py. Rewritten on every run, ignored",
         "# by git. Do not edit.", ""]

    if assigned:
        L.append('comment "---- CAN boards already in use on this printer ----"')
        for u, name in sorted(assigned.items(), key=lambda kv: kv[1])[:12]:
            L.append('comment "    %s  is  %s"' % (u, name))
        if not found:
            L.append('comment "    your autoloader is the one NOT listed above"')
        L.append("")

    if found:
        L.append("choice")
        L.append('    prompt "Which board is the autoloader?"')
        L.append("    help")
        L.append("      These answered a CAN scan, so they are powered and not")
        L.append("      yet claimed by any config -- one of them is your new")
        L.append("      autoloader board.")
        L.append("")
        for i, u in enumerate(found):
            L.append("config UUID_PICK_%d" % i)
            L.append('    bool "%s"' % u)
        L.append("config UUID_PICK_MANUAL")
        L.append('    bool "Type it in myself"')
        L.append("endchoice")
        L.append("")
        for i, u in enumerate(found):
            L.append("if UUID_PICK_%d" % i)
            L.append("config MCU_UUID")
            L.append('    default "%s"' % u)
            L.append("endif")
        L.append("")

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline=NL) as f:
        f.write(NL.join(L))
    return True


# ── writing defaults into the answer file ────────────────────────────────────


def load_answers(path):
    vals = {}
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                m = re.match(r"^CONFIG_([A-Z0-9_]+)=(.*)$", line.strip())
                if m:
                    vals[m.group(1)] = m.group(2)
                m = re.match(r"^# CONFIG_([A-Z0-9_]+) is not set", line.strip())
                if m:
                    vals[m.group(1)] = "n"
    return vals


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config-dir", default=os.path.expanduser("~/printer_data/config"))
    ap.add_argument("--answers", required=True)
    ap.add_argument("--kconfig", default="installer/Kconfig")
    ap.add_argument("--check", action="store_true",
                    help="verify the answers are safe to install; exit 1 if not")
    args = ap.parse_args()

    if not os.path.isdir(args.config_dir):
        print("  ! %s does not exist — skipping detection." % args.config_dir)
        return 0

    files = config_text(args.config_dir)
    existing = load_answers(args.answers)
    proposed = {}

    if args.check:
        # Run AFTER the menu. Warning during detection is not enough: the
        # option is still selectable, and the cost of selecting it is a printer
        # that will not boot. This is the stop.
        collisions = detect_status_collision(files)
        if existing.get("LEDS_FULL") == "y" and collisions:
            print("")
            print("STOP — that combination will prevent Klipper from starting.")
            print("")
            print("You chose the FULL LED option, but these files already define")
            print("the same STATUS_* macros:")
            for path, macros in collisions.items():
                print("    %s" % path.replace(os.path.expanduser("~"), "~"))
                print("      %s" % ", ".join(macros))
            print("")
            print("Klipper uppercases macro names, so both would register the")
            print("same command and the second raises:")
            print('    "gcode command STATUS_READY already registered"')
            print("")
            print("Re-run the installer and choose either:")
            print("  * Filament colour on the logo only — keeps your LEDs, or")
            print("  * Full, AFTER removing the include for the file above.")
            print("")
            print("Nothing was changed.")
            return 1
        if existing.get("LEDS_FULL") == "y" or existing.get("LEDS_FILAMENT_ONLY") == "y":
            names, family = detect_led_chains(files)
            if not family:
                print("  ! You picked LEDs, but no per-toolhead LED chain family was")
                print("    found (%s)." % (", ".join(names) if names else "no LED objects at all"))
                print("    Per-toolhead filament colour needs one chain per tool.")
                print("    Install continues; the LEDs will not light until the chain")
                print("    names in leds/leds.cfg match your hardware.")
        return 0

    print("Looking at your printer...")
    print("")

    # ── toolheads ────────────────────────────────────────────────────────────
    prefix, ecount = detect_extruders(files)
    tc_present, tc_count = detect_toolchanger(files)
    count = tc_count or ecount
    if count:
        print("  toolheads      %d  (from %s)"
              % (count, "tool_number entries" if tc_count else "[extruder] sections"))
        proposed["NUM_PATHS"] = str(count)
    else:
        print("  toolheads      could not tell — you will be asked")
    if prefix:
        proposed["EXTRUDER_PREFIX"] = '"%s"' % prefix

    # ── toolchanger ──────────────────────────────────────────────────────────
    print("  toolchanger    %s" % ("yes" if tc_present else "not found"))
    proposed["HAS_TOOLCHANGER"] = "y" if tc_present else "n"

    # ── CAN ──────────────────────────────────────────────────────────────────
    uuids, note, from_scan = detect_can_uuid(files, args.config_dir)
    assigned = detect_assigned_uuids(files)
    # Only a live scan proves a board is unclaimed. A UUID read out of a config
    # file is by definition already spoken for -- offering it as "pick your new
    # board" invited choosing the one that is already configured.
    scanned = [u for u in uuids if u.lower() not in assigned] if from_scan else []

    if len(uuids) == 1:
        print("  CAN UUID       %s  (%s)" % (uuids[0], note))
        proposed["MCU_UUID"] = '"%s"' % uuids[0]
    elif len(uuids) > 1:
        print("  CAN UUID       %d boards answered — pick yours in the menu:" % len(uuids))
        for u in uuids:
            print("                   %s" % u)
    else:
        print("  CAN UUID       %s" % note)

    if assigned:
        print("                 already in use on this printer:")
        for u, name in sorted(assigned.items()):
            print("                   %s  ->  %s" % (u, name))

    # Only offer a pick-list for boards nothing has claimed. Listing one that
    # is already an extruder would invite the user to point the autoloader at
    # a toolhead.
    menu = os.path.join(os.path.dirname(os.path.abspath(args.kconfig)),
                        "generated", "Kconfig.uuid")
    if write_uuid_menu(menu, scanned, assigned):
        if scanned:
            print("                 -> the menu will offer these as a choice.")
        else:
            print("                 -> the menu lists these too, so you can spot yours.")

    # ── LEDs ─────────────────────────────────────────────────────────────────
    names, family = detect_led_chains(files)
    if not names:
        print("  LED chains     none found — LEDs will stay off")
        proposed["LEDS_NONE"] = "y"
    else:
        print("  LED chains     %s" % ", ".join(names[:8]) + (" ..." if len(names) > 8 else ""))
        if family:
            pre, suf, members = family
            print("                 one per toolhead: %s (%d found)"
                  % ("%s<N>%s" % (pre, suf), len(members)))
            proposed["LED_CHAIN_PREFIX"] = '"%s"' % pre
            proposed["LED_CHAIN_SUFFIX"] = '"%s"' % suf
        else:
            print("                 no per-toolhead family — per-path colour is")
            print("                 not possible with a single shared chain")

    collisions = detect_status_collision(files)
    if collisions:
        print("")
        print("  ! You already have STATUS_* LED macros:")
        for path, macros in collisions.items():
            print("      %s" % path.replace(os.path.expanduser("~"), "~"))
            print("        %s" % ", ".join(macros[:6]) + (" ..." if len(macros) > 6 else ""))
        print("")
        print("    Klipper uppercases macro names, so these register the SAME")
        print("    commands as the autoloader's full LED option. Choosing 'Full'")
        print("    would stop your printer from starting.")
        print("    Choose 'Filament colour on the logo only' instead — it keeps")
        print("    the LEDs you already have.")
        proposed["SA_STATUS_MACROS_EXIST"] = "y"

    # ── write ────────────────────────────────────────────────────────────────
    # A placeholder is not an answer. CHANGE_ME sitting in the answers file
    # from a previous run was treated as "already decided", so a UUID detection
    # had just successfully found was thrown away and the menu still opened on
    # CHANGE_ME.
    PLACEHOLDERS = ('"CHANGE_ME"', 'CHANGE_ME', '""', '')
    new = [k for k in proposed
           if k not in existing or existing.get(k) in PLACEHOLDERS]
    if not new:
        print("")
        print("  (nothing new to fill in — your previous answers are kept)")
        return 0

    # Rewrite rather than append when replacing a placeholder, or the file ends
    # up with the key twice and the stale one may win.
    if os.path.exists(args.answers):
        keep = []
        with open(args.answers, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                k = re.match(r"^CONFIG_([A-Z0-9_]+)=", line.strip())
                if k and k.group(1) in new:
                    continue
                keep.append(line.rstrip(NL))
        with open(args.answers, "w", encoding="utf-8", newline=NL) as f:
            f.write(NL.join(keep) + NL)

    with open(args.answers, "a", encoding="utf-8", newline=NL) as f:
        f.write(NL + "# Filled in by installer/detect.py — change any of these in the menu." + NL)
        for k in new:
            f.write("CONFIG_%s=%s%s" % (k, proposed[k], NL))
    print("")
    print("  Pre-filled %d answer(s). Everything is still editable in the menu." % len(new))
    return 0


if __name__ == "__main__":
    sys.exit(main())
