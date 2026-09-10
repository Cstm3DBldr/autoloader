#!/usr/bin/env python3
"""Fail when two places that describe the same thing disagree.

Every place that restates something becomes a place that goes stale. This
project has been bitten by that four times:

  - the calibration step list lived in _GUIDE, a KlipperScreen wizard, a
    Mainsail wizard and CLAUDE.md. When the chain grew to eleven steps both
    wizards went on showing nine, one of them clamping the extras onto the
    last page it knew.
  - the macros panel kept a fifth copy, listing five of the eleven.
  - CLAUDE.md's Calibration Sequence never mentioned SA_CALIBRATE_ENCODER_SPEED
    at all, and carried the encoder steps in an order the code had already
    changed.
  - the command reference was missing four registered commands.

Each was found by hand, months apart, by someone counting. A rule saying "keep
them in step" is the kind of instruction people skip -- so this counts instead,
and exits non-zero when the copies disagree.

    python3 scripts/check_drift.py

No arguments, no dependencies, no printer. Runs from anywhere.
"""

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Poll and response callbacks are machinery, not operator commands, and
# documenting them would invite someone to run them by hand mid-calibration.
INTERNAL_COMMANDS = {"SA_ENCSPEED_STEP", "SA_ENDSTOP_POLL", "SA_SENSOR_POLL"}

failures = []


def read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


def report(name, problems, detail=""):
    if problems:
        failures.append(name)
        print("  FAIL  %s" % name)
        for p in problems:
            print("          %s" % p)
        if detail:
            print("          -> %s" % detail)
    else:
        print("  ok    %s" % name)


# ── 1. every registered command appears in CLAUDE.md's reference ─────────
def check_commands():
    code = read("klipper", "extras", "autoloader.py")
    doc = read("CLAUDE.md")
    registered = set(re.findall(r"'(SA_[A-Z_]+)'", code)) - INTERNAL_COMMANDS
    documented = set(re.findall(r"^\| `(SA_[A-Z_]+)", doc, re.M))
    problems = []
    for c in sorted(registered - documented):
        problems.append("registered but undocumented: %s" % c)
    for c in sorted(documented - registered):
        problems.append("documented but not registered: %s" % c)
    report("command reference matches register_command", problems,
           "add it to the GCode Commands table in CLAUDE.md, or delete the row")


# ── 2. the guide's step numbering agrees with itself ─────────────────────
def check_guide_numbering():
    src = read("klipper", "extras", "sa_calibration.py")
    problems = []

    total = re.search(r"_STEP_TOTAL\s*=\s*(\d+)", src)
    names = re.search(r"_STEP_NAMES\s*=\s*\{(.*?)\n    \}", src, re.S)
    by_cmd = re.search(r"_STEP_BY_COMMAND\s*=\s*\((.*?)\n    \)", src, re.S)
    by_state = re.search(r"_STEP_BY_STATE\s*=\s*\((.*?)\n    \)", src, re.S)
    if not all((total, names, by_cmd, by_state)):
        report("guide step numbering is self-consistent",
               ["could not locate _STEP_TOTAL / _STEP_NAMES / the lookup tables"])
        return

    total_n = int(total.group(1))
    name_ns = sorted(int(n) for n in re.findall(r"^\s*(\d+):", names.group(1), re.M))
    cmd_ns = [int(n) for n in re.findall(r'\("[A-Z_]+",\s*(\d+)\)', by_cmd.group(1))]
    state_ns = [int(n) for n in re.findall(r'\("[a-z_]+",\s*(\d+)\)', by_state.group(1))]

    # The pages themselves: one dict per step in the _GUIDE list.
    pages = len(re.findall(r"\n        \{'title': ", src))

    if pages != total_n:
        problems.append("_GUIDE has %d pages but _STEP_TOTAL is %d" % (pages, total_n))
    if name_ns != list(range(1, total_n + 1)):
        problems.append("_STEP_NAMES keys are %s, expected 1..%d" % (name_ns, total_n))
    for label, ns in (("_STEP_BY_COMMAND", cmd_ns), ("_STEP_BY_STATE", state_ns)):
        bad = [n for n in ns if not 1 <= n <= total_n]
        if bad:
            problems.append("%s points at steps outside 1..%d: %s" % (label, total_n, bad))
        if len(set(ns)) != len(ns):
            dupes = sorted({n for n in ns if ns.count(n) > 1})
            problems.append("%s maps two entries to the same step: %s" % (label, dupes))

    # Longest-prefix ordering: a shorter prefix listed first swallows the
    # longer one. SA_CALIBRATE_ENCODER_SPEED matching the SA_CALIBRATE_ENCODER
    # row is the live example, and it reports the wrong step silently.
    prefixes = re.findall(r'\("([A-Z_]+)",\s*\d+\)', by_cmd.group(1))
    for i, p in enumerate(prefixes):
        for q in prefixes[i + 1:]:
            if q.startswith(p):
                problems.append(
                    "%s is listed before %s, so %s can never match" % (p, q, q))
    report("guide step numbering is self-consistent", problems,
           "_GUIDE, _STEP_TOTAL, _STEP_NAMES and both lookup tables must agree")


# ── 3. parameters.cfg and the code read the same settings ───────────────
def check_parameters():
    cfg = read("autoloader", "parameters.cfg")
    code = read("klipper", "extras", "autoloader.py")

    declared = set()
    for line in cfg.splitlines():
        line = line.split("#", 1)[0].strip()
        m = re.match(r"^([a-z_][a-z_0-9]*)\s*:", line)
        if m:
            declared.add(m.group(1))

    # \s* before the paren: the code aligns these calls, so getint  ('x') is
    # common and a tighter pattern silently misses them.
    reads = set(re.findall(r"config\.get[a-z_]*\s*\(\s*'([a-z_0-9%]+)'", code))
    # Per-path settings are read as a format string and written out per path.
    families = {r[:-3] for r in reads if r.endswith("_%d")}
    plain = {r for r in reads if not r.endswith("_%d")}
    # Whole families are consumed by prefix -- get_prefix_options('tip_form_')
    # takes every per-material variant without naming one. Honour any such
    # call rather than special-casing the families that exist today.
    prefixes = tuple(re.findall(r"get_prefix_options\(\s*'([a-z_0-9]+)'", code))

    def is_read(name):
        if name in plain:
            return True
        if any(name.startswith(pre) for pre in prefixes):
            return True
        base = re.sub(r"_\d+$", "", name)
        return base in families

    problems = []
    for name in sorted(declared):
        if not is_read(name):
            problems.append("declared in parameters.cfg but never read: %s" % name)
    report("parameters.cfg settings are all read by the code", problems,
           "delete the line, or wire it up -- a setting nothing reads is a "
           "promise the machine does not keep")


# ── 4. every Klipper extra is installed and documented ──────────────────
def check_extras():
    import glob

    on_disk = {os.path.basename(p)
               for p in glob.glob(os.path.join(ROOT, "klipper", "extras", "*.py"))}
    installed = set()
    for line in read("install.sh").splitlines():
        if "for f in" in line and ".py" in line:
            installed |= set(re.findall(r"([a-z_]+\.py)", line))
    doc = read("CLAUDE.md")

    problems = []
    for f in sorted(on_disk - installed):
        problems.append("in klipper/extras/ but install.sh never symlinks it: %s" % f)
    for f in sorted(installed - on_disk):
        problems.append("install.sh symlinks a file that does not exist: %s" % f)
    for f in sorted(on_disk):
        if f not in doc:
            problems.append("in klipper/extras/ but CLAUDE.md never mentions it: %s" % f)
    report("Klipper extras are installed and documented", problems,
           "add it to install.sh's symlink loop, the Project File Structure "
           "table and the symlink list -- a whole module missing from the map "
           "is how sa_led_animator.py went 504 lines unmentioned")


# ── 5. every installer question changes something ───────────────────────
def check_kconfig():
    import glob

    opts = set()
    kconfig_text = ""
    for path in glob.glob(os.path.join(ROOT, "installer", "**", "*"), recursive=True):
        if os.path.isfile(path) and "Kconfig" in os.path.basename(path):
            body = open(path, encoding="utf-8", errors="replace").read()
            kconfig_text += body
            opts |= set(re.findall(r"^config ([A-Z_0-9]+)", body, re.M))

    consumers = ""
    for rel in ("installer/generate.py", "installer/detect.py", "install.sh"):
        consumers += read(rel)
    for path in glob.glob(os.path.join(ROOT, "installer", "templates", "*")):
        if os.path.isfile(path):
            consumers += open(path, encoding="utf-8", errors="replace").read()

    problems = []
    for o in sorted(opts):
        # Its own declaration does not count. Anything else does -- a "depends
        # on" in Kconfig is real use, and so is a template or generate.py.
        internal = len(re.findall(r"\b%s\b" % o, kconfig_text)) - 1
        external = o in consumers or ("CONFIG_" + o) in consumers
        if internal <= 0 and not external:
            problems.append("asked but never acted on: %s" % o)
    report("every installer question changes something", problems,
           "the menu asks, the user answers, and nothing reads it -- wire it "
           "up in generate.py or install.sh, or drop the question")


print("Drift checks -- places that describe the same thing twice\n")
check_commands()
check_guide_numbering()
check_parameters()
check_extras()
check_kconfig()

print()
if failures:
    print("DRIFT: %d check(s) failed -- %s" % (len(failures), ", ".join(failures)))
    sys.exit(1)
print("No drift.")
