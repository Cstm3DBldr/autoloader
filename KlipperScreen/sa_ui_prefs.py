# sa_ui_prefs.py — persist UI preferences for Autoloader KlipperScreen panels
#
# Stores prefs in ~/printer_data/config/autoloader/sa_ui_prefs.json, beside
# user.cfg and variables.cfg -- the directory the project already treats as
# the user's, which post_update.sh never overwrites (it copies *.cfg and
# *.html) and which a Mainsail config backup already includes.
#
# It used to live at ~/autoloader/klipperscreen/sa_ui_prefs.json: INSIDE the
# repo checkout. On a case-sensitive filesystem that directory does not exist,
# so the first save created an untracked `klipperscreen/` in the repo, and on
# this printer a hand-made `klipperscreen -> KlipperScreen` symlink put the
# file in the tracked KlipperScreen/ directory. Both showed as dirt in every
# `git status`, and either would have been lost to a `git clean`.

import json
import logging
import os

_PREFS_PATH = os.path.expanduser(
    "~/printer_data/config/autoloader/sa_ui_prefs.json")

# Where it used to be written. Read once, moved to _PREFS_PATH, then removed,
# so an accent colour chosen before the move survives it.
_LEGACY_PATHS = (
    os.path.expanduser("~/autoloader/klipperscreen/sa_ui_prefs.json"),
    os.path.expanduser("~/autoloader/KlipperScreen/sa_ui_prefs.json"),
)

_DEFAULTS = {
    "accent_color":  "#1565C0",   # button background
    "hover_color":   "#1976D2",
    "active_color":  "#0D47A1",
}

_prefs = None


def _write(path, prefs):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, 'w') as f:
        json.dump(prefs, f, indent=2)
    os.replace(tmp, path)


def _migrate():
    """Move prefs saved at a legacy path to _PREFS_PATH, once."""
    if os.path.isfile(_PREFS_PATH):
        return
    for old in _LEGACY_PATHS:
        if not os.path.isfile(old):
            continue
        try:
            with open(old) as f:
                saved = json.load(f)
            _write(_PREFS_PATH, saved)
            # realpath: the two legacy paths can be one file through the
            # symlink, and the second remove would then fail.
            os.remove(os.path.realpath(old))
            logging.info("sa_ui_prefs: moved %s -> %s", old, _PREFS_PATH)
        except (OSError, ValueError) as e:
            logging.warning("sa_ui_prefs: could not move %s: %s", old, e)
        return


def load():
    global _prefs
    _prefs = dict(_DEFAULTS)
    _migrate()
    try:
        if os.path.isfile(_PREFS_PATH):
            with open(_PREFS_PATH) as f:
                _prefs.update(json.load(f))
    except (OSError, ValueError) as e:
        logging.warning("sa_ui_prefs: could not read %s, using defaults: %s",
                        _PREFS_PATH, e)
    return _prefs


def save(updates):
    if _prefs is None:
        load()
    _prefs.update(updates)
    try:
        _write(_PREFS_PATH, _prefs)
    except OSError as e:
        logging.warning("sa_ui_prefs: could not save %s: %s", _PREFS_PATH, e)


def get(key, default=None):
    if _prefs is None:
        load()
    return _prefs.get(key, _DEFAULTS.get(key, default))
