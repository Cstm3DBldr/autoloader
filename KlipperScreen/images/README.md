# KlipperScreen icons

Icons referenced by `icon:` in the KlipperScreen menu config and by the
`sa_*.py` panels. `post_update.sh` copies every `.svg` here into
`~/KlipperScreen/styles/*/images/` — into *every* installed theme, because
KlipperScreen resolves icons per theme and the active theme is not pinned in
config on this printer. A missing icon renders as a blank tile.

## Do not put XML comments in these files

KlipperScreen renders icons through GdkPixbuf, and the librsvg it binds to on
this build rejects a file with a comment before the root element:

    gdk-pixbuf-error-quark: Couldn't recognize the image file format

The file is valid XML — `xml.dom.minidom` parses it happily — and the failure
message says nothing about comments, so this costs a while to find. The
bundled KlipperScreen icons all go straight from the XML declaration to
`<svg>`; match that. Notes about an icon belong in this README.

## autoloader.svg

The project mark: a formed filament tip travelling right with three dashes
trailing it. Replaced a spool glyph borrowed from Spoolman.

The same geometry is used for the Mainsail panel, as a path string in
`web/mainsail-plugin/src/icons.ts`. There is no shared source — if either is
redrawn, update both.

Drawn as four thick shapes deliberately. It renders at roughly 18–24 px in
both surfaces, and anything thinner than about two units of the 24-unit grid
disappears at that size. `fill:#bebebe` matches the convention the bundled
themes use.
