#!/bin/bash
# install.sh — first-time setup. After install, all subsequent updates run
# through Moonraker Update Manager → post_update.sh (auto-syncs non-symlinked
# files). Use scripts/verify.sh to confirm everything is in place.

set -e
KLIPPER_PATH="${HOME}/klipper"
MOONRAKER_PATH="${HOME}/moonraker"
INSTALL_PATH="${HOME}/autoloader"
CONFIG_DIR="${HOME}/printer_data/config"
KS_PATH="${HOME}/KlipperScreen"

# ── Uninstall ────────────────────────────────────────────────────────────────
if [ "${1:-}" = "--uninstall" ]; then
    echo "[UNINSTALL] Removing Autoloader..."
    # Klipper extras symlinks
    for f in autoloader.py sa_motion.py sa_sequences.py sa_calibration.py sa_encoder.py sa_led_animator.py; do
        rm -f "${KLIPPER_PATH}/klippy/extras/${f}"
    done
    # Moonraker component symlink
    rm -f "${MOONRAKER_PATH}/moonraker/components/sa_moonraker.py"
    # KlipperScreen direct copies
    rm -f "${KS_PATH}/panels/"sa_*.py 2>/dev/null || true
    rm -f "${KS_PATH}/"sa_*.py 2>/dev/null || true
    rm -f "${CONFIG_DIR}/sa_klipperscreen.conf"
    # Live config dir
    # NOT rm -rf on the whole directory. It holds variables.cfg -- every
    # bowden length, encoder mm/pulse and selector position the machine was
    # calibrated with, which took hours to measure and is not in the repo, so
    # nothing else has a copy. Same for user.cfg and any adapted leds/.
    KEEP_DIR="${CONFIG_DIR}/autoloader"
    if [ -d "${KEEP_DIR}" ]; then
        KEEP_BAK="${HOME}/autoloader-config-backup-$(date +%s)"
        mkdir -p "${KEEP_BAK}"
        for keep in variables.cfg user.cfg; do
            [ -f "${KEEP_DIR}/${keep}" ] && cp -a "${KEEP_DIR}/${keep}" "${KEEP_BAK}/"
        done
        [ -d "${KEEP_DIR}/leds" ] && cp -a "${KEEP_DIR}/leds" "${KEEP_BAK}/"
        [ -d "${KEEP_DIR}/filament_profiles" ] && cp -a "${KEEP_DIR}/filament_profiles" "${KEEP_BAK}/"
        rm -rf "${KEEP_DIR}"
        echo "[UNINSTALL] Kept your calibration and settings in ${KEEP_BAK}"
    fi
    # Update manager registration
    rm -f "${HOME}/.moonraker/config/update_manager/autoloader.ini" 2>/dev/null || true
    echo "[UNINSTALL] Complete. Repo at ${INSTALL_PATH} kept (rm -rf manually if desired)."
    echo "[UNINSTALL] Remove [include autoloader/autoloader.cfg] from printer.cfg, then restart klipper."
    exit 0
fi

if [ "$EUID" -eq 0 ]; then echo "[ERROR] Do not run as root."; exit 1; fi

# ── Pull latest ──────────────────────────────────────────────────────────────
echo "[INSTALL] Pulling latest from GitHub..."
git -C "${INSTALL_PATH}" pull origin main

# ── Symlink Klipper extras ───────────────────────────────────────────────────
echo "[INSTALL] Symlinking Klipper extras..."
for f in autoloader.py sa_motion.py sa_sequences.py sa_calibration.py sa_encoder.py sa_led_animator.py; do
    ln -sfn "${INSTALL_PATH}/klipper/extras/${f}" "${KLIPPER_PATH}/klippy/extras/${f}"
    echo "  ${KLIPPER_PATH}/klippy/extras/${f} -> ${INSTALL_PATH}/klipper/extras/${f}"
done

# ── Symlink Moonraker component ──────────────────────────────────────────────
echo "[INSTALL] Symlinking Moonraker component..."
ln -sfn "${INSTALL_PATH}/moonraker/sa_moonraker.py" "${MOONRAKER_PATH}/moonraker/components/sa_moonraker.py"

# ── Initial sync of non-symlinked files ──────────────────────────────────────
# ── menuconfig ───────────────────────────────────────────────────────────────
# Answers live with the user's config, not in the repo, so a re-run starts from
# what they chose last time and an update cannot overwrite them.
SA_ANSWERS="${CONFIG_DIR}/autoloader/.autoloader-config"
mkdir -p "${CONFIG_DIR}/autoloader"

SA_RUN_MENU=1
[ "${SA_NO_MENU:-}" = "1" ] && SA_RUN_MENU=0
[ -t 0 ] || SA_RUN_MENU=0

if [ "${SA_RUN_MENU}" = "1" ]; then
    echo ""
    echo "[INSTALL] Opening setup. This is the same menu Klipper uses to build"
    echo "          firmware, so it should look familiar."
    echo ""
    echo "            arrow keys  move            Enter  open a menu"
    echo "            Y / N       turn on/off     ?      explain this setting"
    echo "            Q           save and quit   Esc Esc  go back"
    echo ""
    printf "          Press Enter to start..."
    read -r _ || true
    srctree="${INSTALL_PATH}" KCONFIG_CONFIG="${SA_ANSWERS}" python3         "${HOME}/klipper/lib/kconfiglib/menuconfig.py"         "${INSTALL_PATH}/installer/Kconfig" || {
            echo "[INSTALL] Setup cancelled — nothing was changed." >&2
            exit 1
        }
else
    if [ ! -f "${SA_ANSWERS}" ]; then
        echo "[INSTALL] No terminal for the setup menu — writing defaults."
        echo "          Re-run this from an interactive shell to change them,"
        echo "          or edit ${SA_ANSWERS} by hand."
        srctree="${INSTALL_PATH}" python3 -c "
import sys; sys.path.insert(0, '${HOME}/klipper/lib/kconfiglib')
import kconfiglib
kc = kconfiglib.Kconfig('${INSTALL_PATH}/installer/Kconfig', warn=False)
kc.write_config('${SA_ANSWERS}')
"
    else
        echo "[INSTALL] Using your saved answers in ${SA_ANSWERS}"
    fi
fi

# Generation happens inside post_update.sh, which is also what Moonraker's
# Update Manager runs -- so the install path and the update path build the
# config exactly the same way, and there is only one of them to get right.
echo "[INSTALL] Running post_update.sh (syncs files and builds your config)..."
"${INSTALL_PATH}/post_update.sh"

# ── Register with Moonraker Update Manager ───────────────────────────────────
# The file the user edits. Not in the repo, so no update can reach it, and
# autoloader.cfg includes it last so anything here overrides parameters.cfg.
#
# Re-running this installer must never quietly discard it: a user who moved
# tuned values here to protect them from post_update.sh would lose exactly the
# thing they were protecting.
USER_CFG="${CONFIG_DIR}/autoloader/user.cfg"
mkdir -p "${CONFIG_DIR}/autoloader"

sa_write_user_cfg() {
    cat > "$1" <<'USEREOF'
# ══════════════════════════════════════════════════════════════════════════════
# Autoloader — your settings.
#
# install.sh creates this file and will not overwrite it without asking. It is
# not in the repository, so no update can reach it. Everything else under
# ~/printer_data/config/autoloader/ IS replaced on update, so put anything you
# want to keep here.
#
# Included last, so a value here overrides the same value in parameters.cfg.
# To change a tuned setting, copy just that line here rather than editing
# parameters.cfg:
#
#   [autoloader]
#   bowden_length_0: 812.5
#   feed_speed: 45
#
# Calibration values written by SA_CALIBRATE_* live in variables.cfg, not here,
# and are never overwritten by an update.
# ══════════════════════════════════════════════════════════════════════════════

# >>> SA-BLOCK: leds
# ── Toolhead status LEDs — off by default ─────────────────────────────────────
#
# The autoloader is fully functional without them; nothing in the load, unload
# or calibration path uses LEDs. To turn them on:
#
#   1. mkdir -p ~/printer_data/config/autoloader/leds
#   2. cp ~/printer_data/config/autoloader/examples/leds.cfg ~/printer_data/config/autoloader/leds/
#   3. adapt that copy to your hardware — chain names and LED indexes differ
#      per build, and the shipped defaults are the developer's machine
#   4. uncomment the line below, then restart Klipper
#
# READ docs/LEDS.md FIRST. The example defines ten STATUS_* macros that the
# stock Voron stealthburner_leds.cfg also defines. Klipper uppercases macro
# aliases, so its lowercase `status_ready` and the example's `STATUS_READY`
# register the same command and Klipper REFUSES TO START. Check with:
#
#   grep -rli "gcode_macro status_ready" ~/printer_data/config/
#
#[include leds/*.cfg]
# <<< SA-BLOCK: leds
USEREOF
}

if [ ! -f "${USER_CFG}" ]; then
    echo "[INSTALL] Creating ${USER_CFG}"
    sa_write_user_cfg "${USER_CFG}"
else
    echo ""
    echo "[INSTALL] ${USER_CFG} already exists."
    echo "          It may hold settings that override parameters.cfg."
    echo ""
    echo "            k) Keep it as it is                      (default, safe)"
    echo "            u) Upgrade — append only blocks it is missing, change nothing else"
    echo "            o) Overwrite — back the current one up first"
    echo ""
    # SA_USER_CFG=keep|upgrade|overwrite answers this without a prompt, for an
    # unattended install. Otherwise ask, and when there is no terminal to ask
    # at, default to Keep -- a piped or scripted run must never destroy
    # settings by falling through a prompt nobody was there to answer.
    case "${SA_USER_CFG:-}" in
        keep|k)      SA_CHOICE="k"; echo "          SA_USER_CFG=keep" ;;
        upgrade|u)   SA_CHOICE="u"; echo "          SA_USER_CFG=upgrade" ;;
        overwrite|o) SA_CHOICE="o"; echo "          SA_USER_CFG=overwrite" ;;
        "")
            if [ -t 0 ]; then
                printf "          Choice [k/u/o]: "
                read -r SA_CHOICE
            else
                SA_CHOICE="k"
                echo "          (not a terminal — keeping it; set SA_USER_CFG to choose)"
            fi
            ;;
        *)
            echo "[ERROR] SA_USER_CFG must be keep, upgrade or overwrite (got '${SA_USER_CFG}')." >&2
            exit 1
            ;;
    esac

    case "${SA_CHOICE}" in
        o|O)
            SA_BAK="${USER_CFG}.bak.$(date +%s)"
            cp -a "${USER_CFG}" "${SA_BAK}"
            sa_write_user_cfg "${USER_CFG}"
            echo "[INSTALL] Overwrote it. Your previous file: ${SA_BAK}"
            ;;
        u|U)
            SA_TMP="$(mktemp)"
            sa_write_user_cfg "${SA_TMP}"
            SA_ADDED=0
            # Each template section is fenced by a stable marker. Append only
            # the ones this file has never seen; never remove, never reorder,
            # never touch a line the user wrote.
            for blk in $(grep -oE '^# >>> SA-BLOCK: [a-z0-9_]+' "${SA_TMP}" | awk '{print $4}'); do
                if ! grep -q "^# >>> SA-BLOCK: ${blk}\$" "${USER_CFG}"; then
                    {
                        echo ""
                        echo "# ── added by install.sh on $(date +%Y-%m-%d) ──"
                        sed -n "/^# >>> SA-BLOCK: ${blk}\$/,/^# <<< SA-BLOCK: ${blk}\$/p" "${SA_TMP}"
                    } >> "${USER_CFG}"
                    echo "[INSTALL]   appended new block: ${blk}"
                    SA_ADDED=$((SA_ADDED + 1))
                fi
            done
            rm -f "${SA_TMP}"
            [ "${SA_ADDED}" = "0" ] && echo "[INSTALL]   already up to date — nothing appended."
            ;;
        *)
            echo "[INSTALL] Keeping it unchanged."
            ;;
    esac
fi

echo "[INSTALL] Registering with Moonraker Update Manager..."
mkdir -p "${HOME}/.moonraker/config/update_manager"
cat > "${HOME}/.moonraker/config/update_manager/autoloader.ini" <<EOF
[update_manager autoloader]
type: git_repo
channel: dev
path: ${INSTALL_PATH}
origin: https://github.com/Cstm3DBldr/autoloader.git
managed_services: klipper
primary_branch: main
post_update_script: ${INSTALL_PATH}/post_update.sh
EOF

# ── Restart services ─────────────────────────────────────────────────────────
echo "[INSTALL] Restarting klipper, moonraker, KlipperScreen..."
sudo systemctl restart klipper
sudo systemctl restart moonraker
sudo systemctl restart KlipperScreen 2>/dev/null || true

echo
echo "✓ Install complete."
echo "  • Add [include autoloader/autoloader.cfg] to printer.cfg (if not already there)"
echo "  • Run ${INSTALL_PATH}/scripts/verify.sh to confirm everything is in sync"
