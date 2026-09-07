"""Autoloader add-on entry point, run once when KlipperScreen starts.

KlipperScreen delivers printer status only to the panel currently on screen,
so an add-on that wants to react to the printer while the user is somewhere
else has nowhere to stand. The autoloader needs exactly that: the guide can be
opened from Mainsail, and the touchscreen should follow whatever it happens to
be showing.

Until this existed, the watcher was installed from an autoloader panel's
activate(). That meant a freshly started KlipperScreen was deaf until someone
opened one of those panels by hand -- which is indistinguishable, from the
outside, from the feature not working at all.

Loaded by the `addons/` hook in screen.py. See scripts/patch_klipperscreen.sh
for what that hook is and how it is applied.
"""

import logging


def init(screen):
    """Called once by KlipperScreen at startup, with the screen instance."""
    try:
        import sa_subscription
    except Exception:
        logging.exception("sa_autoloader: sa_subscription is not importable")
        return
    sa_subscription.install_global_popup_watcher(screen)
    logging.info("sa_autoloader: watching for autoloader events from startup")
