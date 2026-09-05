#!/usr/bin/env bash
#
# Give KlipperScreen an add-on hook, so code can run at startup.
#
# WHY THIS EXISTS
#
# KlipperScreen hands printer status to the panel currently on screen and to
# nothing else:
#
#     def process_update(self, *args):
#         self.base_panel.process_update(*args)
#         if self._cur_panels and hasattr(self.panels[...], "process_update"):
#             self.panels[self._cur_panels[-1]].process_update(*args)
#
# There is no plugin system and no startup hook; panels are imported lazily by
# import_module(f"panels.{panel}"). So an add-on can only start watching once
# one of its own panels has been opened by hand. For the autoloader that means
# a freshly started touchscreen ignores a guide opened in Mainsail, which from
# the outside is indistinguishable from the feature being broken.
#
# This adds the smallest hook that fixes it: at the end of __init__, import
# every module in KlipperScreen's addons/ directory and call its init(screen).
# The patch is deliberately generic and does not mention the autoloader, both
# because that is the right shape and because it is what we would like to
# propose upstream.
#
# SAFETY
#
# This edits a file that runs the printer's UI, so:
#   * it refuses to run unless the exact expected anchor is present;
#   * it is idempotent -- a second run is a no-op;
#   * it backs the file up before touching it;
#   * it byte-compiles the result and restores the backup if that fails;
#   * `--revert` puts the original back.
#
# A KlipperScreen update overwrites screen.py and silently removes the hook,
# which is why post_update.sh runs this every time rather than once.

set -euo pipefail

KS_DIR="${SA_KLIPPERSCREEN_PATH:-$HOME/KlipperScreen}"
SCREEN="$KS_DIR/screen.py"
MARKER="_load_addons"
PYBIN="${SA_KS_PYTHON:-$HOME/.KlipperScreen-env/bin/python}"
[ -x "$PYBIN" ] || PYBIN="$(command -v python3 || true)"

say() { printf '  %s\n' "$*"; }

if [ ! -f "$SCREEN" ]; then
    say "KlipperScreen not found at $SCREEN - nothing to patch"
    exit 0
fi

# ── revert ────────────────────────────────────────────────────────────────
if [ "${1:-}" = "--revert" ]; then
    newest="$(ls -1t "$KS_DIR"/screen.py.sa-bak.* 2>/dev/null | head -1 || true)"
    if [ -z "$newest" ]; then
        say "no backup to revert to"
        exit 0
    fi
    cp "$newest" "$SCREEN"
    say "reverted screen.py from $(basename "$newest")"
    exit 0
fi

# ── already done? ─────────────────────────────────────────────────────────
if grep -q "$MARKER" "$SCREEN"; then
    say "addon hook already present"
    exit 0
fi

# ── the anchor ────────────────────────────────────────────────────────────
# Two lines at the end of __init__. Matching both, rather than just one, so a
# reshuffle upstream fails loudly here instead of putting the call somewhere
# it does not belong.
ANCHOR_A='        self.log_notification("KlipperScreen Started", 1)'
ANCHOR_B='        self.initial_connection()'

if ! grep -qF "$ANCHOR_A" "$SCREEN" || ! grep -qF "$ANCHOR_B" "$SCREEN"; then
    say "SKIPPED: screen.py does not match the expected shape."
    say "         KlipperScreen has changed; the addon hook was not applied."
    say "         The autoloader still works, but a cold-started touchscreen"
    say "         will not follow a guide opened in Mainsail until an"
    say "         autoloader panel is opened once."
    exit 0
fi

BACKUP="$SCREEN.sa-bak.$(date +%s)"
cp "$SCREEN" "$BACKUP"

"$PYBIN" - "$SCREEN" <<'PYEOF'
import io, sys

path = sys.argv[1]
s = io.open(path, encoding='utf-8').read()

anchor = ('        self.log_notification("KlipperScreen Started", 1)\n'
          '        self.initial_connection()')
call = ('        self.log_notification("KlipperScreen Started", 1)\n'
        '        self._load_addons()\n'
        '        self.initial_connection()')
assert anchor in s, "anchor vanished between check and patch"
s = s.replace(anchor, call, 1)

method_anchor = '    def process_update(self, *args):'
method = '''    def _load_addons(self):
        """Import addons/*.py and hand each one the screen, once, at startup.

        process_update reaches only the panel currently on screen, so an
        add-on has no way to observe the printer while the user is elsewhere.
        This is the entry point that lets one arrange that for itself.

        A broken add-on must never stop KlipperScreen from starting, so every
        import and every call is contained.
        """
        addon_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 "addons")
        if not os.path.isdir(addon_dir):
            return
        if addon_dir not in sys.path:
            sys.path.insert(0, addon_dir)
        for entry in sorted(os.listdir(addon_dir)):
            if not entry.endswith(".py") or entry.startswith("_"):
                continue
            name = entry[:-3]
            try:
                module = import_module(name)
                init = getattr(module, "init", None)
                if callable(init):
                    init(self)
                    logging.info(f"Addon loaded: {name}")
            except Exception:
                logging.exception(f"Failed to load addon {name}")

'''
assert method_anchor in s, "process_update not found"
s = s.replace(method_anchor, method + method_anchor, 1)

io.open(path, 'w', encoding='utf-8', newline='\n').write(s)
PYEOF

if ! "$PYBIN" -m py_compile "$SCREEN" 2>/dev/null; then
    cp "$BACKUP" "$SCREEN"
    say "FAILED: patched screen.py does not compile - original restored"
    exit 1
fi

say "addon hook added to screen.py (backup: $(basename "$BACKUP"))"
