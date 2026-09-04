#!/usr/bin/env python3
"""Turn a menuconfig .config into the autoloader's Klipper config files.

Run by install.sh; also runnable by hand:

    python3 installer/generate.py --config .config --out ~/printer_data/config/autoloader

Two things matter here beyond substitution.

**Existing values win.** Re-running the installer regenerates each file from
its template -- so new options and improved comments arrive -- and then puts
back every value the user already had. Without that, a second install would
silently discard tuning, which is the failure mode this whole design exists to
avoid. Anything the template no longer defines is reported rather than dropped
in silence.

**No dependencies.** Klipper ships kconfiglib (it is what `make menuconfig`
uses) so reading .config is free, but jinja2 lives only in klippy-env, not in
system python3. The template syntax below is therefore deliberately tiny:
{{VAR}}, {% for path %}, {% if COND %} / {% ifnot COND %}. If it ever needs
more than that, the templates are doing too much.
"""

import argparse
import os
import re
import sys
import time

NL = chr(10)

# ── reading .config ──────────────────────────────────────────────────────────


def load_kconfig(kconfig_file, config_file):
    """Read .config through Klipper's own vendored kconfiglib."""
    for candidate in (
        os.path.expanduser("~/klipper/lib/kconfiglib"),
        "/home/pi/klipper/lib/kconfiglib",
    ):
        if os.path.isdir(candidate):
            sys.path.insert(0, candidate)
            break
    try:
        import kconfiglib
    except ImportError:
        sys.exit(
            "ERROR: could not find kconfiglib.\n"
            "       It ships with Klipper at ~/klipper/lib/kconfiglib -- the same\n"
            "       copy `make menuconfig` uses. Is Klipper installed?"
        )

    # `source "installer/boards/Kconfig"` inside our Kconfig is resolved
    # relative to $srctree, falling back to the working directory. Without this
    # the installer only works when run from the repo root, which is exactly
    # what a user pasting an absolute path will not do.
    os.environ.setdefault(
        "srctree",
        os.path.dirname(os.path.dirname(os.path.abspath(kconfig_file))))

    kc = kconfiglib.Kconfig(kconfig_file, warn=False)
    if os.path.exists(config_file):
        kc.load_config(config_file)
    return {name: sym.str_value for name, sym in kc.syms.items()}


def truthy(v):
    return str(v).strip().lower() in ("y", "yes", "true", "1")


# ── context ──────────────────────────────────────────────────────────────────


def build_context(k):
    """Flatten .config into the values templates reference."""
    n = int(k.get("NUM_PATHS") or 6)
    prefix = k.get("EXTRUDER_PREFIX") or "extruder"

    encoder_pins = [p.strip() for p in (k.get("PINS_ENCODER") or "").split(",") if p.strip()]
    entry_pins = [p.strip() for p in (k.get("PINS_ENTRY") or "").split(",") if p.strip()]

    ctx = dict(k)
    ctx["NUM_PATHS"] = str(n)

    # Klipper names the first extruder "extruder", not "extruder0".
    def extruder(i):
        return prefix if i == 0 else "%s%d" % (prefix, i)

    paths = []
    for i in range(n):
        paths.append(
            {
                "N": str(i),
                "ENCODER_PIN": encoder_pins[i] if i < len(encoder_pins) else "CHANGE_ME",
                "ENTRY_PIN": entry_pins[i] if i < len(entry_pins) else "CHANGE_ME",
                "EXTRUDER_NAME": extruder(i),
                # Toolhead boards are per-tool; this project's build wires the
                # two filament sensors to the same pins on every EBB.
                "TOOLHEAD_MCU": "et%d" % i,
            }
        )
    ctx["_paths"] = paths

    if len(encoder_pins) < n or len(entry_pins) < n:
        ctx["_short_pins"] = True
    return ctx


# ── the tiny template engine ─────────────────────────────────────────────────

_FOR = re.compile(r"\{%\s*for path\s*%\}\n?(.*?)\{%\s*endfor\s*%\}\n?", re.S)
_IF = re.compile(r"\{%\s*(if|ifnot)\s+([A-Z0-9_]+)\s*%\}\n?(.*?)\{%\s*endif\s*%\}\n?", re.S)
_VAR = re.compile(r"\{\{\s*([A-Z0-9_]+)\s*\}\}")


def _subst(text, scope):
    def one(m):
        key = m.group(1)
        if key not in scope:
            raise KeyError("template references unknown value {{%s}}" % key)
        return str(scope[key])

    return _VAR.sub(one, text)


def render(text, ctx):
    # Conditionals first, so a false branch's loops and vars never render.
    def cond(m):
        kind, name, body = m.group(1), m.group(2), m.group(3)
        on = truthy(ctx.get(name, ""))
        keep = on if kind == "if" else not on
        return render(body, ctx) if keep else ""

    while _IF.search(text):
        text = _IF.sub(cond, text, count=1)

    def loop(m):
        body = m.group(1)
        out = []
        for p in ctx["_paths"]:
            scope = dict(ctx)
            scope.update(p)
            out.append(_subst(body, scope))
        return "".join(out)

    text = _FOR.sub(loop, text)
    return fix_alias_commas(_subst(text, ctx))


def fix_alias_commas(text):
    """Strip the trailing comma from the last alias in a [board_pins] block.

    Klipper parses `aliases:` by splitting on commas, so a trailing one leaves
    an empty entry and the section fails to load. The templates emit a comma
    after every alias because a `{% for path %}` body cannot know it is
    rendering the last iteration -- and which loop ends the block depends on
    the template, so a per-path "last" flag would be wrong too. Fixing it here
    keeps the templates readable and puts the Klipper-specific rule in one
    place.
    """
    lines = text.split(NL)
    in_aliases = False
    last_alias = None
    for i, line in enumerate(lines):
        if re.match(r"^\s*aliases\s*:", line):
            in_aliases = True
            last_alias = None
            continue
        if in_aliases:
            stripped = line.strip()
            if line[:1] in (" ", "	") and stripped and not stripped.startswith("#"):
                last_alias = i
            elif stripped and line[:1] not in (" ", "	"):
                # A new top-level line ends the block.
                if last_alias is not None:
                    lines[last_alias] = lines[last_alias].rstrip().rstrip(",")
                in_aliases = False
    if in_aliases and last_alias is not None:
        lines[last_alias] = lines[last_alias].rstrip().rstrip(",")
    return NL.join(lines)


# ── carrying existing values forward ─────────────────────────────────────────

_SECTION = re.compile(r"^\[([^\]]+)\]\s*$")
# A setting, not a continuation: no leading whitespace, and a value on the line.
_SETTING = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.*?)\s*$")
# Klipper parses with inline_comment_prefixes=(';', '#'), so a value ends at
# whitespace followed by one of those.
_INLINE_COMMENT = re.compile(r"\s+[#;].*$")


def value_only(v):
    """The value with any inline comment removed.

    Without this the captured "value" of

        feed_speed     : 50    # mm/s -- drive motor speed

    is "50    # mm/s -- drive motor speed", and re-applying it appends the
    template's own comment on top, producing a line with the comment twice.
    Most of parameters.cfg carries inline comments, so this corrupted almost
    every tuned value -- it stayed hidden because the values tested first
    (bowden lengths, selector positions) happen to have none.
    """
    return _INLINE_COMMENT.sub("", v).strip()


def parse_settings(path):
    """{(section, key): value} for single-line settings only.

    Multi-line values -- `gcode:`, `aliases:` and friends -- are deliberately
    skipped. Carrying half of a continuation block forward would produce a file
    that parses but does the wrong thing, which is worse than losing an edit.
    """
    out = {}
    if not os.path.exists(path):
        return out
    section = None
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            if line[:1] in (" ", "\t"):
                continue
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            m = _SECTION.match(stripped)
            if m:
                section = m.group(1)
                continue
            m = _SETTING.match(line.rstrip("\n"))
            if m and section:
                key, val = m.group(1), value_only(m.group(2))
                if val == "":  # start of a multi-line block, or comment-only
                    continue
                out[(section, key)] = val
    return out


def reapply(rendered, existing):
    """Put the user's values back into freshly rendered text.

    Returns (text, changed, dropped). `dropped` is everything the user had that
    the new template no longer defines -- reported, never silently discarded.
    """
    if not existing:
        return rendered, [], []

    changed = []
    seen = set()
    out = []
    section = None
    for line in rendered.split("\n"):
        stripped = line.strip()
        m = _SECTION.match(stripped)
        if m:
            section = m.group(1)
            out.append(line)
            continue
        if line[:1] in (" ", "\t") or not stripped or stripped.startswith("#"):
            out.append(line)
            continue
        m = _SETTING.match(line)
        if m and section:
            key, new_val = m.group(1), value_only(m.group(2))
            seen.add((section, key))
            old_val = existing.get((section, key))
            if old_val is not None and old_val != new_val and new_val != "":
                # Replace ONLY the value, leaving the template's own spelling
                # of the line intact -- key, the alignment either side of the
                # colon, and any trailing comment. Rebuilding the line as
                # "key: value" reformatted this project's aligned "key : value"
                # style on every regeneration, which turned a no-op re-install
                # into a diff across the whole file.
                m2 = re.match(
                    r"^([A-Za-z_][A-Za-z0-9_]*\s*:\s*)(.*?)(\s*(?:#.*)?)$", line)
                if m2:
                    out.append(m2.group(1) + old_val + m2.group(3))
                    changed.append((section, key, new_val, old_val))
                    continue
        out.append(line)

    dropped = [(s, k, v) for (s, k), v in existing.items() if (s, k) not in seen]
    return "\n".join(out), changed, dropped


# ── main ─────────────────────────────────────────────────────────────────────

TEMPLATES = [
    ("pin_aliases.cfg", "pin_aliases.cfg"),
    ("hardware.cfg", "hardware.cfg"),
    ("parameters.cfg", "parameters.cfg"),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kconfig", default="installer/Kconfig")
    ap.add_argument("--config", default=".config")
    ap.add_argument("--templates", default="installer/templates")
    ap.add_argument("--out", required=True, help="destination config directory")
    ap.add_argument("--mode", choices=("refresh", "replace"), default="refresh",
                    help="refresh keeps your existing values (default); "
                         "replace writes pristine files from the template")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    k = load_kconfig(args.kconfig, args.config)
    ctx = build_context(k)

    if ctx.get("_short_pins"):
        print("  ! This board defines fewer pins than you have paths.")
        print("    The extra paths get CHANGE_ME and will not start until edited.")

    os.makedirs(args.out, exist_ok=True)
    total_changed = 0
    would_change = []

    for tpl_name, out_name in TEMPLATES:
        tpl_path = os.path.join(args.templates, tpl_name)
        if not os.path.exists(tpl_path):
            sys.exit("ERROR: missing template %s" % tpl_path)
        with open(tpl_path, "r", encoding="utf-8") as f:
            try:
                text = render(f.read(), ctx)
            except KeyError as e:
                sys.exit("ERROR in %s: %s" % (tpl_name, e))

        dest = os.path.join(args.out, out_name)
        changed, dropped = [], []
        if args.mode == "refresh":
            text, changed, dropped = reapply(text, parse_settings(dest))

        if changed:
            total_changed += len(changed)
            print("  %s — kept %d of your existing values:" % (out_name, len(changed)))
            for sec, key, new, old in changed[:12]:
                print("      %s: %s  (template default was %s)" % (key, old, new))
            if len(changed) > 12:
                print("      ... and %d more" % (len(changed) - 12))
        if dropped:
            print("  %s — these settings of yours are no longer used:" % out_name)
            for sec, key, val in dropped:
                print("      [%s] %s: %s" % (sec, key, val))

        # Identical output is not worth a backup or a write. Updates run this
        # every time and most change nothing; backing up regardless would bury
        # the config directory in .bak files and make the one backup that
        # matters impossible to find.
        current = None
        if os.path.exists(dest):
            with open(dest, "r", encoding="utf-8", errors="replace") as f:
                current = f.read()

        if current == text:
            print("  %s unchanged" % out_name)
            continue

        would_change.append(out_name)
        if args.dry_run:
            print("  %s WOULD CHANGE" % out_name)
            continue

        if current is not None:
            bak = "%s.bak.%d" % (dest, int(time.time()))
            os.replace(dest, bak)
            print("  wrote %s  (previous kept as %s)"
                  % (dest, os.path.basename(bak)))
        else:
            print("  wrote %s" % dest)
        with open(dest, "w", encoding="utf-8", newline=NL) as f:
            f.write(text)

    if args.mode == "refresh" and total_changed == 0:
        print("  (no existing values to carry forward)")

    # Non-zero when the on-disk config no longer matches what the answers and
    # templates say it should be -- a hand edit to a generated file, or an
    # update whose templates moved on and was never applied. verify.sh uses it.
    if args.dry_run and would_change:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
