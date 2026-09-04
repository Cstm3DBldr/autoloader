# Handoff — Filament Colour Database Refresh

**For:** a research agent. This document is self-contained; you do not need the
repository to do the work.

**What this database drives:** an automated filament loader on a 6-toolhead
Voron. The hex codes are not decoration — they are written to addressable RGB
LEDs on each toolhead so the operator can see at a glance which colour is in
which path. A wrong hex means the machine lies about what it is holding. The
temperatures are used to heat a real hotend.

---

## The job

Brands already in this database keep releasing colours. Find the ones we are
missing, and return them in the exact schema below.

**Scope:** the 15 brands listed in the inventory at the end of this document.
Do not add new brands unless you flag them separately as a suggestion —
the ask is completeness for what is already tracked.

**Known gap:** Polymaker's **Panchroma Matte PLA** is believed stale. It is the
first place to look. Assume other lines are stale too, and check all of them.

**Current coverage:** 15 brands, 118 product lines, 893 colours.

---

## Output schema — match it exactly

One block per colour:

```
[sa_color <product_line_key>.<color_key>]
product_line: <product_line_key>
color_name: <manufacturer's exact colour name>
color_hex: #RRGGBB
```

- `<product_line_key>` must be one of the keys in the inventory below, verbatim.
- `<color_key>` is the colour name in lowercase snake_case, ASCII only
  (`Sakura Pink` -> `sakura_pink`, `Ash Grey` -> `ash_grey`).
- `color_hex` is uppercase 6-digit hex with a leading `#`. No 3-digit form,
  no `0x`, no names.

If an entire product line is missing, add it in this shape first:

```
[sa_product_line <key>]
brand: <brand key from the inventory>
display_name: <manufacturer's exact line name>
material: PLA | PLA-CF | PETG | coPETG | ABS | ASA | TPU | PC | PA-CF | PVB | CoPE
description: <one line>
load_temp: <°C>
unload_temp: <°C>
purge_speed: 5
purge_length: 30
bed_temp: <°C>
```

### Multi-colour filaments

Silk dual-tone, tri-colour, and gradient filaments exist in several of these
lines. The schema supports them with two optional extra keys:

```
color_type: dual | tri          (omit entirely for a normal single colour)
color_hex_2: #RRGGBB
color_hex_3: #RRGGBB            (tri only)
```

Use these rather than inventing an averaged single hex — averaging a dual-tone
produces a colour the filament does not contain.

**Note: not one of the 893 existing entries uses `color_type`.** The loader has
supported it all along, but every dual-tone and tri-colour filament currently in
the database is stored as a single flat hex. Several tracked lines are explicitly
dual-colour — Amolen's silk line describes itself as "single and dual-color
options" — so **this is a second gap alongside the missing colours**: existing
entries that should be `dual` or `tri` and are not. Report those as corrections
to existing entries, listing the product line key, the colour key, and the two
or three real hexes, in a section of their own.

---

## Rules

1. **Hex codes must come from the manufacturer** — their own swatch image,
   product page colour chip, or official spec sheet. **Do not eyeball a hex
   from a product photograph.** Photo lighting and white balance make those
   wrong by a wide margin, and these values drive physical LEDs.
2. **Cite a source URL for every colour added.** No claim without a citation.
   A colour with no citation will be rejected, not merged.
3. **Use the manufacturer's exact colour name**, including accents, ™ and
   capitalisation. Do not normalise "Grey" to "Gray" or vice versa.
4. **Flag, do not guess.** If you cannot find a first-party hex, list the
   colour in a separate "found, no reliable hex" section with whatever source
   you did find. A guessed hex is worse than a missing one here.
5. **Never delete.** If a colour in the inventory appears discontinued, list it
   under "appears discontinued" with a source. The decision to remove is the
   operator's.
6. **Temperatures come from the manufacturer's published range.** If a range is
   given, take the midpoint and say so explicitly. `unload_temp` is
   conventionally 15 °C below `load_temp` in this database unless the
   manufacturer says otherwise.
7. **Do not duplicate.** Everything already present is listed in the inventory
   below. Check against it before reporting a colour as missing. Match on the
   manufacturer's name, and note that we may have stored an older name for a
   colour that has since been renamed — call those out rather than adding a
   second entry.

---

## Deliverable

1. **Additions**, grouped by brand file, in the schema above, ready to paste.
2. **Found but no reliable hex** — colour names and what source you did find.
3. **Appears discontinued** — with a source.
4. **Renamed** — old name in our inventory, current manufacturer name.
5. **Summary** — which lines were already complete, which were stale and by how
   much, and any brand you think is worth adding but did not add.

---

## Appendix — complete current inventory

Everything below is already in the database. Anything not listed here, for
these brands, is a candidate addition.

### Amolen — `amolen.cfg`

brand key: `amolen`

**`amolen_pla_glow`** — Amolen Glow in the Dark PLA (PLA, load 205°C) — 5 colours

> Glow Blue; Glow Green; Glow Orange; Glow White; Glow Yellow

**`amolen_pla_gradient`** — Amolen Gradient PLA (PLA, load 210°C) — 5 colours

> Forest; Galaxy; Ocean; Rainbow; Sunset

**`amolen_pla_marble`** — Amolen Marble PLA (PLA, load 200°C) — 3 colours

> Black Marble; Grey Marble; White Marble

**`amolen_pla_silk`** — Amolen PLA Silk (PLA, load 215°C) — 14 colours

> Dual Blue/Silver; Dual Gold/Black; Dual Red/Gold; Silk Black; Silk Blue; Silk Copper; Silk Gold; Silk Green; Silk Purple; Silk Rainbow; Silk Red; Silk Rose Gold; Silk Silver; Silk White

**`amolen_pla_wood`** — Amolen Wood Fill PLA (PLA, load 200°C) — 3 colours

> Bamboo; Dark Wood; Natural Wood

**`amolen_tpu`** — Amolen TPU 95A (TPU, load 220°C) — 4 colours

> Black; Red; Transparent; White


### Bambu Lab — `bambulabs.cfg`

brand key: `bambulabs`

**`bambu_abs`** — Bambu ABS (ABS, load 250°C) — 5 colours

> Black; Blue; Grey; Red; White

**`bambu_asa`** — Bambu ASA (ASA, load 250°C) — 6 colours

> Black; Blue; Grey; Red; White; Yellow

**`bambu_pa_cf`** — Bambu PA-CF (PA-CF, load 280°C) — 1 colours

> Black

**`bambu_petg_basic`** — Bambu PETG Basic (PETG, load 240°C) — 9 colours

> Black; Blue; Green; Grey; Orange; Red; Transparent; White; Yellow

**`bambu_pla_basic`** — Bambu PLA Basic (PLA, load 210°C) — 25 colours

> Bambu Green; Beige; Black; Blue; Brown; Cream; Cyan; Dark Grey; Gold; Green; Grey; Jade White; Light Grey; Lime Green; Magenta; Navy Blue; Orange; Pink; Purple; Red; Silver; Teal; Violet; White; Yellow

**`bambu_pla_cf`** — Bambu PLA-CF (PLA-CF, load 220°C) — 2 colours

> Black; Dark Grey

**`bambu_pla_matte`** — Bambu PLA Matte (PLA, load 210°C) — 12 colours

> Matte Beige; Matte Black; Matte Blue; Matte Brown; Matte Green; Matte Grey; Matte Orange; Matte Pink; Matte Purple; Matte Red; Matte White; Matte Yellow

**`bambu_pla_silk`** — Bambu PLA Silk (PLA, load 215°C) — 9 colours

> Silk Black; Silk Blue; Silk Copper; Silk Gold; Silk Green; Silk Purple; Silk Red; Silk Rose Gold; Silk Silver

**`bambu_tpu95a`** — Bambu TPU 95A (TPU, load 230°C) — 5 colours

> Black; Blue; Clear; Red; White


### ColorFabb — `colorfabb.cfg`

brand key: `colorfabb`

**`colorfabb_asa`** — ColorFabb ASA (ASA, load 245°C) — 3 colours

> Black; Grey; White

**`colorfabb_ht`** — ColorFabb HT (coPETG-HT) (coPETG, load 270°C) — 2 colours

> Black; White

**`colorfabb_ngen`** — ColorFabb nGen (coPETG, load 220°C) — 7 colours

> Black; Blue; Green; Grey; Orange; Red; White

**`colorfabb_pla_hs`** — ColorFabb PLA High Speed (PLA, load 205°C) — 4 colours

> Black; Blue; Red; White

**`colorfabb_pla_pha`** — ColorFabb PLA/PHA (PLA, load 195°C) — 11 colours

> Black; Blue; Brown; Green; Grey; Orange; Pink; Purple; Red; White; Yellow

**`colorfabb_tpu85a`** — ColorFabb TPU 85A (TPU, load 220°C) — 3 colours

> Black; Transparent; White

**`colorfabb_varioshore`** — ColorFabb Varioshore TPU (TPU, load 220°C) — 3 colours

> Black; Orange; White

**`colorfabb_xt`** — ColorFabb XT (coPETG) (coPETG, load 240°C) — 3 colours

> Black; Transparent; White


### Creality — `creality.cfg`

brand key: `creality`

**`creality_abs`** — Creality ABS (ABS, load 240°C) — 5 colours

> Black; Blue; Grey; Red; White

**`creality_asa`** — Creality ASA (ASA, load 245°C) — 4 colours

> Black; Grey; Red; White

**`creality_petg`** — Creality PETG (PETG, load 230°C) — 7 colours

> Black; Blue; Green; Grey; Red; Transparent; White

**`creality_pla`** — Creality PLA (PLA, load 200°C) — 14 colours

> Black; Blue; Brown; Gold; Green; Grey; Light Blue; Light Green; Orange; Pink; Purple; Red; White; Yellow

**`creality_pla_matte`** — Creality PLA Matte (PLA, load 210°C) — 6 colours

> Matte Black; Matte Blue; Matte Green; Matte Grey; Matte Red; Matte White

**`creality_pla_plus`** — Creality PLA+ (PLA, load 210°C) — 6 colours

> Black; Blue; Green; Grey; Red; White

**`creality_pla_silk`** — Creality PLA Silk (PLA, load 215°C) — 9 colours

> Silk Blue; Silk Copper; Silk Gold; Silk Green; Silk Purple; Silk Rainbow; Silk Red; Silk Rose Gold; Silk Silver

**`creality_tpu`** — Creality TPU 95A (TPU, load 220°C) — 5 colours

> Black; Blue; Red; Transparent; White


### eSUN — `esun.cfg`

brand key: `esun`

**`esun_abs_plus`** — eSUN ABS+ (ABS, load 240°C) — 7 colours

> Black; Blue; Grey; Orange; Red; White; Yellow

**`esun_asa`** — eSUN ASA (ASA, load 250°C) — 5 colours

> Black; Blue; Grey; Red; White

**`esun_pa_cf`** — eSUN PA-CF (PA-CF, load 260°C) — 1 colours

> Black

**`esun_petg`** — eSUN PETG (PETG, load 235°C) — 10 colours

> Black; Blue; Green; Grey; Orange; Purple; Red; Transparent; White; Yellow

**`esun_pla_matte`** — eSUN PLA Matte (PLA, load 215°C) — 6 colours

> Matte Black; Matte Blue; Matte Green; Matte Grey; Matte Red; Matte White

**`esun_pla_plus`** — eSUN PLA+ (PLA, load 220°C) — 20 colours

> Beige; Black; Blue; Brown; Dark Grey; Fire Engine Red; Gold; Grass Green; Grey; Light Blue; Light Green; Milky White; Orange; Peak Green; Pink; Purple; Red; Silver; White; Yellow

**`esun_pla_silk`** — eSUN PLA Silk (PLA, load 215°C) — 10 colours

> Silk Black; Silk Blue; Silk Copper; Silk Gold; Silk Green; Silk Purple; Silk Red; Silk Rose Gold; Silk Silver; Silk White

**`esun_tpu95a`** — eSUN TPU 95A (TPU, load 225°C) — 5 colours

> Black; Blue; Red; Transparent; White


### Fiberon — `fiberon.cfg`

brand key: `fiberon`

**`fiberon_asa_hf`** — Fiberon ASA HF (ASA, load 250°C) — 4 colours

> Black; Grey; Red; White

**`fiberon_petg_hf`** — Fiberon PETG HF (PETG, load 240°C) — 7 colours

> Black; Blue; Green; Grey; Red; Transparent; White

**`fiberon_pla_hf`** — Fiberon PLA HF (PLA, load 210°C) — 10 colours

> Black; Blue; Green; Grey; Orange; Pink; Purple; Red; White; Yellow

**`fiberon_pla_matte_hf`** — Fiberon PLA Matte HF (PLA, load 210°C) — 8 colours

> Matte Black; Matte Blue; Matte Green; Matte Grey; Matte Orange; Matte Purple; Matte Red; Matte White


### Hatchbox — `hatchbox.cfg`

brand key: `hatchbox`

**`hatchbox_abs`** — Hatchbox ABS (ABS, load 245°C) — 5 colours

> Black; Blue; Grey; Red; White

**`hatchbox_petg`** — Hatchbox PETG (PETG, load 245°C) — 8 colours

> Black; Blue; Green; Grey; Orange; Red; Transparent; White

**`hatchbox_pla`** — Hatchbox PLA (PLA, load 200°C) — 20 colours

> Black; Blue; Brown; Dark Grey; Gold; Green; Grey; Light Blue; Light Green; Magenta; Navy; Orange; Pink; Purple; Red; Silver; Tan; Teal; White; Yellow

**`hatchbox_tpu`** — Hatchbox TPU (TPU, load 225°C) — 5 colours

> Black; Blue; Red; Transparent; White


### Inland — `inland.cfg`

brand key: `inland`

**`inland_abs`** — Inland ABS (ABS, load 240°C) — 5 colours

> Black; Blue; Grey; Red; White

**`inland_asa`** — Inland ASA (ASA, load 245°C) — 4 colours

> Black; Grey; Red; White

**`inland_petg`** — Inland PETG (PETG, load 240°C) — 8 colours

> Black; Blue; Green; Grey; Orange; Red; Transparent; White

**`inland_pla`** — Inland PLA (PLA, load 200°C) — 20 colours

> Black; Blue; Brown; Dark Grey; Gold; Green; Grey; Light Blue; Light Green; Magenta; Navy; Orange; Pink; Purple; Red; Silver; Tan; Teal; White; Yellow

**`inland_pla_plus`** — Inland PLA+ (PLA, load 210°C) — 8 colours

> Black; Blue; Green; Grey; Orange; Purple; Red; White

**`inland_pla_silk`** — Inland PLA Silk (PLA, load 215°C) — 9 colours

> Silk Black; Silk Blue; Silk Copper; Silk Gold; Silk Green; Silk Purple; Silk Red; Silk Silver; Silk White

**`inland_tpu`** — Inland TPU 95A (TPU, load 225°C) — 5 colours

> Black; Blue; Red; Transparent; White


### Overture — `overture.cfg`

brand key: `overture`

**`overture_asa`** — Overture ASA (ASA, load 250°C) — 4 colours

> Black; Grey; Red; White

**`overture_petg`** — Overture PETG (PETG, load 240°C) — 7 colours

> Black; Blue; Green; Grey; Red; Transparent; White

**`overture_pla`** — Overture PLA (PLA, load 205°C) — 21 colours

> Beige; Black; Blue; Brown; Cold White; Fresh Red; Gold; Green; Grey; Light Green; Magenta; Navy Blue; Orange; Pink; Purple; Red; Silver; Sky Blue; Space Grey; White; Yellow

**`overture_pla_matte`** — Overture Matte PLA (PLA, load 205°C) — 13 colours

> Matte Beige; Matte Black; Matte Blue; Matte Brown; Matte Green; Matte Grey; Matte Orange; Matte Pink; Matte Purple; Matte Red; Matte Teal; Matte White; Matte Yellow

**`overture_pla_plus`** — Overture PLA Professional (PLA, load 210°C) — 5 colours

> Black; Blue; Green; Red; White

**`overture_tpu`** — Overture TPU 95A (TPU, load 230°C) — 5 colours

> Black; Blue; Red; Transparent; White


### Polymaker — `polymaker.cfg`

brand key: `polymaker`

**`polyflex_tpu90`** — PolyFlex TPU90 (TPU, load 215°C) — 2 colours

> Black; White

**`polyflex_tpu95`** — PolyFlex TPU95 (TPU, load 220°C) — 5 colours

> Black; Blue; Clear Natural; Red; White

**`polyflex_tpu95_hf`** — PolyFlex TPU95-HF (TPU, load 225°C) — 3 colours

> Black; Red; White

**`polylite_abs`** — PolyLite ABS (ABS, load 245°C) — 6 colours

> Black; Blue; Galaxy Black; Grey; Red; White

**`polylite_asa`** — PolyLite ASA (ASA, load 250°C) — 6 colours

> Black; Blue; Galaxy Black; Grey; Red; White

**`polylite_pla`** — PolyLite PLA (PLA, load 210°C) — 15 colours

> Black; Blue; Galaxy Black; Galaxy Blue; Galaxy Purple; Gold; Green; Grey; Orange; Pink; Purple; Red; Silver; White; Yellow

**`polylite_pla_pro`** — PolyLite PLA Pro (PLA, load 215°C) — 9 colours

> Black; Blue; Green; Magenta; Orange; Pink; Purple; Red; White

**`polymaker_petg`** — Polymaker™ PETG (PETG, load 250°C) — 11 colours

> Black; Blue; Gold; Green; Grey; Orange; Pink; Purple; Red; White; Yellow

**`polymax_pc`** — PolyMax PC (PC, load 270°C) — 3 colours

> Black; Translucent; White

**`polymax_petg`** — PolyMax PETG (PETG, load 245°C) — 2 colours

> Black; White

**`polymax_pla`** — PolyMax PLA (PLA, load 215°C) — 5 colours

> Black; Blue; Grey; Red; White

**`polyterra_pla`** — PolyTerra PLA (PLA, load 200°C) — 14 colours

> Arctic Teal; Army Beige; Blue Ocean; Coal Black; Coffee Brown; Green Forest; Grey Concrete; Natural; Orange; Pink Cotton; Purple Lavender; Red Mars; White Ivory; Yellow Savanna


### Polymaker Panchroma™ — `polymaker_panchroma.cfg`

brand key: `polymaker_panchroma`

**`panchroma_basic`** — Panchroma™ Basic PLA (PLA, load 210°C) — 28 colours

> Aqua Blue; Azure Blue; Beige; Black; Blue; Brown; Cold White; Cream; Dark Grey; Dark Olive Drab; Green; Grey; Jungle Green; Lemon Yellow; Lime Green; Magenta; Olive Green; Orange; Pink; Polymaker Teal; Purple; Red; Steel Grey; Stone Blue; Tan; White; Wine Red; Yellow

**`panchroma_celestial`** — Panchroma™ Celestial PLA (PLA, load 210°C) — 7 colours

> Celestial Blue; Celestial Green; Celestial Light Pink; Celestial Light Yellow; Celestial Purple; Celestial White; Celestial Yellow

**`panchroma_cope`** — Panchroma™ CoPE (CoPE, load 215°C) — 24 colours

> Aqua Blue; Beige; Black; Blue; Brown; Cold White; Cream; Dark Grey; Grey; Jungle Green; Lemon Yellow; Lime Green; Magenta; Olive Green; Orange; Pink; Purple; Red; Steel Grey; Stone Blue; Tan; White; Wine Red; Yellow

**`panchroma_dual_matte`** — Panchroma™ Dual Matte PLA (PLA, load 205°C) — 5 colours

> Camouflage; Chameleon; Flamingo; Shadow Black; Sunrise

**`panchroma_dual_silk`** — Panchroma™ Dual Silk PLA (PLA, load 210°C) — 9 colours

> Aubergine; Banquet; Beluga; Caribbean Sea; Chameleon; Crown; Jadeite; Sovereign; Sunset

**`panchroma_dual_special`** — Panchroma™ Dual Special PLA (PLA, load 210°C) — 1 colours

> Yin-Yang

**`panchroma_galaxy`** — Panchroma™ Galaxy PLA (PLA, load 210°C) — 5 colours

> Galaxy Black; Galaxy Dark Blue; Galaxy Dark Green; Galaxy Dark Grey; Galaxy Dark Red

**`panchroma_glow`** — Panchroma™ Glow PLA (PLA, load 210°C) — 2 colours

> Glow Blue; Glow Green

**`panchroma_gradient_galaxy`** — Panchroma™ Gradient Galaxy PLA (PLA, load 210°C) — 3 colours

> Black-Blue; Black-Grey; Blue-Green

**`panchroma_gradient_matte`** — Panchroma™ Gradient Matte PLA (PLA, load 205°C) — 11 colours

> Cappuccino; Fall; Lavender Fizz; Mint Splash; Pastel Rainbow; Sky; Spring; Summer; Tropical Squeeze; Winter; Wood

**`panchroma_gradient_satin`** — Panchroma™ Gradient Satin PLA (PLA, load 205°C) — 1 colours

> Rainbow

**`panchroma_gradient_silk`** — Panchroma™ Gradient Silk PLA (PLA, load 210°C) — 5 colours

> Silk Air; Silk Earth; Silk Fire; Silk Rainbow; Silk Water

**`panchroma_gradient_translucent`** — Panchroma™ Gradient Translucent PLA (PLA, load 205°C) — 1 colours

> Translucent Rainbow

**`panchroma_luminous`** — Panchroma™ Luminous PLA (PLA, load 210°C) — 5 colours

> Luminous Blue; Luminous Green; Luminous Orange; Luminous Pink; Luminous Yellow

**`panchroma_marble`** — Panchroma™ Marble PLA (PLA, load 205°C) — 5 colours

> Brick; Limestone; Marble White; Sandstone; Slate Grey

**`panchroma_matte`** — Panchroma™ Matte PLA (PLA, load 205°C) — 38 colours

> Arctic Teal; Army Beige; Army Blue; Army Brown; Army Dark Green; Army Light Green; Army Purple; Army Red; Ash Grey; Charcoal Black; Cotton White; Earth Brown; Electric Indigo; Forest Green; Fossil Grey; Lava Red; Lavender Purple; Lime Green; Lotus Pink; Muted Blue; Muted Green; Muted Purple; Muted Red; Muted White; Pastel Banana; Pastel Candy; Pastel Ice; Pastel Mint; Pastel Peach; Pastel Peanut; Pastel Periwinkle; Pastel Watermelon; Sakura Pink; Sapphire Blue; Savannah Yellow; Sky Blue; Sunrise Orange; Wood Brown

**`panchroma_metallic`** — Panchroma™ Metallic PLA (PLA, load 210°C) — 4 colours

> Metallic Blue; Metallic Bronze; Metallic Gold; Metallic Silver

**`panchroma_neon`** — Panchroma™ Neon PLA (PLA, load 210°C) — 5 colours

> Neon Green; Neon Magenta; Neon Orange; Neon Pink; Neon Yellow

**`panchroma_satin`** — Panchroma™ Satin PLA (PLA, load 205°C) — 10 colours

> Black; Blue; Green; Grey; Orange; Purple; Red; Teal; White; Yellow

**`panchroma_silk`** — Panchroma™ Silk PLA (PLA, load 210°C) — 24 colours

> Silk Black; Silk Blue; Silk Brass; Silk Bronze; Silk Chrome; Silk Dark Blue; Silk Gold; Silk Green; Silk Gunmetal Grey; Silk Light Blue; Silk Lime; Silk Magenta; Silk Orange; Silk Peridot Green; Silk Periwinkle; Silk Purple; Silk Quartz Pink; Silk Red; Silk Rose; Silk Rose Gold; Silk Silver; Silk Teal; Silk White; Silk Yellow

**`panchroma_starlight`** — Panchroma™ Starlight PLA (PLA, load 210°C) — 11 colours

> Aurora; Comet; Jupiter; Mars; Mercury; Meteor; Midnight; Nebula; Neptune; Pulsar; Twilight

**`panchroma_translucent`** — Panchroma™ Translucent PLA (PLA, load 205°C) — 5 colours

> Cyan; Grey; Magenta; Natural; Yellow

**`panchroma_uv_shift`** — Panchroma™ UV Shift PLA (PLA, load 210°C) — 1 colours

> Natural/Orange (UV Shift)


### Prusament — `prusament.cfg`

brand key: `prusament`

**`prusament_asa`** — Prusament ASA (ASA, load 255°C) — 5 colours

> Jet Black; Olive Green; Prusa Orange; Prusa Pro Green; Signal White

**`prusament_pc_blend`** — Prusament PC Blend (PC, load 275°C) — 4 colours

> Jet Black; Prusa Orange; Prusa Pro Green; Urban Grey

**`prusament_petg`** — Prusament PETG (PETG, load 240°C) — 9 colours

> Anthracite Grey; Jet Black; Prusa Orange; Red; Signal White; Sky Blue; Transparent; Transparent Blue; Urban Grey

**`prusament_pla`** — Prusament PLA (PLA, load 215°C) — 16 colours

> Anthracite Grey; Chalky Blue; Galaxy Blue; Jet Black; Lipstick Red; Mystic Purple; Noctua Beige; Noctua Brown; Pink; Pistachio Green; Pristine White; Prusa Orange; Prusa Pro Green; Royal Blue; Signal Yellow; Urban Grey

**`prusament_pvb`** — Prusament PVB (PVB, load 215°C) — 4 colours

> Dark Blue; Light Yellow; Natural; Prusa Orange

**`prusament_tpu95a`** — Prusament TPU 95A (TPU, load 220°C) — 2 colours

> Jet Black; Natural


### SunLu — `sunlu.cfg`

brand key: `sunlu`

**`sunlu_asa`** — SunLu ASA (ASA, load 250°C) — 4 colours

> Black; Grey; Red; White

**`sunlu_petg`** — SunLu PETG (PETG, load 230°C) — 7 colours

> Black; Blue; Green; Grey; Red; Transparent; White

**`sunlu_pla_plus`** — SunLu PLA+ (PLA, load 210°C) — 12 colours

> Beige; Black; Blue; Brown; Green; Grey; Orange; Pink; Purple; Red; White; Yellow

**`sunlu_pla_silk`** — SunLu PLA Silk (PLA, load 215°C) — 10 colours

> Silk Black; Silk Blue; Silk Copper; Silk Gold; Silk Green; Silk Purple; Silk Rainbow; Silk Red; Silk Silver; Silk White

**`sunlu_tpu95a`** — SunLu TPU 95A (TPU, load 215°C) — 5 colours

> Black; Blue; Red; Transparent; White


### VoxelPLA — `voxelpla.cfg`

brand key: `voxelpla`

**`voxelpla_petg`** — VoxelPLA PETG (PETG, load 240°C) — 5 colours

> Black; Blue; Red; Transparent; White

**`voxelpla_pla_color_change`** — VoxelPLA Color Change PLA (PLA, load 200°C) — 3 colours

> Blue to White; Green to Yellow; Purple to Pink

**`voxelpla_pla_glow`** — VoxelPLA Glow in the Dark PLA (PLA, load 205°C) — 3 colours

> Glow Blue; Glow Green; Glow Yellow

**`voxelpla_pla_matte`** — VoxelPLA PLA Matte (PLA, load 205°C) — 8 colours

> Matte Black; Matte Blue; Matte Green; Matte Grey; Matte Orange; Matte Purple; Matte Red; Matte White

**`voxelpla_pla_pro`** — VoxelPLA PLA Pro (PLA, load 205°C) — 10 colours

> Black; Blue; Green; Grey; Orange; Pink; Purple; Red; White; Yellow

**`voxelpla_pla_silk`** — VoxelPLA PLA Silk (PLA, load 215°C) — 7 colours

> Silk Blue; Silk Copper; Silk Gold; Silk Purple; Silk Red; Silk Rose Gold; Silk Silver


### ZYLtech — `zyltech.cfg`

brand key: `zyltech`

**`zyltech_abs`** — ZYLtech ABS (ABS, load 240°C) — 5 colours

> Black; Blue; Grey; Red; White

**`zyltech_asa`** — ZYLtech ASA (ASA, load 245°C) — 4 colours

> Black; Grey; Red; White

**`zyltech_petg`** — ZYLtech PETG (PETG, load 240°C) — 7 colours

> Black; Blue; Green; Grey; Red; Transparent; White

**`zyltech_pla`** — ZYLtech PLA (PLA, load 200°C) — 18 colours

> Black; Blue; Brown; Dark Grey; Gold; Green; Grey; Light Blue; Light Green; Navy; Orange; Pink; Purple; Red; Silver; Teal; White; Yellow

**`zyltech_pla_plus`** — ZYLtech PLA+ (PLA, load 210°C) — 6 colours

> Black; Blue; Green; Grey; Red; White

**`zyltech_tpu`** — ZYLtech TPU 95A (TPU, load 220°C) — 3 colours

> Black; Transparent; White


