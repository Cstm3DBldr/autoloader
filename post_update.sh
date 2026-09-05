#!/bin/bash
# post_update.sh — runs automatically after every Moonraker Update Manager pull.
#
# This is the canonical "deploy non-symlinked files" step. It must be safe to
# run repeatedly (idempotent). Files NOT covered by the Klipper-extras and
# Moonraker symlinks live here:
#
#   ~/printer_data/config/autoloader/          .cfg + .html (user-editable)
#   ~/KlipperScreen/panels/sa_*.py             KlipperScreen panel modules
#   ~/KlipperScreen/sa_*.py                    KlipperScreen helpers
#   ~/printer_data/config/sa_klipperscreen.conf KlipperScreen menu registration
#
# Every component must be listed here. If you add a new on-printer destination,
# add it to this script AND to CLAUDE.md "Project Surface".

set -e
# Overridable so this can be pointed at a non-standard layout, and so the
# script can be exercised against a scratch directory without touching a live
# printer -- which is the only way to test the regeneration path safely.
REPO="${SA_REPO:-${HOME}/autoloader}"
CONFIG="${SA_CONFIG:-${HOME}/printer_data/config}"
KS="${HOME}/KlipperScreen"

echo "[POST-UPDATE] Syncing user-editable cfg + html to ${CONFIG}/autoloader/..."
mkdir -p "${CONFIG}/autoloader"
# Three of these files are GENERATED from your menuconfig answers, not
# shipped: pin_aliases.cfg, hardware.cfg and parameters.cfg. Copying the repo
# versions over them is what used to discard tuned values on every update.
#
# So when a saved answer file exists we copy everything else and regenerate
# those three in refresh mode, which rebuilds them from the new templates and
# then puts every value you had back. With no answer file -- a manual install
# that never ran the installer -- we fall back to copying, which is the old
# behaviour.
SA_ANSWERS="${CONFIG}/autoloader/.autoloader-config"
SA_GENERATED="pin_aliases.cfg hardware.cfg parameters.cfg"

if [ -f "${SA_ANSWERS}" ] && [ -f "${REPO}/installer/generate.py" ]; then
    for f in "${REPO}"/autoloader/*.cfg; do
        base=$(basename "$f")
        skip=0
        for g in ${SA_GENERATED}; do
            if [ "$base" = "$g" ]; then skip=1; fi
        done
        # `if`, not `[ ... ] && cp`. This script runs under `set -e`, and that
        # form returns non-zero on every SKIPPED file -- so the first generated
        # file would abort the whole update.
        if [ "$skip" = "0" ]; then
            cp -f "$f" "${CONFIG}/autoloader/"
        fi
    done
    echo "[POST-UPDATE] Regenerating config from your saved answers..."
    ( cd "${REPO}" && python3 installer/generate.py         --config "${SA_ANSWERS}"         --out "${CONFIG}/autoloader" ) || {
            echo "[POST-UPDATE] ERROR: generation failed; your config was left alone." >&2
            exit 1
        }
else
    cp -f "${REPO}"/autoloader/*.cfg  "${CONFIG}/autoloader/"
fi



# The filament database. KlipperScreen reads brand files from
# config/autoloader/filament_profiles (sa_load_unload.py), and nothing ever put
# them there -- they survived only because nothing had deleted them. An
# uninstall/reinstall wiped the lot and left the filament picker empty, with no
# error to explain why.
#
# Copied file by file, never with a delete: a brand file the user added
# themselves is theirs to keep.
mkdir -p "${CONFIG}/autoloader/filament_profiles"
if ls "${REPO}"/filaments/brands/*.cfg >/dev/null 2>&1; then
    cp -f "${REPO}"/filaments/brands/*.cfg "${CONFIG}/autoloader/filament_profiles/"
    echo "[POST-UPDATE] Filament database: $(ls "${REPO}"/filaments/brands/*.cfg | wc -l) brand file(s)."
fi

# Worked examples the user copies and adapts. Always refreshed, because
# nobody edits these in place -- the copy they edit lives in leds/.
mkdir -p "${CONFIG}/autoloader/examples"
cp -f "${REPO}"/autoloader/examples/*.cfg "${CONFIG}/autoloader/examples/" 2>/dev/null || true

# Created empty and then left alone. autoloader.cfg includes leds/*.cfg,
# which is inert while the directory is empty, and anything the user puts
# here is theirs: NOTHING in this script may write to or delete from it, or
# an update would silently discard their LED tuning.
mkdir -p "${CONFIG}/autoloader/leds"
cp -f "${REPO}"/autoloader/*.html "${CONFIG}/autoloader/" 2>/dev/null || true

echo "[POST-UPDATE] Syncing KlipperScreen panels..."
if [ -d "${KS}/panels" ]; then
    cp -f "${REPO}"/KlipperScreen/panels/sa_*.py "${KS}/panels/" 2>/dev/null || true
    cp -f "${REPO}"/KlipperScreen/sa_*.py        "${KS}/"        2>/dev/null || true
    cp -f "${REPO}"/KlipperScreen/sa_klipperscreen.conf "${CONFIG}/" 2>/dev/null || true

    # Icons are per-theme in KlipperScreen, so the file goes into every theme
    # that is installed rather than just the active one — the active theme is
    # not always pinned in config, and a missing icon renders as a blank tile.
    for theme_images in "${KS}"/styles/*/images; do
        [ -d "$theme_images" ] && cp -f "${REPO}"/KlipperScreen/images/*.svg "$theme_images/" 2>/dev/null || true
    done
else
    echo "[POST-UPDATE]   (KlipperScreen not installed — skipping panel sync)"
fi

echo "[POST-UPDATE] Sync complete."
