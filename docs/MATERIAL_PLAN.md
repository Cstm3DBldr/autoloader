# Material plan — load and unload, every material in the database

Written 2026-10-13 from two research passes and everything this printer has
measured. Mike: "before we run any tests go do research ... so we arent testing
blind ... build out a plan for all of them as a load sequence". **This is a
plan, not a calibration.** Only PLA, PETG and (partly) ASA are measured here;
every other number is a starting point with its source.

Sources are listed at the end and referenced in brackets. "(S)" means the
figure came from a search excerpt the researcher could not open.

## 1. What the research changed

1. **Nobody else forms tips as cold as we do.** Prusa's MMU profiles form at
   the full print temperature with a fast ram first; Happy Hare and skinnydip
   ship with no temperature drop; the coolest published ASA/ABS unload is 215C
   from one forum script [PRUSA-INI, HH-VARS, SKINNY, CORE-ONE]. Our forming
   temperatures sit 45-65C below print temperature. That works for PLA and
   PETG on this machine (measured, repeatable over 5 reloads), so it stays for
   them — but ASA is where the cold approach has not converged.
2. **Prusa treats ASA specially, and slowly.** Verified in PrusaResearch
   2.5.11.ini: `Prusament ASA @MMU` overrides its ABS parent with **one
   cooling move at 3 -> 2 mm/s**; the ABS parent uses 5 moves at 10 -> 50 mm/s
   (our direction). The MK4 MMU3 ABS/ASA/PC profile (`*ABSPG*`) uses **3 moves
   at 5 -> 2.5 mm/s**, a 45mm "stamp" and a fast ~42 mm3/s ram. Our cooling
   moves ACCELERATE (10 -> 50); Prusa's ASA ones decelerate and are 10x slower.
   This is the strongest untried lever for ASA.
3. **Skinnydip lost to "stamping" at Prusa.** Prusa's developer said
   skinnydip "did not improve reliability"; stamping replaced it in
   PrusaSlicer 2.7.3, and only works "preceded by very rapid ramming"
   [PS-2385, PS-273]. Our dips (20mm, then 28mm + 0.5s) ran with no ram.
4. **A forming-temperature rule that fits our data: Tg + ~100C.** PLA 61+104
   = 165, PETG 81+104 = 185, ASA 98+97 = 195 [PM-PLA, PM-PETG, PM-ASA]. The
   rule `parameters.cfg` uses for untuned rows (print temperature - 48) misses
   by 15-20C. Three points is a hypothesis, not a law; it cannot apply to TPU
   (Tg ~ -25C) and probably not to semicrystalline nylon (PA-CF).
5. **Some materials should not auto-load at all.** Bambu marks TPU (below
   68D) and its own PA6-CF "not compatible" with the AMS; Prusa hides flexible
   profiles from MMU printers [BBL-WIKI, BBL-PA6, PRUSA-INI].

## 2. The sequence that stays

Unchanged unless a material below says otherwise (`parameters.cfg`):

| Stage | Standard |
|---|---|
| Load | sensor-stopped blast at `encoder_max_speed` to the extruder sensor; sync feed to the toolhead sensor; fill + purge at the profile's load temperature, verified by the encoder (fail under 80%, one automatic retry) |
| Cool | to the per-material forming temperature |
| Sever | one 38mm pull at 70mm/s (capped 10mm short of each toolhead's sensor), back down to the cooling zone at 35mm |
| Cooling moves | 2 x 10mm, 10 -> 50mm/s |
| Clear | out past the melt to 5mm short of the gears at 8mm/s, heater off |
| Unload | pull clear of the extruder sensor, sensor-stopped zero, 95% blast back, encoder park |

## 3. Per-material plan

Forming start = the Tg rule unless measured. Load temperature = top half of
the manufacturer range (a load has to melt a cold strand fast).

| Material | Print range | Tg | Load temp | Forming temp | Status / handling |
|---|---|---|---|---|---|
| **PLA** | 190-230 [PM-PLA] | 61 | 205 (profile) | **165 measured** | Done: clean, no swell, 5/5 reloads. Reference material |
| **PETG** | 230-260 [PM-PETG] | 81 | 250 (profile) | **185 measured** (180 shears) | Done: 5/5 reloads. Window is narrow |
| **ASA** | 230-260 [PM-ASA] | 98 | 250 | 190-195 measured, **strings** | In progress — section 4 |
| ABS | 245-265 [PM-ABS] | 101 | 250-255 | ~200 (row: 202) | Next after ASA: same family, checks whether ASA's answer transfers. Dry 70C/6h |
| CoPE (Polymaker Panchroma CoPE) | 190-230 [PM-CoPE] | **58** [PM-CoPE-FR] | 210-215 | **~160 by Tg** vs 182 in the row (by family) | **The decisive experiment for the Tg rule**: a copolyester with a PLA-like Tg. Near the 150C floor |
| coPETG | nGen 220-240, XT 240-260, HT 250-280 (S) | nGen 85, HT >100 | 230 / 250 / 265 | nGen ~185; HT ~200 | One row cannot serve three resins; HT likely needs its own. Per product line, not per material (`docs/TIPFORM_CAL.md`) |
| PVB | 190-220 [PM-PVB] | 70 | 210-215 | ~170 (row: 167) | **Dry first** (very hygroscopic, 45-50C). "Similar to PLA" [PRUSA-KB-PVB] |
| PC | 250-270 [PM-PC] | **113** [PM-PC] | 260-270 | **~215 by Tg** (row: 232) | Dry 75-80C/6-8h, "required". The row's note "Tg ~147" is bulk PC, not the PolyMax/PolyLite PC we stock |
| PLA-CF | 190-230 [PM-PLACF] | 62 | 220-230 | ~165 (row: 167) | **Load slowly; hardened path.** Abrasive: wears PTFE and gears [BBL-WIKI]. Our one shared drive gear and the encoder wheels touch it. Re-check the encoder calibration after |
| PA-CF | 260-300 [BBL-PA6, FIB-PA6] | 68-74 (Tm ~220, Tc ~185) | ~280 | keep 232 (above Tm); Tg rule does not apply | **Not supported for auto-load** unless the path is hardened and the spool is dry (2.35% water at saturation). Bambu: "too brittle" and "too hard and rough" for the AMS |
| TPU 95A | 210-230 [PM-TPU95] | ~ -25 | 220-225 | n/a | **Experimental, slow only.** No source gives a safe Bowden speed; compression will make the encoder and stepper disagree |
| TPU 90A / 85A | — | — | — | — | **Not supported.** Too soft for any Bowden autoloader [BBL-WIKI, PRUSA-FLEX] |

## 4. ASA — the experiment ladder

Measured so far (T0 and T2, PolyLite ASA, 38mm sever unless stated): 208, 200,
195 and 190C all string with the standard; a 20mm dip cleared 1/5, a 28mm
dip + 0.5s cleared 3/5; a fast 50mm/s exit was worse and snapped a tip.
Strings worsen over back-to-back cycles.

Ranked by evidence, cheapest first. Mike watches each run for strings.

1. **Prusa's ASA cooling moves — slow and decelerating.** No code change:
   `SA_TIP_CYCLE TOOL=0 TEMP=195 COOL_MOVES=3 COOL_LEN=15 COOL_IN=5 COOL_OUT=2.5`
   (Prusa's MMU3 numbers; COOL_LEN kept at 15, not Prusa's 20, because our
   moves go DOWN from the 35mm cooling zone and 20 would reach 15mm above the
   nozzle.) If promising, try Prusa's MMU2S ASA value: `COOL_MOVES=1 COOL_IN=3
   COOL_OUT=2`.
2. **Part-cooling fan during forming.** Happy Hare's fan assist defaults to
   50%; the Core One script uses full fan [HH-VARS, CORE-ONE]. Needs a small
   code change (fan on for the form, off after). Also the cheapest heat-soak
   counter.
3. **Prusa's whole sequence, hot.** Form at the print temperature (250) with
   a fast ram (~22mm at ~17.6mm/s), decelerating separation, the slow cooling
   moves, and a full-depth stamp after the ram. Needs code: multi-stage
   separation and a stamp allowed to the nozzle. Biggest change, strongest
   precedent.
4. **Load side.** Raise the extruder's current during the fill, as Prusa's
   `high_current_on_filament_swap` does "to overcome resistance when loading a
   filament with an ugly shaped tip" [PS-CONFIG]. Our fill already enters the
   melt slowly (~4mm/s), which matches Prusa's slow final approach.
5. **Fallback: cut instead of form.** BoxTurtle and Happy Hare's EREC cut at
   the gate; one cutter on our selector carriage could serve all six lanes,
   and every reload would start from a clean cut. Hardware; only if 1-4 fail.

## 5. Heat soak — the cycle 4/5 failures

Every reload failure in `SA_TIP_CYCLE` to date came on cycle 4 or 5, none on
1-3 (TODO). Research found no documented threshold but indirect support:
strings building up over 10-20 changes, heat creep from a warm extruder
stepper, Prusa holding the heatbreak to a per-material target (40C for ABS/ASA
vs 36C for PLA/PETG) [PRUSA-INI, MMU2-FORUM].

- `SA_TIP_CYCLE TOOL=2 HOLD=120` with PLA (queued): if cycles 4-5 stop
  failing with 2-minute rests, heat soak is confirmed.
- Then: fan during forming (item 2 above), and a rest between loads in real
  use (a print never reloads the same head five times in ten minutes, but an
  MMU-style multi-channel head would).

## 6. Test order

1. Heat soak, PLA on T2 (`HOLD=120`) — separates heat soak from material.
2. ASA ladder, items 1 then 2 (section 4).
3. ABS at ~200 — does ASA's answer transfer?
4. CoPE at 160 vs 182 — settles the Tg rule.
5. coPETG (nGen), PVB (dried), PC (dried, ~215).
6. PLA-CF — only after confirming the drive gear, extruder gears and nozzle are
   hardened; then re-calibrate the encoder.
7. PA-CF and TPU — not at all until marked supported.

## 7. Changes this plan implies (awaiting Mike's go)

1. `parameters.cfg`: correct the PC note (Tg 113 for PolyMax/PolyLite PC, not
   147); record the Tg + 100 hypothesis beside the untuned rows; update the
   ASA row's note to the later results (it still says "no string" from T2).
2. A per-material **auto-load support level** — supported / load slowly /
   not supported — that the load honours: slow means the blast runs at
   `feed_speed`, not supported means it refuses with a reason. This is the same
   speed switch as the requested high-speed toggle (TODO), keyed per material.
3. Optional **fan assist** during tip forming (off by default).
4. Optional **ram + full-depth stamp** and **multi-stage separation** for a
   Prusa-style sequence (off by default).
5. Optional **extruder current boost** during the fill (off by default).

## Sources

- [PRUSA-INI] PrusaResearch 2.5.11.ini — https://github.com/prusa3d/PrusaSlicer-settings-prusa-fff/blob/main/PrusaResearch/2.5.11.ini (sections `Prusament ASA @MMU`, `*ABS MMU2*`, `*ABSPG*`; the ASA override verified directly 2026-10-13)
- [PS-273] PrusaSlicer 2.7.3-alpha1 release notes — https://github.com/prusa3d/PrusaSlicer/releases/tag/version_2.7.3-alpha1
- [PS-2385] https://github.com/prusa3d/PrusaSlicer/issues/2385
- [PS-CONFIG] PrusaSlicer config definitions (`high_current_on_filament_swap`, "Pause before ramming") — https://github.com/prusa3d/PrusaSlicer/blob/master/src/slic3r-domain/src/Slic3r/Domain/ConfigDefsFDM.cpp
- [HH-VARS] Happy Hare mmu_macro_vars.cfg — https://github.com/moggieuk/Happy-Hare/blob/v3/config/base/mmu_macro_vars.cfg
- [SKINNY] https://github.com/domesticatedviking/skinnydip
- [CORE-ONE] Core One MMU3 unload script thread — https://forum.prusa3d.com/forum/prusa-core-one-hardware-firmware-and-software-help/core-one-mmu3-filament-unloading-getting-stuck/paged/2/
- [MMU2-FORUM] https://forum.prusa3d.com/forum/original-prusa-i3-mmu2s-mmu2-general-discussion-announcements-and-releases/mmu2-with-e3d-revo-six-tunning-filament-tip-issue/
- [PM-PLA] [PM-PLACF] [PM-PETG] [PM-ABS] [PM-ASA] [PM-TPU95] [PM-PC] [PM-PVB] [PM-CoPE] — Polymaker wiki technical data sheets, https://wiki.polymaker.com/polymaker-products/more-about-our-products/documents/technical-data-sheets/
- [PM-CoPE-FR] https://shop.polymaker.com/fr/collections/thangs-x-polymaker/products/filament-cope
- [BBL-WIKI] https://wiki.bambulab.com/en/general/filament-guide-material-table
- [BBL-PA6] https://us.store.bambulab.com/products/pa6-cf
- [FIB-PA6] Fiberon PA6-CF20 TDS — https://cdn.shopify.com/s/files/1/0548/7299/7945/files/TDS_FIBERON_PA6-CF20_V1.1_EN.pdf
- [PRUSA-KB-PVB] https://help.prusa3d.com/article/pvb_196708
- [PRUSA-FLEX] https://help.prusa3d.com/article/flexible-materials_2057
