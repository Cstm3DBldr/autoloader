# Runout recovery — a broken or exhausted path with filament still in the head

**Status: design note. Nothing is built.** Written 2026-09-10 so the shape can
be argued before any code exists, because this is the one routine in the
project that deliberately pushes material of uncertain identity into a hot
nozzle.

## The scenario

```
entry: CLEAR     extruder: FILAMENT     toolhead: FILAMENT
```

The tail has passed the entry sensor — the roll ran out, or the filament
snapped — but there is still filament from the extruder gears through to the
nozzle. Both `do_load` and `do_unload` currently refuse it outright:

```
SA: ERROR — extruder/toolhead sensor active without entry on path N.
Possible broken filament piece in tube.
```

That refusal is honest. It is not a recovery.

## Why the extruder cannot fix this alone

The extruder gears can only move filament they are gripping. Once the tail
passes them there is still `nozzle_distance` (50mm here) of material between
the gears and the tip, and **nothing can drive it**. Any plan that starts
"push the old filament out" stalls there by construction, and leaves a free
remnant with a gap above it that the next filament has to cross and mate with.

So the new filament is not a fallback. It is the mechanism: feed it down, let
it butt against the remnant in the melt zone, and push the whole column out.
This is what a normal filament change does, and what Bambu's nozzle-clearing
does for the same reason.

## Temperature

**Heat to the higher of the two materials' temperatures.** Decided
2026-09-10.

The remnant and the new roll need not be the same material, and the two
failures are not symmetric:

- too cold for the remnant — it does not move, and the extruder grinds a flat
  onto the new filament instead
- too hot for the remnant — it degrades, but it still leaves

The first jams the head; the second dirties a nozzle that is about to be
purged anyway. So the higher figure is the safe one.

**The old material is knowable.** A wipe does not destroy the profile, it
stashes it: `_stash_profile` writes `sa_lastprofile_N` as one dict including
`cleared_because`. So a recovery can name what it thinks was in there.

It must still be **confirmed by the operator**, for the same reason
`SA_RESTORE_PROFILE` is deliberately manual — a profile is a claim about what
is physically in the path, and only the operator can confirm the spool was not
changed while the machine was idle. If there is no stash, the routine should
refuse and say so rather than choose a temperature on the operator's behalf.

## The sequence

1. **Refuse unless the state matches.** Entry clear, and extruder or toolhead
   reading filament. Any other combination is a different problem.
2. **Report the stash and require confirmation.** Show the old material and why
   it was cleared. No stash, no recovery.
3. **Heat to `max(old_temp, new_temp)`.**
4. **Feed the new roll to the extruder sensor** — the normal Bowden blast, at
   the calibrated speed.
5. **Synced feed past the gears**, reusing `_sync_feed_to_toolhead_sensor`.
   Same drive+extruder concurrency the load already uses.
6. **Purge `nozzle_distance + purge_length`** — 80mm as configured. That is the
   gears-to-tip volume plus the existing prime margin, which is the amount that
   has to be displaced for the old material to be gone.
7. **Verify by sensors, not by hope:** entry, extruder and toolhead all reading
   filament, which is an ordinary loaded path.

## Failure modes, and how each is caught

| Failure | Detection |
|---|---|
| Remnant will not move (too cold, or wrong temp chosen) | encoder reads motion while the toolhead sensor never changes — the new filament is being ground, not fed |
| New tip wedges alongside a jagged break rather than butting it | same signature; the encoder is on the NEW filament so it reads fine. This is the one the slip check cannot see |
| Broken piece loose in the Bowden | pushing it works often and can make it worse — a snapped end can wedge at the gate or the gear entry |
| Nozzle already blocked by the remnant | purge produces no extrusion; nothing downstream can detect this without a flow sensor |

The second and third rows are why any "keep pushing until it clears" loop needs
a **hard distance bound** and a sensor-based success test. The encoder cannot
referee this one: it measures the filament being pushed, not the thing ahead
of it.

## Deliberate non-goals

- **Not automatic.** Explicitly invoked, e.g. `SA_RECOVER TOOL=N`. It heats a
  nozzle and pushes material of uncertain identity through it; that is not
  something to trigger off a sensor edge.
- **Not folded into load or unload.** Their refusal is correct for what they
  are. A recovery is a different operation with different consent.
- **Does not guess a temperature.** No stash means no recovery.
- **Does not clear a blocked nozzle.** If the remnant will not pass, that is a
  cold pull by hand, and the routine should say so rather than keep pushing.

## Open questions

- How far to push a loose Bowden fragment before giving up, and whether to
  attempt it at all versus telling the operator to pull the tube.
- Whether to require the new spool's profile to be set first, or to prompt for
  it as part of the routine.
- Whether a failed recovery should leave the path `unknown` or `partial`. It is
  neither, really — there is filament in it that nobody can account for.
