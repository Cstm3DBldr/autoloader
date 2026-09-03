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

## toolhead.svg

A per-tool mark, for anywhere a specific toolhead is named — the path buttons
on the calibration prompt, the Load/Unload rows, post-load. Drawn from the
Dragon Burner this printer runs, so it reads as *the* toolhead rather than a
generic hotend.

Three features carry the recognition, and they are the only three worth
keeping at icon size:

- the shield body with the two shoulder wings, which is the silhouette you
  see across the gantry
- the blower fan, cut out of the body with `fill-rule="evenodd"` rather than
  drawn as a ring, so it stays a clean hole instead of turning into grey mush
  when it is scaled down
- the nozzle stepping down in two stages below the body

Deliberately left out: the Voron slashes on the front face, and the extruder
motor on top. Both are real, and both collapse into noise below about 40 px —
the slashes in particular sit right on top of the fan circle and fight it. The
project already has a Voron identity elsewhere; this icon only needs to say
"toolhead".

On a 64-unit grid rather than the 24 used by `autoloader.svg`, because the fan
cut-out needs the extra resolution to stay circular. `fill:#ffffff` matches the
bundled z-bolt icons, which is the theme running here; `autoloader.svg` uses
`#bebebe` and both read fine on the dark themes.

**Not yet wired to anything.** Panels can use it immediately via
`self._gtk.Button("toolhead", label, style)`. The calibration prompt cannot:
KlipperScreen builds prompt buttons with `image_name=None` hard-coded
(`ks_includes/widgets/prompts.py`), and Klipper's `prompt_button` protocol has
no icon field, so getting it there needs a CSS `background-image` injected
through a theme. See UI_AUDIT.md.
