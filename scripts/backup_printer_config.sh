#!/bin/bash
# Snapshot the printer's live configuration onto a dedicated git branch, as a
# known-good reference to diff against or restore from.
#
# Run this from the repo on your PC (Git Bash), NOT on the printer:
#
#   bash "/c/Users/Mike/Claude Project Files/Autoloader/scripts/backup_printer_config.sh"
#
# Optionally label the snapshot:
#
#   bash ".../backup_printer_config.sh" "before-respooler-work"
#
# What it captures
# ----------------
# Two kinds of files, for two different reasons:
#
#   1. Files the repo already tracks and deploys (autoloader/*.cfg,
#      KlipperScreen panels, sa_klipperscreen.conf). These land in their normal
#      repo paths, so `git diff main <branch>` shows exactly what drifted on
#      the printer — user-tuned values, Mainsail config-editor changes,
#      calibration results written by SAVE_CONFIG.
#
#   2. Printer-side files the repo does NOT track (printer.cfg, macros.cfg,
#      homing.cfg, moonraker.conf, Toolchanger/). These have no version control
#      anywhere today. They land under printer_snapshot/ so they exist
#      somewhere other than the SD card.
#
# Deliberately skipped: gcode files, logs, the Moonraker database, and .git —
# large, regenerable, or not configuration.
#
# Restoring later
# ---------------
#   git checkout <branch> -- autoloader/parameters.cfg     # one file
#   git checkout <branch> -- printer_snapshot/             # the untracked set
#
# The branch is never merged. It is an archive.

set -u

PRINTER="pi@192.168.1.214"
LABEL="${1:-}"

# ── Locate the repo without assuming the current directory ──────────────────
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO" || { echo "ERROR: cannot enter repo at $REPO"; exit 1; }

if [ ! -d .git ] && [ ! -f .git ]; then
    echo "ERROR: $REPO is not a git repository."
    exit 1
fi

# ── Refuse to run with uncommitted work, so nothing gets lost ───────────────
if [ -n "$(git status --porcelain)" ]; then
    echo "ERROR: You have uncommitted changes. Commit or stash them first."
    echo ""
    git status --short
    exit 1
fi

ORIGINAL_BRANCH="$(git rev-parse --abbrev-ref HEAD)"

# ── Confirm the printer is reachable before doing anything destructive ──────
echo "Checking the printer is reachable..."
if ! ssh -o ConnectTimeout=10 -o BatchMode=yes "$PRINTER" true 2>/dev/null; then
    echo "ERROR: Cannot reach the printer at $PRINTER."
    echo "       Is it powered on and on the network?"
    exit 1
fi

DATE="$(ssh "$PRINTER" 'date +%Y-%m-%d')"
BRANCH="printer-backup/known-good-${DATE}"
[ -n "$LABEL" ] && BRANCH="${BRANCH}-${LABEL}"

# ── Don't silently clobber an existing snapshot ─────────────────────────────
if git show-ref --verify --quiet "refs/heads/$BRANCH"; then
    echo "ERROR: Branch '$BRANCH' already exists."
    echo "       Pass a label to make it unique, e.g.:"
    echo "         bash \"$0\" second-run"
    exit 1
fi

STAGING="$(mktemp -d)"
trap 'rm -rf "$STAGING"' EXIT

echo "Pulling configuration from the printer..."

# Everything under printer_data/config except gcodes, logs and the database.
ssh "$PRINTER" 'cd ~/printer_data && tar czf - \
        --exclude="config/.moonraker.conf.bkp" \
        --exclude="*.bak.*" \
        config' > "$STAGING/config.tar.gz" 2>/dev/null \
    || { echo "ERROR: Failed to read ~/printer_data/config from the printer."; exit 1; }

ssh "$PRINTER" 'cd ~ && tar czf - \
        KlipperScreen/panels/sa_*.py \
        KlipperScreen/sa_*.py' > "$STAGING/ks.tar.gz" 2>/dev/null \
    || echo "WARNING: no KlipperScreen sa_* files found; continuing."

# ── Record what was actually running, so the snapshot is identifiable ───────
{
    echo "# Printer configuration snapshot"
    echo ""
    echo "Captured: $(ssh "$PRINTER" 'date -Is')"
    echo "Host:     $PRINTER"
    [ -n "$LABEL" ] && echo "Label:    $LABEL"
    echo ""
    echo "## Deployed autoloader commit"
    echo ""
    echo '```'
    ssh "$PRINTER" 'cd ~/autoloader && git log --oneline -1 && git status --short' 2>/dev/null || echo "(unavailable)"
    echo '```'
    echo ""
    echo "## Service versions"
    echo ""
    echo '```'
    ssh "$PRINTER" 'cd ~/klipper && echo -n "klipper:   " && git describe --tags --always 2>/dev/null; \
                    cd ~/moonraker && echo -n "moonraker: " && git describe --tags --always 2>/dev/null; \
                    cd ~/KlipperScreen && echo -n "KS:        " && git describe --tags --always 2>/dev/null; \
                    echo -n "mainsail:  " && cat ~/mainsail/.version 2>/dev/null || true' 2>/dev/null
    echo '```'
    echo ""
    echo "## Service state"
    echo ""
    echo '```'
    ssh "$PRINTER" 'systemctl is-active klipper moonraker KlipperScreen 2>/dev/null | paste -sd" " -' 2>/dev/null || echo "(unavailable)"
    echo '```'
    echo ""
    echo "## Klipper state at capture"
    echo ""
    echo '```'
    ssh "$PRINTER" 'curl -s http://localhost:7125/printer/info' 2>/dev/null | head -c 600 || echo "(unavailable)"
    echo '```'
} > "$STAGING/MANIFEST.md"

echo "Building the snapshot branch..."

git checkout -q -b "$BRANCH" || { echo "ERROR: could not create branch $BRANCH"; exit 1; }

mkdir -p "$STAGING/extract"

# tar exits non-zero when it cannot recreate a symlink whose target does not
# exist on this machine -- printer_data/config has several pointing into other
# projects (tapchanger, moonraker-timelapse, mainsail-config). Those are not
# autoloader data and their absence is expected, so the exit status alone
# cannot be trusted either way. Check the RESULT instead: a backup that
# reports success while holding nothing is worse than no backup at all.
tar xzf "$STAGING/config.tar.gz" -C "$STAGING/extract" 2>"$STAGING/tar.err" || true

EXTRACTED=$(find "$STAGING/extract" -type f 2>/dev/null | wc -l)
if [ ! -f "$STAGING/extract/config/printer.cfg" ] || [ "$EXTRACTED" -lt 5 ]; then
    echo "ERROR: the snapshot did not extract properly -- $EXTRACTED file(s), and"
    echo "       printer.cfg is $([ -f "$STAGING/extract/config/printer.cfg" ] && echo present || echo missing)."
    echo "       Refusing to create a branch that would look like a good backup."
    echo ""
    echo "tar said:"
    sed 's/^/  /' "$STAGING/tar.err" 2>/dev/null | head -20
    exit 1
fi

if [ -s "$STAGING/tar.err" ]; then
    SKIPPED=$(grep -c "Cannot create symlink" "$STAGING/tar.err" 2>/dev/null || echo 0)
    if [ "$SKIPPED" -gt 0 ]; then
        echo "  note: $SKIPPED symlink(s) to other projects were not recreated."
        echo "        They point outside printer_data and are not autoloader data."
    fi
fi
[ -f "$STAGING/ks.tar.gz" ] && tar xzf "$STAGING/ks.tar.gz" -C "$STAGING/extract" 2>/dev/null

SRC="$STAGING/extract/config"

# 1. Overwrite the repo's own deployed files with the printer's live copies,
#    so a diff against main shows the drift.
[ -d "$SRC/autoloader" ] && cp -f "$SRC"/autoloader/*.cfg  "$REPO/autoloader/"  2>/dev/null
[ -d "$SRC/autoloader" ] && cp -f "$SRC"/autoloader/*.html "$REPO/autoloader/"  2>/dev/null
[ -f "$SRC/sa_klipperscreen.conf" ] && cp -f "$SRC/sa_klipperscreen.conf" "$REPO/KlipperScreen/"
if [ -d "$STAGING/extract/KlipperScreen/panels" ]; then
    cp -f "$STAGING/extract/KlipperScreen/panels/"sa_*.py "$REPO/KlipperScreen/panels/" 2>/dev/null
fi
if ls "$STAGING/extract/KlipperScreen/"sa_*.py >/dev/null 2>&1; then
    cp -f "$STAGING/extract/KlipperScreen/"sa_*.py "$REPO/KlipperScreen/" 2>/dev/null
fi

# 2. Everything else from the printer's config dir, which the repo does not
#    track, kept verbatim so it exists somewhere off the SD card.
rm -rf "$REPO/printer_snapshot"
mkdir -p "$REPO/printer_snapshot"
cp -r "$SRC/." "$REPO/printer_snapshot/" 2>/dev/null
cp -f "$STAGING/MANIFEST.md" "$REPO/printer_snapshot/MANIFEST.md"

# The .gitignore excludes some of these paths for normal work; this branch is
# an archive, so include them regardless.
git add -A -f autoloader/ KlipperScreen/ printer_snapshot/ 2>/dev/null

if [ -z "$(git status --porcelain)" ]; then
    echo ""
    echo "Nothing differed from the current branch — no snapshot needed."
    git checkout -q "$ORIGINAL_BRANCH"
    git branch -q -D "$BRANCH"
    exit 0
fi

git commit -q -F - <<EOF
chore(backup): known-good printer configuration snapshot ${DATE}${LABEL:+ (${LABEL})}

Captured from the live printer while everything was working, as a
reference to diff against or restore from.

Repo-tracked files under autoloader/ and KlipperScreen/ hold the
printer's copies, so a diff against main shows what drifted there —
user-tuned values, edits made through the Mainsail config editor, and
anything SAVE_CONFIG wrote.

printer_snapshot/ holds the rest of ~/printer_data/config, which the
repo does not track and which otherwise exists only on the SD card:
printer.cfg, macros.cfg, homing.cfg, moonraker.conf and the Toolchanger
configs.

printer_snapshot/MANIFEST.md records the deployed commit and the Klipper,
Moonraker and KlipperScreen versions this was captured against.

This branch is an archive and is not meant to be merged.
EOF

git checkout -q "$ORIGINAL_BRANCH"

echo ""
# Ask the COMMITTED BRANCH, not the working tree. This runs after the checkout
# back to the original branch, at which point printer_snapshot/ is gone from
# the working tree -- so a find here reported zero files and declared a
# perfectly good backup incomplete. A check that cries wolf is worse than none:
# it teaches you to ignore it.
SNAP_COUNT=$(git ls-tree -r --name-only "$BRANCH" -- printer_snapshot 2>/dev/null | wc -l)
echo "Done — $SNAP_COUNT file(s) captured."
for must in autoloader/variables.cfg printer.cfg; do
    if git cat-file -e "$BRANCH:printer_snapshot/$must" 2>/dev/null; then
        echo "  ✓ $must"
    else
        echo "  ✗ $must is NOT in the snapshot — treat this backup as incomplete." >&2
    fi
done
echo ""
echo "  Branch:  $BRANCH"
echo "  Back on: $ORIGINAL_BRANCH"
echo ""
echo "See what drifted on the printer:"
echo "  git diff $ORIGINAL_BRANCH $BRANCH -- autoloader/ KlipperScreen/"
echo ""
echo "Restore one file later:"
echo "  git checkout $BRANCH -- autoloader/parameters.cfg"
echo ""
echo "Push it so it is not only on this PC:"
echo "  git push origin $BRANCH"
