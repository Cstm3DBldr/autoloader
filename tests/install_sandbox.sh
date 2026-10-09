#!/bin/bash
# A fresh install, end to end, in a throwaway sandbox -- on a real Klipper host
# but touching nothing of it.
#
# "Confirming an installer change means running install.sh on a machine that
# has never seen the project" was true and impractical: there is one printer,
# and it has seen the project. install.sh already takes its paths from SA_*
# variables, and everything else it touches hangs off $HOME -- so a fake HOME
# is a machine that has never seen the project. Klipper, Moonraker,
# KlipperScreen and the real config are only ever READ (copied in), services
# are never restarted (SA_SKIP_RESTART), and nothing is pulled (SA_SKIP_PULL).
#
# Runs three installs against one sandbox:
#   1. defaults, no terminal          -- the piped `wget | bash` case
#   2. REGISTER_UPDATE_MANAGER = no   -- the answer must remove the registration
#   3. LEDs on + toolchange LED hook  -- the hook line must be PRINTED, and the
#                                        toolchanger config left untouched
#
# Usage (on the printer):  bash ~/autoloader/tests/install_sandbox.sh [repo]
#   repo defaults to the checkout this script lives in; its COMMITTED state is
#   what gets installed (cloned), so push before testing a change.
# Exit 0 = every check passed. The sandbox is deleted unless SA_KEEP_SBX=1.

set -u
REPO="${1:-$(cd "$(dirname "$0")/.." && pwd)}"
REAL_HOME="${HOME}"
SBX="$(mktemp -d /tmp/sa_install_sbx.XXXXXX)"
H="${SBX}/home"
FAILS=0

pass() { echo "  ok    $*"; }
fail() { echo "  FAIL  $*"; FAILS=$((FAILS + 1)); }
cleanup() { [ "${SA_KEEP_SBX:-0}" = "1" ] && echo "(sandbox kept: ${SBX})" || rm -rf "${SBX}"; }
trap cleanup EXIT

[ -d "${REAL_HOME}/klipper/lib/kconfiglib" ] || {
    echo "Needs a Klipper host: ${REAL_HOME}/klipper/lib/kconfiglib not found."; exit 2; }

# ── the machine that has never seen the project ─────────────────────────────
mkdir -p "${H}/klipper/klippy/extras" "${H}/klipper/lib" \
         "${H}/moonraker/moonraker/components" "${H}/printer_data"
ln -s "${REAL_HOME}/klipper/lib/kconfiglib" "${H}/klipper/lib/kconfiglib"
[ -d "${REAL_HOME}/.KlipperScreen-env" ] && ln -s "${REAL_HOME}/.KlipperScreen-env" "${H}/.KlipperScreen-env"
if [ -d "${REAL_HOME}/KlipperScreen" ]; then
    mkdir -p "${H}/KlipperScreen"
    cp -a "${REAL_HOME}/KlipperScreen/screen.py" "${H}/KlipperScreen/"
    mkdir -p "${H}/KlipperScreen/panels" "${H}/KlipperScreen/styles"
fi
# The real config, minus everything this project put there.
cp -a "${REAL_HOME}/printer_data/config" "${H}/printer_data/config"
rm -rf "${H}/printer_data/config/autoloader" "${H}/printer_data/config/sa_klipperscreen.conf"
sed -i '/^\s*\[include autoloader\/autoloader\.cfg\]/d' "${H}/printer_data/config/printer.cfg" 2>/dev/null
# And the toolchange LED hook, a manual edit on this printer -- left in, step 3
# would only ever see "already present" and never test the printed line.
grep -RlE '_SA_LEDS_INIT_ALL' "${H}/printer_data/config" --include='*.cfg' 2>/dev/null \
    | xargs -r sed -i '/_SA_LEDS_INIT_ALL/d'
git clone -q "${REPO}" "${H}/autoloader" || { echo "clone of ${REPO} failed"; exit 2; }

CFG="${H}/printer_data/config"
ANS="${CFG}/autoloader/.autoloader-config"
INI="${H}/.moonraker/config/update_manager/autoloader.ini"
TC_BEFORE="$(cd "${CFG}" && grep -RlE '^\[toolchanger\]' . --include='*.cfg' 2>/dev/null | head -1 \
             | xargs -r md5sum 2>/dev/null)"

run_install() {
    env -i HOME="${H}" PATH="${PATH}" USER="${USER:-pi}" \
        SA_SKIP_PULL=1 SA_NO_MENU=1 SA_SKIP_RESTART=1 SA_KS_ADDONS=no \
        bash "${H}/autoloader/install.sh" </dev/null >"${SBX}/out.$1" 2>&1
    echo $?
}

# ── 1. defaults ──────────────────────────────────────────────────────────────
echo "1. fresh install, defaults, no terminal"
rc=$(run_install 1)
[ "${rc}" = "0" ] && pass "exit 0" || { fail "exit ${rc}"; tail -15 "${SBX}/out.1"; }
grep -q "Install complete" "${SBX}/out.1" && pass "reached the end" || fail "never reached 'Install complete'"
for f in autoloader.py sa_motion.py sa_sequences.py sa_calibration.py sa_encoder.py sa_led_animator.py; do
    [ -L "${H}/klipper/klippy/extras/${f}" ] || fail "no extras symlink ${f}"
done
pass "extras symlinked into the sandbox Klipper"
for f in pin_aliases.cfg hardware.cfg parameters.cfg; do
    [ -f "${CFG}/autoloader/${f}" ] || fail "${f} not generated"
done
pass "configs generated"
[ -f "${CFG}/autoloader/.autoloader-defaults.json" ] && pass "template defaults recorded" \
    || fail "no .autoloader-defaults.json beside the generated files"
grep -q "Sync complete" "${SBX}/out.1" && pass "post_update.sh ran to the end" \
    || fail "post_update.sh stopped early"
[ -f "${INI}" ] && pass "registered with the Update Manager (default yes)" \
    || fail "default answer did not register with the Update Manager"
# detect.py creates the answers file before the defaults step, which used to
# make an unattended install skip the defaults entirely and read every
# unanswered yes-by-default question as no.
grep -q '^CONFIG_RESTART_SERVICES=y' "${ANS}" && grep -q '^CONFIG_WRITE_PRINTER_CFG_INCLUDE=y' "${ANS}" \
    && pass "answers file completed with the menu defaults" \
    || fail "answers file still missing defaults (RESTART_SERVICES / WRITE_PRINTER_CFG_INCLUDE)"
grep -qE '^\s*\[include autoloader/autoloader\.cfg\]' "${CFG}/printer.cfg" \
    && pass "printer.cfg include added (default yes)" \
    || fail "printer.cfg include not added although the answer defaults to yes"

# ── 2. Update Manager: no ────────────────────────────────────────────────────
echo "2. REGISTER_UPDATE_MANAGER = no"
sed -i 's/^CONFIG_REGISTER_UPDATE_MANAGER=y/# CONFIG_REGISTER_UPDATE_MANAGER is not set/' "${ANS}"
rc=$(run_install 2)
[ "${rc}" = "0" ] && pass "exit 0" || { fail "exit ${rc}"; tail -15 "${SBX}/out.2"; }
[ ! -f "${INI}" ] && pass "registration removed" || fail "autoloader.ini still present after 'no'"
grep -q "you said no" "${SBX}/out.2" && pass "said why" || fail "no message for the 'no' answer"

# ── 3. LED hook ──────────────────────────────────────────────────────────────
echo "3. LEDs on, toolchange LED hook = yes"
sed -i -e 's/^CONFIG_LEDS_NONE=y/# CONFIG_LEDS_NONE is not set/' \
       -e 's/^# CONFIG_LEDS_FILAMENT_ONLY is not set/CONFIG_LEDS_FILAMENT_ONLY=y/' "${ANS}"
grep -q '^CONFIG_ADD_TOOLCHANGE_LED_HOOK' "${ANS}" \
    && sed -i 's/^.*CONFIG_ADD_TOOLCHANGE_LED_HOOK.*/CONFIG_ADD_TOOLCHANGE_LED_HOOK=y/' "${ANS}" \
    || echo "CONFIG_ADD_TOOLCHANGE_LED_HOOK=y" >> "${ANS}"
rc=$(run_install 3)
[ "${rc}" = "0" ] && pass "exit 0" || { fail "exit ${rc}"; tail -15 "${SBX}/out.3"; }
if grep -q "_SA_LEDS_INIT_ALL ACTIVE={tool.tool_number}" "${SBX}/out.3"; then
    pass "hook line printed"
else
    fail "hook answered yes and the line was not printed"
fi
TC_AFTER="$(cd "${CFG}" && grep -RlE '^\[toolchanger\]' . --include='*.cfg' 2>/dev/null | head -1 \
            | xargs -r md5sum 2>/dev/null)"
[ "${TC_BEFORE}" = "${TC_AFTER}" ] && pass "toolchanger config untouched" \
    || fail "the toolchanger config was modified"

echo
[ "${FAILS}" -eq 0 ] && { echo "install sandbox: all checks passed"; exit 0; }
echo "install sandbox: ${FAILS} check(s) failed (outputs in ${SBX}/out.N; SA_KEEP_SBX=1 keeps them)"
exit 1
