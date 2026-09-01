/*
 * Autoloader mark: a formed filament tip travelling right, with three dashes
 * trailing it.
 *
 * Replaces a spool glyph borrowed from Spoolman, which was another project's
 * brand sitting in this panel's header.
 *
 * Drawn as four thick shapes on purpose. Vuetify renders this as a bare
 * `fill: currentColor` path at 18 px in the panel header, so anything under
 * about 2 units of the 24-unit grid disappears at that size — which is what
 * ruled out the gear-driven versions, whose teeth turned to mush. Nothing
 * here is thinner than 1.7 units.
 *
 * Keep the tip as the leading element if this is ever redrawn: the taper is
 * what makes it read as filament rather than a generic bar.
 */
export const saFilamentIcon =
    'M11 9.8H20L23.4 12L20 14.2H11ZM6.6 9.8h3.2v4.4H6.6ZM2.9 9.8h2.6v4.4H2.9ZM0.3 9.8h1.7v4.4H0.3Z'
