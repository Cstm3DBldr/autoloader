#!/bin/bash
# install.sh — first-time setup. After install, all subsequent updates run
# through Moonraker Update Manager → post_update.sh (auto-syncs non-symlinked
# files). Use scripts/verify.sh to confirm everything is in place.

set -e
# Overridable so the installer can be exercised against scratch directories.
# This script writes to printer.cfg, symlinks into Klipper and restarts
# services -- all of which need to be testable somewhere that is not a working
# printer, or they only ever get tested on one.
KLIPPER_PATH="${SA_KLIPPER_PATH:-${HOME}/klipper}"
MOONRAKER_PATH="${SA_MOONRAKER_PATH:-${HOME}/moonraker}"
INSTALL_PATH="${SA_INSTALL_PATH:-${HOME}/autoloader}"
CONFIG_DIR="${SA_CONFIG_DIR:-${HOME}/printer_data/config}"
KS_PATH="${SA_KS_PATH:-${HOME}/KlipperScreen}"

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
        # .autoloader-config is every menuconfig answer. Losing it means the
        # next install starts from defaults and silently regenerates a config
        # for a machine it no longer knows the shape of.
        # hardware.cfg is here for one reason: it holds the CAN UUID, and a
        # board already in use does not answer canbus_query. Lose it and
        # reinstalling means hunting the UUID down again with the board
        # unplugged.
        for keep in variables.cfg user.cfg .autoloader-config hardware.cfg; do
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
if [ "${SA_SKIP_PULL:-0}" = "1" ]; then
    echo "[INSTALL] Skipping git pull (SA_SKIP_PULL=1)."
else
    echo "[INSTALL] Pulling latest from GitHub..."
    git -C "${INSTALL_PATH}" pull origin main
fi

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

# Read the printer and pre-fill what can be read, so the menu is mostly
# confirming rather than typing. Never fatal: a printer it cannot read still
# gets a working menu, just with fewer answers filled in.
python3 "${INSTALL_PATH}/installer/detect.py"     --config-dir "${CONFIG_DIR}" --answers "${SA_ANSWERS}" || true

if [ "${SA_RUN_MENU}" = "1" ]; then
    echo ""
    echo "[INSTALL] Opening setup. This is the same menu Klipper uses to build"
    echo "          firmware, so it should look familiar."
    echo ""
    echo "            up / down     move                 Enter or Space  open / toggle"
    echo "            left or Esc   go back a level      ?               explain this line"
    echo "            /             search               Q               save and quit"
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
# The stop. detect.py warns while the menu is open, but the option stays
# selectable and the cost of selecting it is a printer that will not start.
if ! python3 "${INSTALL_PATH}/installer/detect.py" --check         --config-dir "${CONFIG_DIR}" --answers "${SA_ANSWERS}"; then
    exit 1
fi

echo "[INSTALL] Running post_update.sh (syncs files and builds your config)..."
SA_REPO="${INSTALL_PATH}" SA_CONFIG="${CONFIG_DIR}" "${INSTALL_PATH}/post_update.sh"

# ── Register with Moonraker Update Manager ───────────────────────────────────
# The file the user edits. Not in the repo, so no update can reach it, and
# autoloader.cfg includes it last so anything here overrides parameters.cfg.
#
# Re-running this installer must never quietly discard it: a user who moved
# tuned values here to protect them from post_update.sh would lose exactly the
# thing they were protecting.
USER_CFG="${CONFIG_DIR}/autoloader/user.cfg"
mkdir -p "${CONFIG_DIR}/autoloader"

# ── put back what an uninstall set aside ─────────────────────────────────────
# Uninstall preserves calibration, settings and the LED config; nothing put
# them back. A wipe-and-reinstall therefore came up with the hardware correct
# and every bowden length at its 800 mm default -- hours of measurement sitting
# in a directory the user was never told to look in.
#
# Restored automatically rather than offered. variables.cfg is a measurement of
# THIS machine, and the machine has not changed between an uninstall and the
# reinstall that follows it; a fresh install that silently discards it is never
# what anyone wanted. It is also trivially undone -- delete the file and
# recalibrate -- whereas losing it is not.
#
# Only ever fills in what is MISSING. Anything already present wins, so this
# cannot overwrite a config the user has just built deliberately.
SA_BACKUP="$(ls -d "${HOME}"/autoloader-config-backup-* 2>/dev/null | tail -1)"
if [ -n "${SA_BACKUP}" ] && [ -d "${SA_BACKUP}" ]; then
    SA_RESTORED=""
    if [ -f "${SA_BACKUP}/variables.cfg" ] && \
       [ ! -f "${CONFIG_DIR}/autoloader/variables.cfg" ]; then
        cp -a "${SA_BACKUP}/variables.cfg" "${CONFIG_DIR}/autoloader/"
        SA_RESTORED="${SA_RESTORED} variables.cfg"
    fi
    if [ -f "${SA_BACKUP}/user.cfg" ] && [ ! -f "${USER_CFG}" ]; then
        cp -a "${SA_BACKUP}/user.cfg" "${USER_CFG}"
        SA_RESTORED="${SA_RESTORED} user.cfg"
    fi
    if [ -d "${SA_BACKUP}/leds" ] && \
       [ -z "$(ls -A "${CONFIG_DIR}/autoloader/leds" 2>/dev/null)" ]; then
        mkdir -p "${CONFIG_DIR}/autoloader/leds"
        cp -a "${SA_BACKUP}/leds/." "${CONFIG_DIR}/autoloader/leds/" 2>/dev/null
        SA_RESTORED="${SA_RESTORED} leds/"
    fi
    if [ -n "${SA_RESTORED}" ]; then
        echo "[INSTALL] Put back from your last uninstall:${SA_RESTORED}"
        echo "          (calibration and settings — the originals are still in"
        echo "           ${SA_BACKUP})"
        if [ -f "${CONFIG_DIR}/autoloader/variables.cfg" ]; then
            echo "          $(grep -c '=' "${CONFIG_DIR}/autoloader/variables.cfg" 2>/dev/null) calibrated value(s) restored."
        fi
    fi
fi

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
    if grep -qE '^[[:space:]]*canbus_uuid' "${USER_CFG}" 2>/dev/null; then
        echo ""
        echo "          NOTE: it contains a canbus_uuid. If that is the only"
        echo "          place your board's UUID is written, overwriting will"
        echo "          stop Klipper starting until you put it back. A backup"
        echo "          is taken either way."
    fi
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

# ── LEDs ─────────────────────────────────────────────────────────────────────
# The example is split in two on purpose. leds_core.cfg is entirely namespaced
# and cannot collide with anything; leds_status.cfg holds the ten STATUS_*
# macros that share names with the stock stealthburner_leds.cfg. Copying only
# core is what makes "keep my existing LEDs" actually safe -- warning about the
# collision but then installing the colliding macros anyway would be worse than
# not offering the option.
sa_answer() {
    # grep + cut, deliberately not a sed regex. Writing a BRE that contains
    # quotes and a capture group through this many layers of quoting lost the
    # backreference, and a sed substitution whose replacement is empty still
    # matches and prints -- so the failure was silent, and it blanked the very
    # settings it was meant to fill in.
    grep -m1 "^CONFIG_$1=" "${SA_ANSWERS}" 2>/dev/null |
        cut -d= -f2- |
        sed 's/^"//; s/"$//'
}

SA_LED_MODE="none"
if grep -q '^CONFIG_LEDS_FULL=y' "${SA_ANSWERS}" 2>/dev/null; then
    SA_LED_MODE="full"
elif grep -q '^CONFIG_LEDS_FILAMENT_ONLY=y' "${SA_ANSWERS}" 2>/dev/null; then
    SA_LED_MODE="core"
fi

if [ "${SA_LED_MODE}" != "none" ]; then
    SA_LED_DIR="${CONFIG_DIR}/autoloader/leds"
    SA_EX="${CONFIG_DIR}/autoloader/examples"
    mkdir -p "${SA_LED_DIR}"

    if [ -f "${SA_LED_DIR}/leds_core.cfg" ] || [ -f "${SA_LED_DIR}/leds.cfg" ]; then
        echo "[INSTALL] Keeping your existing LED config in ${SA_LED_DIR}"
    else
        cp "${SA_EX}/leds_core.cfg" "${SA_LED_DIR}/"
        # Fill in what detection found, so the copy matches this machine rather
        # than the developer's.
        for pair in             "led_prefix:LED_CHAIN_PREFIX"             "led_suffix:LED_CHAIN_SUFFIX"             "logo_idx:LED_LOGO_INDEX"             "nozzle_idx:LED_NOZZLE_INDEXES"; do
            var="${pair%%:*}"; key="${pair##*:}"
            val=$(sa_answer "${key}")
            if [ -n "${val}" ]; then
                sed -i "s|^variable_${var}:.*|variable_${var}: \"${val}\"|"                     "${SA_LED_DIR}/leds_core.cfg"
            fi
        done
        echo "[INSTALL] Installed LED config: leds_core.cfg"
    fi

    if [ "${SA_LED_MODE}" = "full" ] && [ ! -f "${SA_LED_DIR}/leds_status.cfg" ]; then
        cp "${SA_EX}/leds_status.cfg" "${SA_LED_DIR}/"
        echo "[INSTALL] Installed LED config: leds_status.cfg (STATUS_* macros)"
    fi

    if [ -f "${USER_CFG}" ]; then
        sed -i 's|^#\[include leds/\*\.cfg\]|[include leds/*.cfg]|' "${USER_CFG}"
    fi
    echo "[INSTALL] LEDs enabled. Verify the chain names and indexes with"
    echo "          _SA_LED_TEST_T0 — see docs/LEDS.md."
fi

# ── printer.cfg include ──────────────────────────────────────────────────────
if grep -q '^CONFIG_WRITE_PRINTER_CFG_INCLUDE=y' "${SA_ANSWERS}" 2>/dev/null; then
    SA_PCFG="${CONFIG_DIR}/printer.cfg"
    if [ ! -f "${SA_PCFG}" ]; then
        echo "[INSTALL] No printer.cfg found — add this yourself:"
        echo "            [include autoloader/autoloader.cfg]"
    elif grep -qE '^\s*\[include autoloader/autoloader\.cfg\]' "${SA_PCFG}"; then
        echo "[INSTALL] printer.cfg already includes the autoloader."
    else
        cp -a "${SA_PCFG}" "${SA_PCFG}.bak.$(date +%s)"
        # Insert ABOVE the SAVE_CONFIG block. Klipper appends its saved state as
        # "#*#" lines at the very end and rewrites that region wholesale, so an
        # include appended after it would be destroyed on the next SAVE_CONFIG.
        if grep -qn '^#\*# <---------------------- SAVE_CONFIG' "${SA_PCFG}"; then
            ln=$(grep -n '^#\*# <---------------------- SAVE_CONFIG' "${SA_PCFG}"                  | head -1 | cut -d: -f1)
            sed -i "${ln}i [include autoloader/autoloader.cfg]
" "${SA_PCFG}"
        else
            printf '
[include autoloader/autoloader.cfg]
' >> "${SA_PCFG}"
        fi
        echo "[INSTALL] Added [include autoloader/autoloader.cfg] to printer.cfg"
        echo "          (previous kept as printer.cfg.bak.*)"
    fi
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
# Honour the menu answer rather than always restarting: a user who said no
# wants to restart in their own time, and an automated run must not need sudo.
if grep -q '^CONFIG_RESTART_SERVICES=y' "${SA_ANSWERS}" 2>/dev/null    && [ "${SA_SKIP_RESTART:-0}" != "1" ]; then
    echo "[INSTALL] Restarting klipper, moonraker, KlipperScreen..."
    sudo systemctl restart klipper
    sudo systemctl restart moonraker
    sudo systemctl restart KlipperScreen 2>/dev/null || true
else
    echo "[INSTALL] Not restarting services — do it when you are ready:"
    echo "            sudo systemctl restart klipper moonraker KlipperScreen"
fi

echo
echo "✓ Install complete."
if grep -qE '^\s*\[include autoloader/autoloader\.cfg\]' "${CONFIG_DIR}/printer.cfg" 2>/dev/null; then
    echo "  • printer.cfg already includes the autoloader — nothing to add"
else
    echo "  • Add this line to printer.cfg, then restart Klipper:"
    echo "        [include autoloader/autoloader.cfg]"
fi
echo "  • Run ${INSTALL_PATH}/scripts/verify.sh to confirm everything is in sync"

# ── the one thing that will stop Klipper starting, said plainly ──────────────
# The installer knows perfectly well the UUID is unset -- it tried to find one
# and said so during detection. Staying quiet here means a first-time user
# restarts and meets "mcu 'autoloader': Invalid CAN uuid" with no idea it was
# foreseeable. Warn at the end, where they are actually looking.
# Checks the GENERATED FILE, not the answers. detect.py only writes MCU_UUID
# when it actually found one, so on a first install the key is absent from the
# answers entirely and CHANGE_ME arrives from the Kconfig default at generate
# time -- a grep of the answers file matches nothing and the warning never
# fires. The artifact is what Klipper reads, so the artifact is what to check.
if grep -qE '^canbus_uuid:[[:space:]]*CHANGE_ME'         "${CONFIG_DIR}/autoloader/hardware.cfg" 2>/dev/null; then
    echo ""
    echo "  ⚠  YOUR CAN UUID IS NOT SET YET — Klipper will not start until it is."
    echo ""
    echo "     The autoloader board has to be found before it can be addressed,"
    echo "     and a board already running does not answer a scan. So:"
    echo ""
    echo "       1. Power the printer off, then on."
    echo "       2. Before starting a print, run:"
    echo "            python3 ~/klipper/scripts/canbus_query.py can0"
    echo "       3. It prints a line like:  canbus_uuid=329ce333239a"
    echo "       4. Put that number in:"
    echo "            ~/printer_data/config/autoloader/user.cfg"
    echo "          as:"
    echo "            [mcu autoloader]"
    echo "            canbus_uuid: <the number>"
    echo "       5. Restart Klipper."
    echo ""
    echo "     user.cfg is included last, so it overrides the generated file and"
    echo "     no update can undo it."
    echo ""
fi
