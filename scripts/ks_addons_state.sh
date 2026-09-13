#!/bin/bash
# Is KlipperScreen's own add-on loader present, and is it switched on?
#
# KlipperScreen/KlipperScreen#1770 (merged 2026-09-13, 8abe645c) added the
# startup hook upstream -- the one scripts/patch_klipperscreen.sh used to add
# by hand. Review asked for it to be opt-in, so it ships GATED behind
# `enable_addons` in [main], default False, on the grounds that it runs code
# KlipperScreen did not write or review.
#
# That gate is the whole reason this script exists. Our patch correctly stands
# aside once upstream has the hook -- it guards on the same `_load_addons`
# marker -- so on any printer that updates KlipperScreen past the merge the
# add-on quietly stops loading unless the flag is set. Nothing errors. The
# touchscreen simply stops following a guide opened in Mainsail until someone
# opens an autoloader panel.
#
# Exit codes:
#   0  upstream hook present AND enable_addons is on   -- nothing to do
#   1  upstream hook present but enable_addons is OFF  -- needs the operator
#   2  no upstream hook (older KlipperScreen)          -- our patch is in charge
#
# Usage: bash scripts/ks_addons_state.sh [ks_path] [klipperscreen.conf]

KS="${1:-${SA_KS_PATH:-${HOME}/KlipperScreen}}"
CONF="${2:-${SA_KS_CONF:-${HOME}/printer_data/config/KlipperScreen.conf}}"

# The upstream hook is told from ours by the flag it reads. Ours predates the
# review and has no gate, so `enable_addons` appearing in screen.py is the
# thing that says which one is installed.
if ! grep -q "enable_addons" "${KS}/screen.py" 2>/dev/null; then
    exit 2
fi

# configparser-ish: a bare `enable_addons: True` under [main]. Accept the
# spellings KlipperScreen's own settings UI writes.
if grep -Eqi "^[[:space:]]*enable_addons[[:space:]]*[:=][[:space:]]*(true|1|yes)[[:space:]]*$" \
        "${CONF}" 2>/dev/null; then
    exit 0
fi
exit 1
