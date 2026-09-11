#!/usr/bin/env bash
# Build the Mainsail panel plugin, ship it, and make the browser actually load it.
#
# The plugin is registered in the Moonraker database with a fixed entryUrl:
#
#     /plugins/autoloader-panel-plugin.js
#
# A static file at a URL that never changes is a file the browser will serve
# from cache forever. Every update since has needed a manual Ctrl+Shift+R, and
# without one the panel looks like the deploy silently failed -- which is how a
# rebuilt guide came to look unchanged after it had already shipped.
#
# So the URL carries the file's own hash. Same file, same URL, still cached;
# changed file, new URL, fetched. Nothing to remember.
#
# Usage (from anywhere):
#     bash scripts/deploy_mainsail_plugin.sh
#     SA_HOST=pi@192.168.1.214 bash scripts/deploy_mainsail_plugin.sh
set -eu

HOST="${SA_HOST:-pi@192.168.1.214}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="${HERE}/web/mainsail-plugin"
FILE="autoloader-panel-plugin.js"
DEST="/home/pi/mainsail/plugins/${FILE}"

command -v npm >/dev/null 2>&1 || { echo "ERROR: npm not found; needed to build." >&2; exit 1; }
[ -d "${SRC}" ] || { echo "ERROR: ${SRC} missing." >&2; exit 1; }

echo "[1/4] Building..."
( cd "${SRC}" && npm run build >/dev/null ) || { echo "ERROR: build failed." >&2; exit 1; }
BUILT="${SRC}/dist/${FILE}"
[ -f "${BUILT}" ] || { echo "ERROR: ${BUILT} not produced." >&2; exit 1; }

# The hash is of the built file, so it changes exactly when the code does.
HASH="$(sha256sum "${BUILT}" | cut -c1-10)"
echo "      $(wc -c <"${BUILT}") bytes, hash ${HASH}"

echo "[2/4] Copying to ${HOST}..."
# -O forces the legacy SCP protocol. OpenSSH 9+ defaults to SFTP, which
# this printer's sshd closes on -- "scp: Connection closed", with no
# hint that the transport is the problem rather than the file or the
# host. Measured on 2026-09-11: identical command, -O succeeds.
scp -O -q "${BUILT}" "${HOST}:${DEST}" || { echo "ERROR: scp failed." >&2; exit 1; }

echo "[3/4] Pointing the registration at the new hash..."
ssh "${HOST}" "HASH='${HASH}' FILE='${FILE}' python3 - <<'PY'
import json, os, urllib.request

BASE = 'http://localhost:7125/server/database/item'
url  = '%s?namespace=mainsail&key=view.customPanels' % BASE
panels = json.load(urllib.request.urlopen(url, timeout=10))['result']['value']

want = '/plugins/%s?v=%s' % (os.environ['FILE'], os.environ['HASH'])
hit  = False
for p in panels:
    if p.get('id') == 'autoloader':
        if p.get('entryUrl') == want:
            print('      already current')
        p['entryUrl'] = want
        hit = True
if not hit:
    raise SystemExit('ERROR: no customPanel with id \"autoloader\" registered')

req = urllib.request.Request(
    BASE, method='POST',
    data=json.dumps({'namespace': 'mainsail', 'key': 'view.customPanels',
                     'value': panels}).encode(),
    headers={'Content-Type': 'application/json'})
urllib.request.urlopen(req, timeout=10).read()
print('      entryUrl -> ' + want)
PY" || { echo "ERROR: could not update the registration." >&2; exit 1; }

echo "[4/4] Verifying what the printer now serves..."
ssh "${HOST}" "curl -sf -o /dev/null -w '      /plugins/${FILE}?v=${HASH} -> HTTP %{http_code}\n' \
    'http://localhost/plugins/${FILE}?v=${HASH}'" || true

echo
echo "Done. Reload Mainsail once; after this the URL changes on its own"
echo "whenever the plugin does, so no hard refresh is needed again."
