#!/usr/bin/env python3
"""Catch `owner.<attr>` references that Autoloader never defines.

Three times now a helper module has reached for an attribute the main class
does not set. Each time the result was identical: AttributeError raised out of
a gcode handler, which Klipper treats as fatal, so the printer SHUT DOWN
mid-command. And each time it lay dormant until someone happened to run that
one command --

    _selector_homed         any calibration on a fresh Klipper
    _clear_material_profile every state-monitor tick, swallowed by a broad except
    selector_cal_current,   SA_CALIBRATE_SELECTOR
    selector_end_offset,
    path_width

-- because nothing loads these modules until the command that needs them runs.
A syntax check does not see it. Klipper starting cleanly does not see it. Only
running every command sees it, and nobody runs every command.

This does. It is a static scan, so it costs nothing and needs no printer.

Run directly, or via scripts/verify.sh:

    python3 scripts/check_owner_attrs.py

Exits non-zero if anything is missing, listing file and line.
"""

import ast
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
EXTRAS = os.path.join(os.path.dirname(HERE), "klipper", "extras")
MAIN = "autoloader.py"
# Modules that hold a reference to the Autoloader instance as `owner`.
HELPERS = ("sa_motion.py", "sa_sequences.py", "sa_calibration.py")


def defined_on_main(path):
    """Every attribute Autoloader assigns to self, plus its methods."""
    src = open(path, "r", encoding="utf-8", errors="replace").read()
    names = set(re.findall(r"self\.([A-Za-z_][A-Za-z0-9_]*)\s*=", src))
    names |= set(re.findall(r"self\.([A-Za-z_][A-Za-z0-9_]*)\s*[+\-*/]?=", src))

    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "Autoloader":
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    names.add(item.name)
                # Class-level constants: TIP_FORM_BASES, STATE_EMPTY, ...
                if isinstance(item, ast.Assign):
                    for t in item.targets:
                        if isinstance(t, ast.Name):
                            names.add(t.id)
    return names


def referenced_in(path):
    """[(attr, lineno)] for every `owner.<attr>` in a helper."""
    out = []
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for n, line in enumerate(f, 1):
            # Skip comments and docstring prose; a mention is not a reference.
            code = line.split("#", 1)[0]
            for m in re.finditer(r"\bowner\.([A-Za-z_][A-Za-z0-9_]*)", code):
                out.append((m.group(1), n))
    return out


def main():
    main_path = os.path.join(EXTRAS, MAIN)
    if not os.path.exists(main_path):
        print("ERROR: %s not found" % main_path, file=sys.stderr)
        return 2

    known = defined_on_main(main_path)
    # Inherited from object / set by Klipper on every printer object.
    known |= {"printer", "reactor", "gcode", "name", "config"}

    missing = []
    for helper in HELPERS:
        hp = os.path.join(EXTRAS, helper)
        if not os.path.exists(hp):
            continue
        seen = set()
        for attr, line in referenced_in(hp):
            if attr in known or (helper, attr) in seen:
                continue
            seen.add((helper, attr))
            missing.append((helper, line, attr))

    if not missing:
        print("  owner attributes: all %d references resolve" % len(known))
        return 0

    print("  MISSING -- these would raise AttributeError and shut Klipper down:")
    for helper, line, attr in missing:
        print("    %s:%d  owner.%s" % (helper, line, attr))
    print("")
    print("  Define each in Autoloader.__init__ (config.getfloat/getint/get),")
    print("  or correct the name in the helper.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
