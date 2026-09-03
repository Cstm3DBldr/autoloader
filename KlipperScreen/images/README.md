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

A per-tool mark, for anywhere a specific toolhead is named — the Load/Unload
rows, post-load, status. Chosen from five candidates after several rounds
against photos of the real hardware.

Tall and narrow with a **flat top**, a **blower fan** cut out of the body, and
a **bottom that forks into two duct prongs** with the nozzle emerging between
them. Those three carry the recognition; everything else was tried and cut.

Things deliberately not in it, each having been drawn and rejected:

- **Voron slashes.** They sit on the front face of the real head, but at 24 px
  they land on top of the fan and turn it to mush.
- **Pointed shoulder wings.** An earlier draft read as a shield rather than a
  toolhead — the head is a squarish block, not an arrowhead.
- **Bolt heads flanking the fan.** Two units across on a 64 grid is under a
  pixel at menu size.

The top corners are **chamfered by 3 units rather than square**. A true 90°
corner sits directly above the round fan and reads ragged once scaled down;
the chamfer still says "machined block" without that fight.

The fan is a **hole cut with `fill-rule="evenodd"`**, not a drawn ring. A ring
at these sizes collapses into grey; a hole stays crisp.

On a 64-unit grid rather than `autoloader.svg`'s 24, which the fan cut-out
needs to stay circular. `fill:#ffffff` matches the bundled z-bolt icons, the
theme running here.

Verified through KlipperScreen's own stack before shipping — librsvg via
GdkPixbuf at 24, 40, 56 and 64 px — because a file librsvg rejects renders as
a blank tile with no error anywhere. See the warning above about comments.

**Not yet referenced by any panel.** Use it with
`self._gtk.Button("toolhead", label, style)`. The calibration prompt cannot
show it: KlipperScreen builds prompt buttons with `image_name=None`
hard-coded (`ks_includes/widgets/prompts.py`), and Klipper's `prompt_button`
protocol has no icon field, so getting it there needs a CSS
`background-image` injected through a theme. See UI_AUDIT.md.
