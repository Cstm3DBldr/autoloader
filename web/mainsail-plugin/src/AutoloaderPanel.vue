<template>
    <div>
        <!-- MAIN PANEL -->
        <v-card-text v-if="saExists" class="pa-0">
                <!-- Calibration toolbar — mirrors KlipperScreen's calibration panel -->
                <div class="sa-cal-bar">
                    <v-btn small outlined class="sa-cal-btn" @click="openCalibration">
                        <v-icon size="16" left>{{ mdiCogOutline }}</v-icon>
                        {{ $t('Panels.AutoloaderPanel.CalibrationGuide') }}
                    </v-btn>
                </div>

                <!-- Status strip — machine state at a glance, above the per-path table.
                     The table answers "what is in each path"; this answers "what is the
                     mechanism doing right now", which otherwise takes reading several
                     rows and the dialogs to work out. -->
                <div class="sa-status-strip">
                    <div v-for="item in statusItems" :key="item.key" class="sa-status-cell">
                        <span class="sa-status-label">{{ item.label }}</span>
                        <span class="sa-status-value" :class="item.accent ? 'sa-status-value--accent' : null">
                            {{ item.value }}
                            <span v-if="item.sub" class="sa-status-sub">{{ item.sub }}</span>
                        </span>
                    </div>
                </div>

                <!-- Grid: header + path rows -->
                <div class="sa-grid">
                    <!-- Header row -->
                    <div class="sa-row sa-header-row">
                        <div class="sa-center">{{ $t('Panels.AutoloaderPanel.ColToolheadPath') }}</div>
                        <div></div>
                        <div>{{ $t('Panels.AutoloaderPanel.ColMaterial') }}</div>
                        <div class="sa-center">{{ $t('Panels.AutoloaderPanel.ColLoadout') }}</div>
                        <v-tooltip bottom>
                            <template #activator="{ on }">
                                <div class="sa-center" v-on="on">EN</div>
                            </template>
                            <span>{{ $t('Panels.AutoloaderPanel.Entry') }}</span>
                        </v-tooltip>
                        <v-tooltip bottom>
                            <template #activator="{ on }">
                                <div class="sa-center" v-on="on">EX</div>
                            </template>
                            <span>{{ $t('Panels.AutoloaderPanel.Extruder') }}</span>
                        </v-tooltip>
                        <v-tooltip bottom>
                            <template #activator="{ on }">
                                <div class="sa-center" v-on="on">TH</div>
                            </template>
                            <span>{{ $t('Panels.AutoloaderPanel.Toolhead') }}</span>
                        </v-tooltip>
                    </div>

                    <!-- Data rows -->
                    <div
                        v-for="i in saPathIndices"
                        :key="i"
                        :class="[
                            'sa-row',
                            'sa-data-row',
                            { 'sa-row--active': saStatus.current_path === i },
                            { 'sa-row--open': pathModalOpen && pathModalIdx === i },
                        ]"
                        @click="openPathModal(i)">
                        <!-- Tool label -->
                        <div class="sa-tool-label sa-center">T{{ i }}</div>

                        <!-- Color swatch (single or multi-color) -->
                        <div class="sa-swatch-cell">
                            <!-- Tri+ → SVG pie (avoids conic-gradient AA bleed at small sizes) -->
                            <svg
                                v-if="saColorMode(i) === 'multi'"
                                class="sa-color-swatch sa-color-swatch--svg"
                                viewBox="0 0 36 36">
                                <path
                                    v-for="(slice, k) in saPieSlices(i)"
                                    :key="k"
                                    :d="slice.d"
                                    :fill="slice.fill" />
                                <circle
                                    cx="18"
                                    cy="18"
                                    r="17.25"
                                    fill="none"
                                    :stroke="saSwatchBorderColor(i)"
                                    stroke-width="1.5" />
                            </svg>
                            <!-- Dual → SVG semicircles (no linear-gradient hard-stop bleed) -->
                            <svg
                                v-else-if="saColorMode(i) === 'dual'"
                                class="sa-color-swatch sa-color-swatch--svg"
                                viewBox="0 0 36 36">
                                <path
                                    v-for="(slice, k) in saDualSlices(i)"
                                    :key="k"
                                    :d="slice.d"
                                    :fill="slice.fill" />
                                <circle
                                    cx="18"
                                    cy="18"
                                    r="17.25"
                                    fill="none"
                                    :stroke="saSwatchBorderColor(i)"
                                    stroke-width="1.5" />
                            </svg>
                            <div
                                v-else
                                class="sa-color-swatch"
                                :style="{
                                    background: saColorBackground(i) || 'transparent',
                                    border: saColorBackground(i)
                                        ? `1px solid ${saSwatchBorderColor(i)}`
                                        : '1px solid rgba(255,255,255,0.25)',
                                }" />
                        </div>

                        <!-- Material / brand / color name -->
                        <div class="sa-material-cell">
                            <div class="caption">
                                <span v-if="saStatus.path_materials[i]">
                                    {{ saStatus.path_materials[i] }}
                                    <span v-if="saStatus.path_brands[i]" class="grey--text">
                                        · {{ saStatus.path_brands[i] }}
                                    </span>
                                </span>
                                <span v-else class="grey--text text--darken-1">—</span>
                            </div>
                            <div v-if="saStatus.path_color_names[i]" class="caption grey--text">
                                {{ saStatus.path_color_names[i] }}
                            </div>
                        </div>

                        <!-- Loadout badge -->
                        <div class="sa-center">
                            <v-chip x-small :color="saStateColor(saEffectiveState(i))" dark>
                                {{ saEffectiveState(i) }}
                            </v-chip>
                        </div>

                        <!-- Sensor dots -->
                        <div class="sa-center">
                            <div
                                class="sa-dot"
                                :class="saStatus.entry_filament[i] ? 'sa-dot--on' : 'sa-dot--off'" />
                        </div>
                        <div class="sa-center">
                            <div
                                class="sa-dot"
                                :class="saStatus.extruder_filament[i] ? 'sa-dot--on' : 'sa-dot--off'" />
                        </div>
                        <div class="sa-center">
                            <div
                                class="sa-dot"
                                :class="saStatus.toolhead_filament[i] ? 'sa-dot--on' : 'sa-dot--off'" />
                        </div>
                    </div>
                </div>

            </v-card-text>

        <!-- ─── CONTROLS DIALOG ─────────────────────────────────── -->
        <v-dialog v-model="pathModalOpen" width="400" :retain-focus="false">
            <v-card v-if="pathModalIdx !== null" class="panel sa-dialog">
                <!-- ─── CONTROLS VIEW ──────────────────────────────── -->
                <template v-if="pathView === 'controls'">
                <v-toolbar dense flat class="panel-toolbar sa-dialog-title">
                    <v-icon left size="18">{{ saFilamentIcon }}</v-icon>
                    <span class="sa-dialog-heading">
                        T{{ pathModalIdx }} — {{ $t('Panels.AutoloaderPanel.Controls') }}
                    </span>
                    <v-spacer />
                    <v-btn icon small @click="pathModalOpen = false">
                        <v-icon size="18">{{ mdiClose }}</v-icon>
                    </v-btn>
                </v-toolbar>
                <v-divider />
                <v-card-text class="pa-3">
                    <!-- Current profile tile (clickable → opens profile editor) -->
                    <div class="sa-profile-tile mb-3" @click="openProfile">
                        <div
                            class="sa-color-swatch-lg sa-profile-tile-swatch"
                            :style="{
                                background: saColorBackground(pathModalIdx) || 'transparent',
                                border: saColorBackground(pathModalIdx)
                                    ? `1px solid ${saSwatchBorderColor(pathModalIdx)}`
                                    : '2px dashed rgba(255,255,255,0.25)',
                            }" />
                        <div class="sa-profile-tile-info">
                            <div v-if="saStatus.path_materials[pathModalIdx]" class="body-2">
                                {{ saStatus.path_materials[pathModalIdx] }}
                                <span v-if="saStatus.path_brands[pathModalIdx]" class="grey--text">
                                    · {{ saStatus.path_brands[pathModalIdx] }}
                                </span>
                            </div>
                            <div v-else class="body-2 grey--text">
                                {{ $t('Panels.AutoloaderPanel.NoProfile') }}
                            </div>
                            <div
                                v-if="saStatus.path_color_names[pathModalIdx]"
                                class="caption grey--text">
                                {{ saStatus.path_color_names[pathModalIdx] }}
                            </div>
                            <div v-else class="caption grey--text">
                                {{ $t('Panels.AutoloaderPanel.EditProfile') }}
                            </div>
                        </div>
                        <v-icon small class="sa-profile-tile-icon">{{ mdiPencil }}</v-icon>
                    </div>

                    <div class="caption grey--text mb-1">
                        {{ $t('Panels.AutoloaderPanel.Selector') }}
                    </div>
                    <div class="sa-btn-group mb-3">
                        <v-btn
                            small
                            class="sa-group-btn"
                            :class="{
                                'sa-group-btn--primary': isSelectorHomed,
                                'sa-group-btn--warning': !isSelectorHomed,
                            }"
                            @click="saGcode('SA_HOME')">
                            {{ $t('Panels.AutoloaderPanel.Home') }}
                        </v-btn>
                        <v-btn
                            small
                            class="sa-group-btn"
                            :class="{ 'sa-group-btn--primary': isServoEngaged }"
                            :disabled="!isSelectorHomed"
                            @click="doEngage">
                            {{ $t('Panels.AutoloaderPanel.Engage') }}
                        </v-btn>
                        <v-btn
                            small
                            class="sa-group-btn"
                            :class="{ 'sa-group-btn--primary': !isServoEngaged }"
                            @click="saGcode('SA_DISENGAGE')">
                            {{ $t('Panels.AutoloaderPanel.Disengage') }}
                        </v-btn>
                    </div>

                    <!-- Manual feed / retract -->
                    <div class="caption grey--text mb-1">
                        {{ $t('Panels.AutoloaderPanel.FeedRetract') }}
                    </div>
                    <v-row dense class="mb-2">
                        <v-col>
                            <v-text-field
                                v-model.number="feedDistance"
                                :label="$t('Panels.AutoloaderPanel.Distance')"
                                type="number"
                                dense
                                outlined
                                hide-details
                                suffix="mm" />
                            <div class="sa-btn-group mt-2">
                                <v-btn
                                    v-for="d in feedDistancePresets"
                                    :key="d"
                                    small
                                    class="sa-group-btn sa-preset-btn"
                                    :class="{ 'sa-preset-btn--active': feedDistance === d }"
                                    @click="feedDistance = d">
                                    {{ d }}
                                </v-btn>
                            </div>
                        </v-col>
                        <v-col>
                            <v-text-field
                                v-model.number="feedSpeed"
                                :label="$t('Panels.AutoloaderPanel.Speed')"
                                type="number"
                                dense
                                outlined
                                hide-details
                                suffix="mm/s" />
                            <div class="sa-btn-group mt-2">
                                <v-btn
                                    v-for="s in feedSpeedPresets"
                                    :key="s"
                                    small
                                    class="sa-group-btn sa-preset-btn"
                                    :class="{ 'sa-preset-btn--active': feedSpeed === s }"
                                    @click="feedSpeed = s">
                                    {{ s }}
                                </v-btn>
                            </div>
                        </v-col>
                    </v-row>
                    <div class="d-flex mb-3">
                        <v-btn
                            small
                            class="sa-feed-btn flex-grow-1 mr-2"
                            :loading="busyAction === 'retract'"
                            @click="doRetract">
                            <v-icon small class="mr-1">{{ mdiArrowUpBold }}</v-icon>
                            {{ $t('Panels.AutoloaderPanel.Retract') }}
                        </v-btn>
                        <v-btn
                            small
                            class="sa-feed-btn flex-grow-1"
                            :loading="busyAction === 'feed'"
                            @click="doFeed">
                            <v-icon small class="mr-1">{{ mdiArrowDownBold }}</v-icon>
                            {{ $t('Panels.AutoloaderPanel.Feed') }}
                        </v-btn>
                    </div>

                    <div class="d-flex align-center mb-3">
                        <span class="caption grey--text mr-2">
                            {{ $t('Panels.AutoloaderPanel.Sensors') }}:
                        </span>
                        <v-tooltip bottom>
                            <template #activator="{ on }">
                                <div
                                    class="sa-dot mr-1"
                                    :class="saStatus.entry_filament[pathModalIdx] ? 'sa-dot--on' : 'sa-dot--off'"
                                    v-on="on" />
                            </template>
                            <span>{{ $t('Panels.AutoloaderPanel.Entry') }}</span>
                        </v-tooltip>
                        <v-tooltip bottom>
                            <template #activator="{ on }">
                                <div
                                    class="sa-dot mr-1"
                                    :class="saStatus.extruder_filament[pathModalIdx] ? 'sa-dot--on' : 'sa-dot--off'"
                                    v-on="on" />
                            </template>
                            <span>{{ $t('Panels.AutoloaderPanel.Extruder') }}</span>
                        </v-tooltip>
                        <v-tooltip bottom>
                            <template #activator="{ on }">
                                <div
                                    class="sa-dot mr-2"
                                    :class="saStatus.toolhead_filament[pathModalIdx] ? 'sa-dot--on' : 'sa-dot--off'"
                                    v-on="on" />
                            </template>
                            <span>{{ $t('Panels.AutoloaderPanel.Toolhead') }}</span>
                        </v-tooltip>
                        <v-chip x-small :color="saStateColor(saEffectiveState(pathModalIdx))" dark>
                            {{ saEffectiveState(pathModalIdx) }}
                        </v-chip>
                    </div>

                    <div class="d-flex">
                        <v-btn
                            small
                            color="primary"
                            class="flex-grow-1 mr-2"
                            :disabled="!canLoadModal"
                            :loading="busyAction === 'load'"
                            @click="doLoad">
                            {{ $t('Panels.AutoloaderPanel.Load') }}
                        </v-btn>
                        <v-btn
                            small
                            color="error"
                            class="flex-grow-1"
                            :disabled="!canUnloadModal"
                            :loading="busyAction === 'unload'"
                            @click="doUnload">
                            {{ $t('Panels.AutoloaderPanel.Unload') }}
                        </v-btn>
                    </div>
                    <div v-if="!canLoadModal && pathModalIdx !== null" class="caption grey--text mt-1 sa-hint">
                        <span v-if="saEffectiveState(pathModalIdx) === 'loaded'">
                            {{ $t('Panels.AutoloaderPanel.AlreadyLoaded') }}
                        </span>
                        <span v-else-if="!saStatus.path_color_hexes[pathModalIdx]">
                            {{ $t('Panels.AutoloaderPanel.NoProfileSet') }}
                        </span>
                    </div>
                </v-card-text>
                </template>

                <!-- ─── PROFILE VIEW ───────────────────────────────── -->
                <template v-else>
                <v-toolbar dense flat class="panel-toolbar sa-dialog-title">
                    <span class="sa-dialog-heading">
                        T{{ pathModalIdx }} — {{ $t('Panels.AutoloaderPanel.FilamentProfile') }}
                    </span>
                    <v-spacer />
                    <v-btn icon small @click="pathModalOpen = false">
                        <v-icon size="18">{{ mdiClose }}</v-icon>
                    </v-btn>
                </v-toolbar>
                <v-divider />
                <v-card-text class="pa-3">
                    <!-- Current profile read-only summary -->
                    <div
                        v-if="pathModalIdx !== null && (saStatus.path_materials[pathModalIdx] || saStatus.path_brands[pathModalIdx] || saStatus.path_color_names[pathModalIdx])"
                        class="sa-current-profile mb-3">
                        <div class="d-flex align-center">
                            <div
                                class="sa-color-swatch-lg mr-3"
                                :style="{
                                    background: saColorBackground(pathModalIdx) || 'transparent',
                                    border: saColorBackground(pathModalIdx)
                                        ? `1px solid ${saSwatchBorderColor(pathModalIdx)}`
                                        : '2px solid rgba(255,255,255,0.25)',
                                }" />
                            <div>
                                <div class="caption grey--text">
                                    {{ $t('Panels.AutoloaderPanel.CurrentProfile') }}
                                </div>
                                <div class="body-2">
                                    <span v-if="saStatus.path_materials[pathModalIdx]">
                                        {{ saStatus.path_materials[pathModalIdx] }}
                                    </span>
                                    <span v-if="saStatus.path_brands[pathModalIdx]" class="grey--text">
                                        · {{ saStatus.path_brands[pathModalIdx] }}
                                    </span>
                                </div>
                                <div v-if="saStatus.path_color_names[pathModalIdx]" class="caption grey--text">
                                    {{ saStatus.path_color_names[pathModalIdx] }}
                                </div>
                            </div>
                        </div>
                    </div>

                    <!-- Catalog cascade: Brand → Line → Color -->
                    <v-select
                        v-model="selectedBrandPath"
                        :items="brandItems"
                        :label="$t('Panels.AutoloaderPanel.BrandSelect')"
                        :loading="loadingBrands"
                        :menu-props="{ maxHeight: 480 }"
                        item-text="display_name"
                        item-value="filepath"
                        dense
                        outlined
                        hide-details
                        clearable
                        class="mb-2"
                        @change="onBrandChange" />
                    <v-select
                        v-model="selectedLineId"
                        :items="productLineItems"
                        :label="$t('Panels.AutoloaderPanel.LineSelect')"
                        :disabled="!selectedBrandPath"
                        :loading="loadingLines"
                        :menu-props="{ maxHeight: 480 }"
                        item-text="display_name"
                        item-value="line_id"
                        dense
                        outlined
                        hide-details
                        clearable
                        class="mb-2"
                        @change="onLineChange" />
                    <v-select
                        v-model="selectedColorId"
                        :items="colorItems"
                        :label="$t('Panels.AutoloaderPanel.ColorSelect')"
                        :disabled="!selectedLineId"
                        :menu-props="{ maxHeight: 480 }"
                        item-text="name"
                        item-value="id"
                        dense
                        outlined
                        hide-details
                        clearable
                        :class="{ 'mb-3': !isCustomColor, 'mb-2': isCustomColor }"
                        @change="onColorChange">
                        <template #selection="{ item }">
                            <div class="d-flex align-center">
                                <div class="sa-dd-swatch mr-2" :style="catalogSwatchStyle(item)" />
                                {{ item.name }}
                            </div>
                        </template>
                        <template #item="{ item }">
                            <div class="d-flex align-center">
                                <div class="sa-dd-swatch mr-2" :style="catalogSwatchStyle(item)" />
                                {{ item.name }}
                            </div>
                        </template>
                    </v-select>

                    <!-- Custom color overrides (only when ✨ Custom is picked) -->
                    <div v-if="isCustomColor" class="mb-3">
                        <!-- 3-way mode slider -->
                        <div class="caption grey--text mb-1">
                            {{ $t('Panels.AutoloaderPanel.ColorMode') }}
                        </div>
                        <v-slider
                            v-model="colorModeIdx"
                            :tick-labels="colorModeLabels"
                            :max="2"
                            :min="0"
                            step="1"
                            ticks="always"
                            tick-size="6"
                            hide-details
                            class="sa-mode-slider mb-3" />

                        <!-- Clickable pie (single = full circle) -->
                        <div class="d-flex align-center mb-2">
                            <svg viewBox="-50 -50 100 100" class="sa-pie">
                                <g v-for="(slice, idx) in pieSlices" :key="idx">
                                    <circle
                                        v-if="slice.type === 'circle'"
                                        cx="0"
                                        cy="0"
                                        :r="slice.r"
                                        :fill="slice.color"
                                        :stroke="saBorderForHex(slice.color)"
                                        stroke-width="1.2"
                                        class="sa-pie-slice"
                                        @click="openPicker(idx)" />
                                    <path
                                        v-else
                                        :d="slice.d"
                                        :fill="slice.color"
                                        :stroke="saBorderForHex(slice.color)"
                                        stroke-width="1.2"
                                        class="sa-pie-slice"
                                        @click="openPicker(idx)" />
                                </g>
                            </svg>
                            <div class="ml-3 caption grey--text">
                                {{ $t('Panels.AutoloaderPanel.ClickSliceToEdit') }}
                            </div>
                        </div>

                        <v-text-field
                            v-model="editColorName"
                            :label="$t('Panels.AutoloaderPanel.ColorName')"
                            dense
                            outlined
                            hide-details />
                    </div>

                    <v-divider class="mb-3" />

                    <!-- Temperatures + purge (always editable) -->
                    <v-row dense class="mb-1">
                        <v-col>
                            <v-text-field
                                v-model.number="editLoadTemp"
                                :label="$t('Panels.AutoloaderPanel.LoadTemp')"
                                type="number"
                                dense
                                outlined
                                hide-details
                                suffix="°C" />
                        </v-col>
                        <v-col>
                            <v-text-field
                                v-model.number="editUnloadTemp"
                                :label="$t('Panels.AutoloaderPanel.UnloadTemp')"
                                type="number"
                                dense
                                outlined
                                hide-details
                                suffix="°C" />
                        </v-col>
                    </v-row>
                    <v-row dense>
                        <v-col>
                            <v-text-field
                                v-model.number="editPurgeSpeed"
                                :label="$t('Panels.AutoloaderPanel.PurgeSpeed')"
                                type="number"
                                dense
                                outlined
                                hide-details
                                suffix="mm/s" />
                        </v-col>
                        <v-col>
                            <v-text-field
                                v-model.number="editPurgeLength"
                                :label="$t('Panels.AutoloaderPanel.PurgeLength')"
                                type="number"
                                dense
                                outlined
                                hide-details
                                suffix="mm" />
                        </v-col>
                    </v-row>
                </v-card-text>
                <v-card-actions class="px-3 py-2 flex-wrap">
                    <v-btn small text @click="backToControls">
                        ← {{ $t('Panels.AutoloaderPanel.BackToControls') }}
                    </v-btn>
                    <v-spacer />
                    <v-btn
                        small
                        text
                        :disabled="!selectedLineId"
                        class="mr-1"
                        @click="resetToDefault">
                        {{ $t('Panels.AutoloaderPanel.ResetDefault') }}
                    </v-btn>
                    <v-btn
                        small
                        text
                        color="error"
                        class="mr-1"
                        :disabled="saEffectiveState(pathModalIdx) !== 'empty'"
                        @click="clearProfile">
                        {{ $t('Panels.AutoloaderPanel.ClearProfile') }}
                    </v-btn>
                    <v-btn
                        small
                        color="primary"
                        :loading="busyAction === 'save'"
                        @click="saveProfile">
                        {{ $t('Panels.AutoloaderPanel.SaveProfile') }}
                    </v-btn>
                </v-card-actions>
                </template>
            </v-card>
        </v-dialog>

        <!-- ─── CALIBRATION GUIDE DIALOG ────────────────────────── -->
        <v-dialog v-model="calOpen" width="400" :retain-focus="false" scrollable>
            <v-card class="panel sa-dialog sa-guide-card">
                <v-toolbar dense flat class="panel-toolbar sa-dialog-title">
                    <v-icon left size="18">{{ mdiInformation }}</v-icon>
                    <span class="sa-dialog-heading">
                        {{ $t('Panels.AutoloaderPanel.CalibrationShort') }}
                        — {{ $t('Panels.AutoloaderPanel.Step') }} {{ calStep + 1 }} /
                        {{ calTotalSteps }}
                    </span>
                    <v-spacer />
                    <v-btn icon small @click="closeGuide()">
                        <v-icon size="18">{{ mdiCloseThick }}</v-icon>
                    </v-btn>
                </v-toolbar>
                <v-divider />
                <v-card-text class="pa-4 sa-cal-body">
                    <!--
                        One page, rendered from the printer. The steps used to
                        be written out here as well as in KlipperScreen and in
                        the backend chain, which is how three files came to
                        disagree about how many there are.
                    -->
                    <div v-if="guidePage">
                        <div class="sa-step-head">{{ guidePage.title }}</div>
                        <div class="sa-step-body">{{ guidePage.hint }}</div>

                        <div
                            v-if="guidePage.status"
                            class="sa-step-note"
                            :class="guideToneClass">
                            {{ guidePage.status }}
                        </div>

                        <div v-if="guidePage.buttons.length" class="d-flex mb-3">
                            <v-btn
                                v-for="b in guidePage.buttons"
                                :key="b.gcode"
                                class="sa-step-btn mr-2"
                                color="primary"
                                @click="saGcode(b.gcode)">
                                {{ b.label }}
                            </v-btn>
                        </div>

                        <!--
                            A per-path step arrives with a button per path,
                            already addressed, so there is nothing to pick on
                            a second screen.
                        -->
                        <div v-if="guidePage.grid" class="sa-cal-grid mb-3">
                            <div
                                v-for="c in guidePage.grid"
                                :key="c.tool"
                                class="sa-cal-cell">
                                <div
                                    class="sa-cal-cell-val"
                                    :class="c.done ? 'sa-cal-done' : 'sa-cal-todo'">
                                    {{ c.value || '\u2715' }}
                                </div>
                                <v-btn
                                    small
                                    block
                                    color="primary"
                                    @click="saGcode(c.gcode)">
                                    T{{ c.tool }}
                                </v-btn>
                            </div>
                        </div>

                        <div class="sa-cal-expect">
                            ✓ {{ $t('Panels.AutoloaderPanel.WhatToExpect') }}<br />
                            <span v-for="(l, i) in guidePage.expect" :key="'e' + i">
                                • {{ l }}<br />
                            </span>
                        </div>
                        <div class="sa-cal-warn">
                            ⚠ {{ $t('Panels.AutoloaderPanel.WatchOutFor') }}<br />
                            <span v-for="(l, i) in guidePage.warn" :key="'w' + i">
                                • {{ l }}<br />
                            </span>
                        </div>

                        <div class="caption grey--text mt-3">
                            {{ $t('Panels.AutoloaderPanel.CalSaveNote') }}
                            <v-btn
                                x-small
                                text
                                class="sa-save-config"
                                @click="saGcode('SAVE_CONFIG')">
                                {{ $t('Panels.AutoloaderPanel.SaveConfig') }}
                            </v-btn>
                        </div>
                    </div>
                </v-card-text>
                <v-divider />
                <v-card-actions class="sa-step-actions">
                    <v-spacer />
                    <v-btn text :disabled="calStep === 0" @click="calStepNav(-1)">
                        <v-icon size="16" left>{{ mdiArrowLeft }}</v-icon>
                        {{ $t('Panels.AutoloaderPanel.Back') }}
                    </v-btn>
                    <v-btn
                        v-if="calStep < calTotalSteps - 1"
                        text
                        color="primary"
                        @click="calStepNav(1)">
                        {{ $t('Panels.AutoloaderPanel.Next') }}
                        <v-icon size="16" right>{{ mdiArrowRight }}</v-icon>
                    </v-btn>
                    <v-btn v-else text color="primary" @click="closeGuide()">
                        {{ $t('Panels.AutoloaderPanel.Finish') }}
                    </v-btn>
                </v-card-actions>
            </v-card>
        </v-dialog>

        <!-- ─── PROMPT DIALOG ──────────────────────────────────────
             Three modes driven by cal_state, mirroring KlipperScreen's
             sa_post_load.py:
               * load_purge   → load-complete action panel
               * unload_done  → unload-complete action panel
               * anything else → generic calibration prompt
        -->
        <v-dialog v-model="promptOpen" width="400" persistent :retain-focus="false">
            <v-card class="panel sa-dialog">
                <v-toolbar dense flat class="panel-toolbar sa-dialog-title">
                    <v-icon
                        left
                        size="18"
                        :color="promptKind === 'load' ? 'success' : promptKind === 'unload' ? 'warning' : 'warning'">
                        {{ promptKind === 'generic' ? mdiAlertCircleOutline : mdiCheckCircle }}
                    </v-icon>
                    <span class="sa-dialog-heading">{{ promptDialogTitle }}</span>
                </v-toolbar>
                <v-divider />

                <!-- ─── LOAD COMPLETE ────────────────────────────── -->
                <template v-if="promptKind === 'load'">
                    <v-card-text class="pa-4 sa-prompt-header">
                        <div class="success--text font-weight-bold sa-prompt-headline">
                            {{ $t('Panels.AutoloaderPanel.LoadComplete') }} · T{{ saStatus.cal_path }}
                        </div>
                        <div class="caption grey--text">
                            {{ $t('Panels.AutoloaderPanel.LoadCompleteSub') }}
                        </div>
                    </v-card-text>
                    <v-divider />
                    <v-card-actions class="px-3 py-2 sa-prompt-row">
                        <v-btn small color="success" class="ma-1 flex-grow-1" @click="sendPromptValue('more')">
                            <v-icon left size="16">{{ mdiAutorenew }}</v-icon>
                            {{ $t('Panels.AutoloaderPanel.Purge60') }}
                        </v-btn>
                        <v-btn small class="ma-1 flex-grow-1" @click="sendPromptValue('park')">
                            <v-icon left size="16">{{ mdiHomeMapMarker }}</v-icon>
                            {{ $t('Panels.AutoloaderPanel.Park') }}
                        </v-btn>
                        <v-btn small color="error" class="ma-1 flex-grow-1" @click="sendPromptValue('exit')">
                            <v-icon left size="16">{{ mdiClose }}</v-icon>
                            {{ $t('Panels.AutoloaderPanel.Exit') }}
                        </v-btn>
                    </v-card-actions>
                </template>

                <!-- ─── UNLOAD COMPLETE ──────────────────────────── -->
                <template v-else-if="promptKind === 'unload'">
                    <v-card-text class="pa-4 sa-prompt-header">
                        <div class="warning--text font-weight-bold sa-prompt-headline">
                            {{ $t('Panels.AutoloaderPanel.UnloadComplete') }} · T{{ saStatus.cal_path }}
                        </div>
                        <div class="caption grey--text">
                            {{ $t('Panels.AutoloaderPanel.UnloadCompleteSub') }}
                        </div>
                    </v-card-text>
                    <v-divider />
                    <v-card-actions class="px-3 py-2 sa-prompt-row">
                        <v-btn small class="ma-1 flex-grow-1" @click="sendPromptValue('park')">
                            <v-icon left size="16">{{ mdiHomeMapMarker }}</v-icon>
                            {{ $t('Panels.AutoloaderPanel.Park') }}
                        </v-btn>
                        <v-btn small color="error" class="ma-1 flex-grow-1" @click="sendPromptValue('exit')">
                            <v-icon left size="16">{{ mdiClose }}</v-icon>
                            {{ $t('Panels.AutoloaderPanel.Exit') }}
                        </v-btn>
                    </v-card-actions>
                    <v-divider />
                    <v-card-actions class="px-3 py-2">
                        <v-btn small color="success" class="ma-1 flex-grow-1" @click="sendPromptValue('load')">
                            <v-icon left size="16">{{ mdiPlay }}</v-icon>
                            {{ $t('Panels.AutoloaderPanel.LoadSamePath') }}
                        </v-btn>
                    </v-card-actions>
                </template>

                <!-- Path grids — shared by both load and unload modes -->
                <template v-if="promptKind === 'load' || promptKind === 'unload'">
                    <v-divider />
                    <v-card-text class="pa-3">
                        <div class="caption mb-1" style="color:#90CAF9;">
                            <v-icon size="14" left color="#90CAF9">{{ mdiUpload }}</v-icon>
                            {{ $t('Panels.AutoloaderPanel.LoadPath') }}
                        </div>
                        <div class="sa-path-grid mb-3">
                            <v-btn
                                v-for="i in saPathIndices"
                                :key="`load-${i}`"
                                small
                                outlined
                                class="sa-path-btn"
                                @click="sendPathAction('load', i)">
                                T{{ i }}
                            </v-btn>
                        </div>
                        <div class="caption mb-1" style="color:#FFCC80;">
                            <v-icon size="14" left color="#FFCC80">{{ mdiDownload }}</v-icon>
                            {{ $t('Panels.AutoloaderPanel.UnloadPath') }}
                        </div>
                        <div class="sa-path-grid">
                            <v-btn
                                v-for="i in saPathIndices"
                                :key="`unload-${i}`"
                                small
                                outlined
                                class="sa-path-btn"
                                @click="sendPathAction('unload', i)">
                                T{{ i }}
                            </v-btn>
                        </div>
                    </v-card-text>
                </template>

                <!-- ─── GENERIC CAL PROMPT ───────────────────────── -->
                <template v-else>
                    <v-card-text class="pa-4 sa-prompt-text">
                        {{ saStatus.cal_prompt }}
                    </v-card-text>
                    <v-divider />
                    <v-card-actions class="px-3 py-2 flex-wrap sa-prompt-actions">
                        <v-btn small class="sa-feed-btn ma-1" @click="sendPromptValue('yes')">
                            {{ $t('Panels.AutoloaderPanel.Yes') }}
                        </v-btn>
                        <v-btn small class="sa-feed-btn ma-1" @click="sendPromptValue('no')">
                            {{ $t('Panels.AutoloaderPanel.No') }}
                        </v-btn>
                        <v-btn small class="sa-feed-btn ma-1" @click="sendPromptValue('ok')">
                            {{ $t('Panels.AutoloaderPanel.OK') }}
                        </v-btn>
                        <v-btn small class="sa-feed-btn ma-1" @click="sendPromptValue('continue')">
                            {{ $t('Panels.AutoloaderPanel.Continue') }}
                        </v-btn>
                        <v-btn small class="sa-feed-btn ma-1" @click="sendPromptValue('cancel')">
                            {{ $t('Panels.AutoloaderPanel.Cancel') }}
                        </v-btn>
                    </v-card-actions>
                    <v-divider />
                    <v-card-actions class="px-3 py-2">
                        <v-text-field
                            v-model="calResponse"
                            :label="$t('Panels.AutoloaderPanel.CalResponse')"
                            dense
                            outlined
                            hide-details
                            @keyup.enter="sendCalResponse" />
                        <v-btn
                            small
                            color="primary"
                            class="ml-2"
                            :disabled="!calResponse.trim()"
                            @click="sendCalResponse">
                            {{ $t('Panels.AutoloaderPanel.Respond') }}
                        </v-btn>
                    </v-card-actions>
                </template>
            </v-card>
        </v-dialog>

        <!-- ─── COLOR PICKER DIALOG (for custom pie slices) ────── -->
        <v-dialog v-model="pickerOpen" width="400" :retain-focus="false">
            <v-card class="panel sa-dialog">
                <v-toolbar dense flat class="panel-toolbar sa-dialog-title">
                    <span class="sa-dialog-heading">
                        {{ $t('Panels.AutoloaderPanel.PickColor') }}
                        <span v-if="colorMode !== 'single'" class="grey--text">
                            — {{ pickerSliceLabel }}
                        </span>
                    </span>
                    <v-spacer />
                    <v-btn icon small @click="pickerOpen = false">
                        <v-icon size="18">{{ mdiClose }}</v-icon>
                    </v-btn>
                </v-toolbar>
                <v-divider />
                <v-color-picker
                    v-model="pickerColor"
                    mode="hexa"
                    hide-mode-switch
                    flat
                    dot-size="20" />
            </v-card>
        </v-dialog>
    </div>
</template>

<script lang="ts">
import { Component, Mixins, Prop, Watch } from 'vue-property-decorator'
import {
    mdiClose,
    mdiCloseThick,
    mdiArrowUpBold,
    mdiArrowDownBold,
    mdiPencil,
    mdiCogOutline,
    mdiInformation,
    mdiArrowLeft,
    mdiArrowRight,
    mdiAlertCircleOutline,
    mdiCheckCircle,
    mdiAutorenew,
    mdiHomeMapMarker,
    mdiPlay,
    mdiUpload,
    mdiDownload,
} from '@mdi/js'
import axios from './lib/http'
import SaMixin, { saBorderForHex } from './mixin'
import localeMessages from './locales/index.json'
import { saFilamentIcon } from './icons'

interface SaBrand {
    display_name: string
    filepath: string
}

interface SaColor {
    id: string
    name: string
    hex: string
    /** Explicit fields from new-format brand cfgs — present once the catalog
     *  provides them. When set, these win over name/line heuristics. */
    color_type?: string
    hex_2?: string
    hex_3?: string
    /** Enrichment: 'single'|'dual'|'tri'|'gradient' derived from name/line. */
    mode?: 'single' | 'dual' | 'tri' | 'gradient'
    /** Enrichment: full hex list for single/dual/tri. Always includes base hex first. */
    hexes?: string[]
}

interface SaProductLine {
    line_id: string
    display_name: string
    material: string
    description: string
    load_temp: number
    unload_temp: number
    purge_speed: number
    purge_length: number
    bed_temp: number
    notes: string
    colors: SaColor[]
}

/**
 * Common filament color names → representative hex. Used to derive the
 * second / third hex for catalog entries with multi-color names like
 * "Dual Gold/Black" — the config only carries ONE hex, so we look up
 * "Black" here to paint the second pie slice.
 */
const NAMED_COLORS: Record<string, string> = {
    black: '#1A1A1A',
    white: '#F0F0F0',
    grey: '#808080',
    gray: '#808080',
    charcoal: '#36454F',
    natural: '#E8DCC4',
    beige: '#E5D5B7',
    cream: '#FFF8DC',
    ivory: '#FFFFF0',
    red: '#E53935',
    blue: '#1E88E5',
    green: '#43A047',
    yellow: '#FDD835',
    orange: '#FB8C00',
    purple: '#8E24AA',
    violet: '#7E57C2',
    pink: '#EC407A',
    magenta: '#C2185B',
    cyan: '#00ACC1',
    teal: '#00897B',
    gold: '#FFC107',
    silver: '#BDBDBD',
    bronze: '#8D6E63',
    copper: '#BF5F00',
    brown: '#6D4C41',
    tan: '#B08E5A',
    navy: '#1A237E',
    maroon: '#5D1A1A',
    burgundy: '#4E1519',
    lime: '#C0CA33',
    mint: '#26A69A',
    coral: '#FF7043',
    salmon: '#FF8A65',
    peach: '#FFAB91',
    clear: '#F5F5F5',
    transparent: '#F5F5F5',
    translucent: '#F5F5F5',
}

function cleanColorWord(w: string): string {
    // Strip "(UV shift)" style parentheticals; lowercase; trim
    return w
        .replace(/\s*\([^)]*\)\s*/g, '')
        .trim()
        .toLowerCase()
}

// ── HSL helpers for generating pie-slice colors when the catalog only
//    carries one representative hex (e.g. Polymaker Panchroma Dual Silk
//    entries named "Aubergine", "Beluga", etc. with no second-color hint).
function hexToHsl(hex: string): [number, number, number] {
    const h = hex.replace(/^#/, '').padEnd(6, '0')
    const r = parseInt(h.slice(0, 2), 16) / 255
    const g = parseInt(h.slice(2, 4), 16) / 255
    const b = parseInt(h.slice(4, 6), 16) / 255
    const max = Math.max(r, g, b)
    const min = Math.min(r, g, b)
    const l = (max + min) / 2
    if (max === min) return [0, 0, l * 100]
    const d = max - min
    const s = l > 0.5 ? d / (2 - max - min) : d / (max + min)
    let hue = 0
    if (max === r) hue = (g - b) / d + (g < b ? 6 : 0)
    else if (max === g) hue = (b - r) / d + 2
    else hue = (r - g) / d + 4
    return [(hue / 6) * 360, s * 100, l * 100]
}

function hslToHex(hDeg: number, sPct: number, lPct: number): string {
    const h = (((hDeg % 360) + 360) % 360) / 360
    const s = sPct / 100
    const l = lPct / 100
    if (s === 0) {
        const v = Math.round(l * 255)
            .toString(16)
            .padStart(2, '0')
        return `#${v}${v}${v}`.toUpperCase()
    }
    const q = l < 0.5 ? l * (1 + s) : l + s - l * s
    const p = 2 * l - q
    const hue2rgb = (t: number): number => {
        if (t < 0) t += 1
        if (t > 1) t -= 1
        if (t < 1 / 6) return p + (q - p) * 6 * t
        if (t < 1 / 2) return q
        if (t < 2 / 3) return p + (q - p) * (2 / 3 - t) * 6
        return p
    }
    const r = hue2rgb(h + 1 / 3)
    const g = hue2rgb(h)
    const b = hue2rgb(h - 1 / 3)
    const toHex = (v: number): string =>
        Math.round(v * 255)
            .toString(16)
            .padStart(2, '0')
    return `#${toHex(r)}${toHex(g)}${toHex(b)}`.toUpperCase()
}

/** Rotate the hue of a hex color by `degrees` (e.g. 180 = complementary). */
function shiftHue(hex: string, degrees: number): string {
    if (!hex) return hex
    const [h, s, l] = hexToHsl(hex)
    // Keep saturation above a visible floor so complement of near-greys
    // doesn't come out as just another grey.
    const sBoosted = Math.max(s, 30)
    return hslToHex(h + degrees, sBoosted, l)
}

function namedColorToHex(word: string, fallback: string): string {
    const cleaned = cleanColorWord(word)
    if (!cleaned) return fallback
    if (NAMED_COLORS[cleaned]) return NAMED_COLORS[cleaned]
    // Partial match ("Cold White" → "white", "Rose Gold" → "gold")
    for (const key of Object.keys(NAMED_COLORS)) {
        if (cleaned.endsWith(key) || cleaned.includes(` ${key}`) || cleaned.startsWith(`${key} `)) {
            return NAMED_COLORS[key]
        }
    }
    return fallback
}

/**
 * Inspect a catalog color and determine whether it's single/dual/tri/gradient.
 * Rules:
 *   - product line marked "gradient" in name/description → gradient
 *   - name starts with "Dual|Tri|Bicolor|Tricolor" and has an X/Y split → that mode
 *   - name has "/" separator(s) → dual (1 slash) or tri (2 slashes)
 *   - otherwise single
 * The stored hex is always the first color; additional hexes are derived
 * from the remaining words via NAMED_COLORS.
 */
function parseMultiColor(
    name: string,
    baseHex: string,
    line?: SaProductLine,
    explicit?: { color_type?: string; hex_2?: string; hex_3?: string }
): { mode: 'single' | 'dual' | 'tri' | 'gradient'; hexes: string[] } {
    const normBase = baseHex ? (baseHex.startsWith('#') ? baseHex : `#${baseHex}`) : ''
    const norm = (h: string): string => (h ? (h.startsWith('#') ? h : `#${h}`) : '')

    // EXPLICIT fields from new-format brand cfgs win unconditionally — they
    // carry actual hex values for each slice, not heuristic guesses.
    if (explicit?.color_type) {
        const t = explicit.color_type.toLowerCase()
        const h2 = norm(explicit.hex_2 ?? '')
        const h3 = norm(explicit.hex_3 ?? '')
        if (t === 'tri' && h2 && h3) {
            return { mode: 'tri', hexes: [normBase, h2, h3] }
        }
        if (t === 'dual' && h2) {
            return { mode: 'dual', hexes: [normBase, h2] }
        }
        if (t === 'gradient') {
            return { mode: 'gradient', hexes: h2 ? [normBase, h2] : [normBase] }
        }
        // color_type === 'single' (or unrecognized) → fall through to heuristics
    }

    const ctx = `${line?.display_name ?? ''} ${line?.description ?? ''}`.toLowerCase()

    // Gradient context wins first — most specific product-line signal.
    if (/\bgradient\b|\brainbow\s*spool\b|\bmulti-?color\b/.test(ctx)) {
        return { mode: 'gradient', hexes: [normBase] }
    }

    // Explicit X/Y (or X/Y/Z) pattern in the color name — Amolen style.
    // "Dual Gold/Black" → split on '/' and look up each word in NAMED_COLORS.
    const cleanName = (name || '')
        .replace(/^(Dual|Tri|Bi-?color|Tri-?color|Tricolored|Two-tone)\s+/i, '')
        .replace(/\s*\([^)]*\)\s*/g, '')
        .trim()
    const parts = cleanName
        .split(/\s*\/\s*/)
        .map((p) => p.trim())
        .filter((p) => p)
    if (parts.length >= 3) {
        return {
            mode: 'tri',
            hexes: [
                normBase,
                namedColorToHex(parts[1], shiftHue(normBase, 120)),
                namedColorToHex(parts[2], shiftHue(normBase, 240)),
            ],
        }
    }
    if (parts.length === 2) {
        return {
            mode: 'dual',
            hexes: [normBase, namedColorToHex(parts[1], shiftHue(normBase, 180))],
        }
    }

    // Line-context multi-color: the color NAME doesn't split, but the product
    // line itself is a dual/tri product (Polymaker Panchroma Dual Silk/Matte,
    // etc.). Each color entry still carries only one representative hex, so
    // generate the remaining slice(s) via hue rotation to visually indicate
    // the multi-color nature.
    if (/\btri-?color(ed)?\b/i.test(ctx)) {
        return {
            mode: 'tri',
            hexes: [normBase, shiftHue(normBase, 120), shiftHue(normBase, 240)],
        }
    }
    if (/\bdual\b|\bbi-?color\b|\btwo-?tone\b|\bco-?extru/i.test(ctx)) {
        return { mode: 'dual', hexes: [normBase, shiftHue(normBase, 180)] }
    }

    return { mode: 'single', hexes: [normBase] }
}

// Named explicitly: minification renames the class, and Vue registers a
// class component under that name. A one-letter minified name collides with
// a real HTML tag and Vue warns about a reserved component id.
@Component({ name: 'AutoloaderPanel' })
export default class AutoloaderPanel extends Mixins(SaMixin) {
    /*
     * Props supplied by Mainsail's CustomPanel host.
     *
     * panelStore/panelSocket are the sanctioned way for a plugin to reach the
     * host; $store and $socket also happen to resolve because the plugin
     * shares Mainsail's Vue constructor and renders inside its component
     * tree, but that is an implementation detail rather than a contract.
     */
    @Prop({ type: Object, required: true }) declare readonly panelConfig: Record<string, unknown>
    @Prop({ type: Object, required: true }) declare readonly panelStore: any
    @Prop({ type: Object, required: true }) declare readonly panelSocket: any

    /**
     * Moonraker's base URL. Upstream this came from BaseMixin, which a plugin
     * cannot import — it lives inside Mainsail's own source tree. The getter
     * body is the same one BaseMixin uses.
     */
    get apiUrl(): string {
        return this.panelStore.getters['socket/getUrl']
    }

    /*
     * The panel's ~120 translation keys ship with the plugin instead of
     * Mainsail's locale files, since the host has no reason to carry strings
     * for a panel it does not know about. Merging in created() puts them in
     * place before the first render, so no $t call ever renders a raw key.
     */
    created(): void {
        const messages = localeMessages as Record<string, Record<string, unknown>>

        Object.keys(messages).forEach((locale) => {
            this.$i18n.mergeLocaleMessage(locale, messages[locale])
        })
    }

    saFilamentIcon = saFilamentIcon
    mdiClose = mdiClose
    mdiCloseThick = mdiCloseThick
    mdiArrowUpBold = mdiArrowUpBold
    mdiArrowDownBold = mdiArrowDownBold
    mdiPencil = mdiPencil
    mdiCogOutline = mdiCogOutline
    mdiInformation = mdiInformation
    mdiArrowLeft = mdiArrowLeft
    mdiArrowRight = mdiArrowRight
    mdiAlertCircleOutline = mdiAlertCircleOutline
    mdiCheckCircle = mdiCheckCircle
    mdiAutorenew = mdiAutorenew
    mdiHomeMapMarker = mdiHomeMapMarker
    mdiPlay = mdiPlay
    mdiUpload = mdiUpload
    mdiDownload = mdiDownload
    saBorderForHex = saBorderForHex

    /** Auto-shown when the autoloader sets cal_state non-empty (calibration
     *  prompts, unload-confirm prompts, etc.). Closes when the printer
     *  clears cal_state. */
    promptOpen = false

    // Calibration wizard state (mirrors KlipperScreen sa_calibration_guide)
    calOpen = false
    calStep = 0
    /*
     * Set while the operator is paging around by hand, so following the live
     * phase does not yank the page out from under someone reading ahead. It
     * lasts until the guide is reopened -- a deliberate move away is a
     * decision, not a momentary one.
     */
    /*
     * True when the guide closed itself to let a prompt have the screen, as
     * opposed to the operator closing it. Only the former reopens: pressing X
     * during a calibration has to mean "go away", or the guide fights the
     * person trying to dismiss it.
     */
    calYielded = false

    // Feed/Retract state
    feedDistance = 50
    feedSpeed = 10
    feedDistancePresets = [10, 50, 100, 200]
    feedSpeedPresets = [5, 10, 25, 50]

    pathModalOpen = false
    pathModalIdx: number | null = null
    /*
     * Which view the path dialog is showing.
     *
     * Controls and the profile editor used to be two v-dialogs that swapped by
     * closing one and opening the other in the same tick. Vuetify tears an
     * overlay down asynchronously, so the closing dialog's teardown landed
     * after the opening dialog had set up and stripped the scroll lock back
     * off -- leaving the dashboard scrolling behind an open popup. One dialog
     * with two views cannot race with itself, and swapping views no longer
     * costs a close/open transition.
     */
    pathView: 'controls' | 'profile' = 'controls'
    calResponse = ''

    editMaterial = ''
    editBrand = ''
    editLine = ''
    editColorName = ''
    editColorHex = ''
    editLoadTemp = 200
    editUnloadTemp = 185
    editPurgeSpeed = 5
    editPurgeLength = 30

    // Catalog cascade state
    brandItems: SaBrand[] = []
    productLineItems: SaProductLine[] = []
    colorItems: SaColor[] = []
    selectedBrandPath = ''
    selectedLineId = ''
    selectedColorId = ''
    loadingBrands = false
    loadingLines = false

    // Custom-color state (single / dual / tri)
    colorMode: 'single' | 'dual' | 'tri' = 'single'
    // Authoritative type for the saved profile (matches what the autoloader
    // klipper module accepts/exposes). 'gradient' has no editor toggle but is
    // preserved when the user picks a gradient catalog entry.
    editColorType: 'single' | 'dual' | 'tri' | 'gradient' = 'single'
    customHexes: string[] = ['FFFFFF', '000000', '808080']

    // Color picker dialog
    pickerOpen = false
    pickerSlice = 0
    pickerColor = '#FFFFFF'

    // Client-side homed tracker. The autoloader module does NOT expose its
    // `_selector_homed` flag through `get_status`, so we infer homed state
    // from (a) any path being currently selected (current_path >= 0 — impossible
    // without a prior home), or (b) having seen an "SA: Selector homed"
    // gcode response message since the last Klippy connect/shutdown.
    selectorHomedSawMessage = false
    private _unsubStore: (() => void) | null = null

    get isCustomColor(): boolean {
        return this.selectedColorId === '__custom__'
    }

    get selectedLine(): SaProductLine | undefined {
        return this.productLineItems.find((l) => l.line_id === this.selectedLineId)
    }

    get colorModeLabels(): string[] {
        return [
            this.$t('Panels.AutoloaderPanel.Single') as string,
            this.$t('Panels.AutoloaderPanel.Dual') as string,
            this.$t('Panels.AutoloaderPanel.Tri') as string,
        ]
    }

    get colorModeIdx(): number {
        return ['single', 'dual', 'tri'].indexOf(this.colorMode)
    }

    set colorModeIdx(val: number) {
        this.colorMode = (['single', 'dual', 'tri'] as const)[val] ?? 'single'
        // User touched the toggle → that is now the authoritative type
        // (any prior 'gradient' selection is replaced).
        this.editColorType = this.colorMode
    }

    get pieSliceCount(): number {
        return this.colorMode === 'tri' ? 3 : this.colorMode === 'dual' ? 2 : 1
    }

    get pieSlices(): Array<{ type: 'circle' | 'arc'; d?: string; r?: number; color: string }> {
        const sliceColor = (i: number): string => {
            const raw = (this.customHexes[i] || '').replace(/^#/, '')
            return raw ? `#${raw}` : '#E0E0E0'
        }
        if (this.colorMode === 'single') {
            return [{ type: 'circle', r: 45, color: sliceColor(0) }]
        }
        if (this.colorMode === 'dual') {
            // KlipperScreen convention: hex[0] on left, hex[1] on right.
            // arcPath(180, 360) sweeps clockwise from 6→12 via the 9 o'clock side → LEFT.
            // arcPath(0, 180)   sweeps clockwise from 12→6 via the 3 o'clock side → RIGHT.
            return [
                { type: 'arc', d: this.arcPath(180, 360, 45), color: sliceColor(0) },
                { type: 'arc', d: this.arcPath(0, 180, 45), color: sliceColor(1) },
            ]
        }
        // Tri — three 120° sectors starting from the top.
        const slices: Array<{ type: 'circle' | 'arc'; d?: string; color: string }> = []
        const step = 360 / 3
        for (let i = 0; i < 3; i++) {
            slices.push({
                type: 'arc',
                d: this.arcPath(i * step, (i + 1) * step, 45),
                color: sliceColor(i),
            })
        }
        return slices
    }

    get pickerSliceLabel(): string {
        const n = this.pickerSlice + 1
        const labels = ['1st', '2nd', '3rd']
        return labels[this.pickerSlice] ?? `#${n}`
    }

    arcPath(startAngle: number, endAngle: number, r: number): string {
        // Start angles are measured from top (12 o'clock), going clockwise.
        const rad = (deg: number): number => ((deg - 90) * Math.PI) / 180
        const x1 = r * Math.cos(rad(startAngle))
        const y1 = r * Math.sin(rad(startAngle))
        const x2 = r * Math.cos(rad(endAngle))
        const y2 = r * Math.sin(rad(endAngle))
        const largeArc = endAngle - startAngle > 180 ? 1 : 0
        return `M 0,0 L ${x1.toFixed(3)},${y1.toFixed(3)} A ${r},${r} 0 ${largeArc},1 ${x2.toFixed(3)},${y2.toFixed(3)} Z`
    }

    openPicker(idx: number): void {
        this.pickerSlice = idx
        const hex = (this.customHexes[idx] || 'FFFFFF').replace(/^#/, '')
        this.pickerColor = `#${hex}`
        this.pickerOpen = true
    }

    @Watch('pickerColor')
    onPickerColorChange(val: unknown): void {
        if (!this.pickerOpen) return
        // v-color-picker can emit either a string "#RRGGBB"/"#RRGGBBAA" or an
        // object { hex: ..., hexa: ..., rgba: ..., ... }. Normalize here.
        let hex = ''
        if (typeof val === 'string') {
            hex = val
        } else if (val && typeof val === 'object') {
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            const obj = val as any
            hex = obj.hex ?? obj.hexa ?? ''
        }
        const clean = hex.replace(/^#/, '').substring(0, 6).toUpperCase()
        if (clean.length !== 6) return
        const next = [...this.customHexes]
        next[this.pickerSlice] = clean
        this.customHexes = next
    }

    get canLoadModal(): boolean {
        if (this.pathModalIdx === null) return false
        const i = this.pathModalIdx
        if (this.saEffectiveState(i) === 'loaded') return false
        if (!this.saStatus.path_color_hexes[i]) return false
        return true
    }

    get canUnloadModal(): boolean {
        if (this.pathModalIdx === null) return false
        const state = this.saEffectiveState(this.pathModalIdx)
        return state !== 'empty' && state !== 'unknown'
    }

    /**
     * Name of the action this panel is currently running, or null.
     *
     * Replaces a spinner bound to socket.loadings, which is global: it holds
     * 'sendGcode' while ANY g-code is in flight anywhere in Mainsail. Pressing
     * Feed therefore span Load, Unload and Save Profile too, and so did
     * running an unrelated macro from the console. Buttons appeared to be
     * doing something for no reason the user could see.
     */
    busyAction: string | null = null

    /**
     * Run one action, showing progress on that action alone.
     *
     * Also serialises: a second press while one is running is dropped rather
     * than queued. These commands move a real machine, and SA_LOAD twice from
     * an impatient double-click is a genuine hazard, not just noise.
     */
    private async runAction(name: string, script: string): Promise<void> {
        if (this.busyAction !== null) return

        this.busyAction = name
        try {
            await this.saGcode(script)
        } finally {
            this.busyAction = null
        }
    }

    /**
     * Config-declared stepper key under `stepper_enable.steppers`.
     * e.g. "manual_stepper sa_selector".
     */
    get selectorStepperKey(): string {
        return (
            this.$store.state.printer?.configfile?.settings?.autoloader
                ?.selector_stepper ?? 'manual_stepper sa_selector'
        )
    }

    /**
     * True when the selector stepper is currently energized. If it's off,
     * the selector has lost its reference — must re-home before trusting
     * any position.
     */
    get selectorStepperEnabled(): boolean {
        const steppers = this.$store.state.printer?.stepper_enable?.steppers
        if (!steppers) return true // data not yet available — fail-safe
        return !!steppers[this.selectorStepperKey]
    }

    /**
     * Returns true when the selector is homed. Requires BOTH:
     *   (1) The selector stepper is currently energized — `stepper_enable`
     *       flips this to false on M84 / DISABLE_MOTORS / any TURN_OFF_MOTORS.
     *   (2) We've observed a "SA: Selector homed" gcode response since the
     *       last disable or Klippy reconnect.
     * Using stepper_enable is authoritative; event-text matching on its own
     * missed M84 sent via macros / buttons.
     */
    get isSelectorHomed(): boolean {
        return this.selectorStepperEnabled && this.selectorHomedSawMessage
    }

    @Watch('selectorStepperEnabled')
    onSelectorStepperEnabledChange(enabled: boolean): void {
        // Any transition to "disabled" invalidates the homed flag — position
        // is unknown once the motor is de-energized. Re-enabling doesn't
        // restore home; SA_HOME must run again.
        if (!enabled) {
            this.selectorHomedSawMessage = false
        }
    }

    /**
     * Index of the extruder currently on the carriage.
     *
     * Klipper names the first extruder "extruder" and the rest "extruderN",
     * so the first one has no number to parse.  Returns -1 when there is no
     * toolhead object yet, which happens before klippy is ready.
     */
    get activeToolIndex(): number {
        const name = this.$store.state.printer?.toolhead?.extruder
        if (typeof name !== 'string' || !name.startsWith('extruder')) return -1

        const suffix = name.slice('extruder'.length)
        if (suffix === '') return 0

        const idx = parseInt(suffix, 10)

        return Number.isNaN(idx) ? -1 : idx
    }

    /** Hotend temperature of the mounted tool, or null if it cannot be read. */
    get activeToolTemp(): number | null {
        const idx = this.activeToolIndex
        if (idx < 0) return null

        const key = idx === 0 ? 'extruder' : `extruder${idx}`
        const temp = this.$store.state.printer?.[key]?.temperature

        return typeof temp === 'number' ? temp : null
    }

    /**
     * The four readings in the status strip.
     *
     * Built as data rather than markup so the template stays a single v-for,
     * and so the empty cases are decided in one place: every value has a
     * defined reading before the printer is homed or a profile is set.
     */
    get statusItems(): Array<{ key: string; label: string; value: string; sub?: string; accent?: boolean }> {
        const sa = this.saStatus
        const t = (k: string): string => this.$t(`Panels.AutoloaderPanel.${k}`) as string

        // The selector holds no position until it has been homed, so an
        // unhomed machine must say so rather than show a stale 0.00 mm.
        const selectorHomed = sa.current_path >= 0
        const selector = selectorHomed
            ? { value: `T${sa.current_path}`, sub: `${(sa.selector_position ?? 0).toFixed(2)} mm` }
            : { value: t('StatusUnhomed'), sub: undefined }

        const activeIdx = this.activeToolIndex
        const temp = this.activeToolTemp
        const active = activeIdx >= 0
            ? { value: `T${activeIdx}`, sub: temp === null ? undefined : `${temp.toFixed(1)} °C` }
            : { value: '—', sub: undefined }

        return [
            { key: 'selector', label: t('Selector'), value: selector.value, sub: selector.sub },
            {
                key: 'drive',
                label: t('StatusDriveGear'),
                value: this.isServoEngaged ? t('StatusEngaged') : t('StatusNeutral'),
                accent: this.isServoEngaged,
            },
            { key: 'active', label: t('StatusActiveTool'), value: active.value, sub: active.sub },
            {
                key: 'cal',
                label: t('StatusCalibration'),
                value: this.saIsCalibrating ? t('StatusRunning') : t('StatusIdle'),
                sub: this.saIsCalibrating && sa.cal_path >= 0 ? `T${sa.cal_path}` : undefined,
                accent: this.saIsCalibrating,
            },
        ]
    }

    get isServoEngaged(): boolean {
        return !!this.saStatus.servo_engaged
    }

    get klippyState(): string {
        return this.$store.state.server?.klippy_state ?? ''
    }

    @Watch('klippyState')
    onKlippyStateChange(val: string): void {
        // Any loss of Klippy connection wipes the homed state — the printer
        // has to re-home when it comes back up.
        if (val !== 'ready') {
            this.selectorHomedSawMessage = false
        }
    }

    mounted(): void {
        this.installPromptSkin()
        // Adopt the printer's current guide state. A refresh while the guide
        // is open would otherwise show a closed dialog with no change coming
        // to correct it.
        if (this.saStatus.guide_open && !this.promptWaiting) {
            this.syncCalStep()
            this.calOpen = true
        }
        // Scan recent gcode events to recover the "homed" flag across a page
        // refresh. `stepper_enable` covers the "unhomed" side authoritatively.
        if (this.selectorStepperEnabled) {
            const events = this.$store.state.server?.events ?? []
            for (let i = events.length - 1; i >= 0; i--) {
                const msg = events[i]?.message
                if (typeof msg === 'string' && /SA:\s*Selector\s+homed/i.test(msg)) {
                    this.selectorHomedSawMessage = true
                    break
                }
            }
        }
        // Subscribe to future gcode responses so the home indicator updates live.
        this._unsubStore = this.$store.subscribe((mutation) => {
            if (mutation.type !== 'server/addEvent') return
            const msg = mutation.payload?.message
            if (typeof msg === 'string' && /SA:\s*Selector\s+homed/i.test(msg)) {
                this.selectorHomedSawMessage = true
            }
        })
    }

    beforeDestroy(): void {
        if (this._unsubStore) {
            this._unsubStore()
            this._unsubStore = null
        }
        // A MutationObserver on document.body outlives the panel unless it is
        // disconnected here, and Mainsail mounts and unmounts panels freely.
        if (this.saPromptObserver) {
            this.saPromptObserver.disconnect()
            this.saPromptObserver = null
        }
    }

    /**
     * Short name of the autoloader's drive manual_stepper, read from
     * `autoloader.drive_stepper` in the printer config.
     * Example config value: "manual_stepper sa_drive" → returns "sa_drive".
     */
    get driveStepperName(): string {
        const full =
            this.$store.state.printer?.configfile?.settings?.autoloader?.drive_stepper
        if (!full) return 'sa_drive'
        const parts = String(full).trim().split(/\s+/)
        return parts[parts.length - 1] || 'sa_drive'
    }

    doFeed(): void {
        this.sendManualMove(Math.abs(this.feedDistance), 'feed')
    }

    doRetract(): void {
        this.sendManualMove(-Math.abs(this.feedDistance), 'retract')
    }

    sendManualMove(distance: number, action = 'feed'): void {
        const speed = Math.max(1, Number(this.feedSpeed) || 10)
        const stepper = this.driveStepperName
        const script = [
            `MANUAL_STEPPER STEPPER=${stepper} ENABLE=1`,
            `MANUAL_STEPPER STEPPER=${stepper} SET_POSITION=0`,
            `MANUAL_STEPPER STEPPER=${stepper} MOVE=${distance} SPEED=${speed}`,
        ].join('\n')
        void this.runAction(action, script)
    }

    /** The profile editor needs more room than the controls. */
    openPathModal(i: number): void {
        this.pathModalIdx = i
        // Always open on the controls, never on whichever view was last used.
        this.pathView = 'controls'
        this.pathModalOpen = true
    }

    openCalibration(): void {
        this.calStep = 0
        this.openGuide()
    }

    // ── Calibration status helpers ────────────────────────────────────
    /*
     * Whether either motor is running inverted, shown beside the buzz
     * buttons. The state matters because SA_BUZZ_CHECK's "wrong way" answer
     * flips it -- without a readout, two wrong answers land back where you
     * started with nothing on screen saying so.
     */
    get motorDirInverted(): boolean {
        return !!this.saStatus.drive_dir_invert || !!this.saStatus.selector_dir_invert
    }

    /*
     * The guide, as the printer defines it. Nothing about the steps is known
     * here -- not their content, not their order, not how many there are.
     * Keeping a second copy is what let this dialog show seven pages, count to
     * nine, and belong to an eleven-step chain all at once.
     */
    get guidePages(): any[] {
        const p = (this.saStatus as any).guide_pages
        return Array.isArray(p) ? p : []
    }

    get guidePage(): any | null {
        return this.guidePages[this.calStep] ?? null
    }

    get calTotalSteps(): number {
        return this.guidePages.length || 1
    }

    get guideToneClass(): string {
        const tone = this.guidePage?.tone
        if (tone === 'warn') return 'sa-cal-status--warn'
        if (tone === 'ok') return 'sa-cal-status--ok'
        return ''
    }

    get motorDirLabel(): string {
        const f = (inv?: boolean) => (inv ? 'INVERTED' : 'normal')
        return `Direction: drive ${f(this.saStatus.drive_dir_invert)}`
            + ` \u00b7 selector ${f(this.saStatus.selector_dir_invert)}`
    }

    get motorDirClass(): string {
        return this.motorDirInverted ? 'sa-cal-status--warn' : ''
    }

    get servoAnglesLabel(): string {
        const eng = this.saStatus.servo_engaged_angle ?? 0
        const dis = this.saStatus.servo_disengaged_angle ?? 0
        return `Engaged ${eng.toFixed(0)}\u00b0`
            + ` \u00b7 disengaged ${dis.toFixed(0)}\u00b0`
    }

    /*
     * Move the guide to whichever step the machine is actually waiting on.
     *
     * The step number comes from the backend, not from a copy of the mapping
     * here: the prompt dialog is titled from the same value, so the page
     * behind it cannot end up claiming a different step than the dialog in
     * front of it -- which is exactly what made the prompt read as an
     * interruption rather than the next page.
     */
    /*
     * The printer owns which page the guide is on, so this is a mirror rather
     * than a second copy: nothing here decides a step, it only reflects
     * guide_step and asks the printer to change it.
     */
    syncCalStep(): void {
        const live = this.saStatus.guide_step ?? 0
        if (live >= 1) this.calStep = live - 1
    }

    @Watch('saStatus.guide_step')
    onGuideStepChange(): void {
        this.syncCalStep()
    }

    @Watch('saStatus.guide_open')
    onGuideOpenChange(open: boolean): void {
        // A prompt owns the screen while one is waiting; the guide reopens
        // when it clears. See onPromptWaitingChange.
        if (open && this.promptWaiting) return
        this.syncCalStep()
        this.calOpen = !!open
        if (!open) this.calYielded = false
    }

    openGuide(): void {
        // Open here directly rather than waiting for guide_open to change:
        // if it is already true -- the touchscreen has the guide up -- there
        // is no change coming and the click would do nothing at all.
        this.calYielded = false
        this.syncCalStep()
        this.calOpen = true
        this.saGcode('SA_GUIDE OPEN=1')
    }

    closeGuide(): void {
        // Same reasoning as openGuide: close here rather than waiting for the
        // flag to come back false. Clearing calYielded as well means a guide
        // dismissed during a calibration stays dismissed rather than springing
        // back when the phase clears.
        this.calYielded = false
        this.calOpen = false
        this.saGcode('SA_GUIDE OPEN=0')
    }

    calStepNav(delta: number): void {
        const next = Math.min(this.calTotalSteps,
                              Math.max(1, this.calStep + 1 + delta))
        this.saGcode(`SA_GUIDE STEP=${next}`)
    }

    @Watch('saStatus.cal_step')
    onCalStepChange(): void {
        if (this.calOpen) this.syncCalStep()
    }

    /** Whether a calibration phase is waiting on an answer right now. */
    get promptWaiting(): boolean {
        return (this.saStatus.cal_state ?? '') !== ''
    }

    @Watch('promptWaiting')
    onPromptWaitingChange(waiting: boolean): void {
        if (waiting) {
            // Step aside locally only. The printer's guide_open stays true --
            // this screen is hiding its copy behind the prompt, not closing
            // the guide for everyone.
            if (this.calOpen) {
                this.calYielded = true
                this.calOpen = false
            }
            return
        }
        if (this.calYielded) {
            this.calYielded = false
            this.syncCalStep()
            this.calOpen = !!this.saStatus.guide_open
        }
    }

    get selectorCalibrated(): boolean {
        const positions = this.saStatus.selector_positions ?? []
        if (positions.length === 0) return false
        // Defaults are spaced at exactly 21mm increments (0, 21, 42, ...).
        // Once calibrated, the actual positions drift from those ideals.
        return positions.some((p, i) => Math.abs(p - i * 21.0) > 1.0)
    }

    get selectorPositionsLabel(): string {
        const positions = this.saStatus.selector_positions ?? []
        return positions.map((p, i) => `T${i}:${p.toFixed(1)}`).join('  ')
    }

    get driveCalibrated(): boolean {
        const d = this.saStatus.drive_rotation_distance
        return typeof d === 'number' && d > 0
    }

    get encoderMaxSpeed(): number {
        return this.saStatus.encoder_max_speed ?? 0
    }

    get encoderSpeedCalibrated(): boolean {
        return this.encoderMaxSpeed > 0
    }

    toolEncoderDone(i: number): boolean {
        const mpp = this.saStatus.encoder_mpp?.[i]
        return typeof mpp === 'number' && mpp > 0
    }

    toolBowdenDone(i: number): boolean {
        // Default length in config is 800mm; consider "calibrated" once it
        // drifts from that by more than 5mm.
        const len = this.saStatus.bowden_lengths?.[i]
        return typeof len === 'number' && Math.abs(len - 800.0) > 5.0
    }

    async openProfile(): Promise<void> {
        this.pathView = 'profile'
        if (this.pathModalIdx !== null) {
            const i = this.pathModalIdx
            this.editMaterial = this.saStatus.path_materials?.[i] ?? ''
            this.editBrand = this.saStatus.path_brands?.[i] ?? ''
            this.editLine = this.saStatus.path_product_lines?.[i] ?? ''
            this.editColorName = this.saStatus.path_color_names?.[i] ?? ''
            const parts = this.saColorParts(i)
            const mode = this.saColorMode(i)
            // Reconstruct the editColorHex summary (slash-joined for display only).
            this.editColorHex = parts.length ? parts.map((h) => `#${h}`).join('/') : ''
            this.editLoadTemp = this.saStatus.path_load_temps?.[i] ?? 200
            this.editUnloadTemp = this.saStatus.path_unload_temps?.[i] ?? 185
            this.editPurgeSpeed = 5
            this.editPurgeLength = this.saStatus.purge_length ?? 30
            this.hydrateCustomHexesFromParts(parts, mode)
        }
        this.selectedBrandPath = ''
        this.selectedLineId = ''
        this.selectedColorId = ''
        this.productLineItems = []
        this.colorItems = []
        if (this.brandItems.length === 0) {
            await this.fetchBrands()
        }
        await this.matchProfileToCatalog()
    }

    /**
     * When opening an existing profile, look up the stored brand / line /
     * color in the catalog and pre-select the dropdowns. Leaves them blank
     * on no match (e.g. user-typed brand that isn't in the catalog) or when
     * the profile is empty. Does NOT overwrite edit fields — dropdowns are
     * set programmatically so `@change` handlers never fire.
     */
    async matchProfileToCatalog(): Promise<void> {
        if (this.pathModalIdx === null) return
        const i = this.pathModalIdx
        const storedBrand = this.saStatus.path_brands?.[i] ?? ''
        const storedLine = this.saStatus.path_product_lines?.[i] ?? ''
        const storedColorName = this.saStatus.path_color_names?.[i] ?? ''
        const storedHex = this.saStatus.path_color_hexes?.[i] ?? ''
        if (!storedBrand) return

        const brand = this.brandItems.find((b) => b.display_name === storedBrand)
        if (!brand) return

        this.loadingLines = true
        try {
            const res = await axios.get(`${this.apiUrl}/machine/autoloader/filaments`, {
                params: { brand: brand.filepath },
            })
            this.productLineItems = res.data?.result?.product_lines ?? []
        } catch (e) {
            this.productLineItems = []
            this.loadingLines = false
            return
        }
        this.loadingLines = false
        this.selectedBrandPath = brand.filepath

        if (!storedLine) return
        const line = this.productLineItems.find((l) => l.display_name === storedLine)
        if (!line) return
        this.colorItems = [
            ...this.enrichColors(line.colors, line),
            { id: '__custom__', name: '✨ Custom color', hex: '' },
        ]
        this.selectedLineId = line.line_id

        if (!storedColorName && !storedHex) return
        const norm = (s: string): string => s.replace(/^#/, '').toUpperCase()
        // Authoritative primary hex from the structured fields, with the
        // legacy slash-joined fallback for old profiles.
        const firstHex = (this.saColorParts(i)[0] ?? storedHex.split('/')[0] ?? '')
        const color = this.colorItems.find((c) => {
            if (c.id === '__custom__') return false
            if (storedColorName && c.name === storedColorName) return true
            if (firstHex && norm(c.hex) === norm(firstHex)) return true
            return false
        })
        if (color) {
            this.selectedColorId = color.id
        } else if (storedHex) {
            // Profile has a hex that doesn't match any catalog color in this line
            // (custom-typed color or multi-color) → pre-select the Custom entry.
            this.selectedColorId = '__custom__'
        }
    }

    /**
     * Hydrate the custom-color editor (mode toggle + customHexes) from the
     * authoritative parts array + mode supplied by the SA mixin. The mixin
     * already prefers the structured `path_color_types` / `path_color_hex2s`
     * / `path_color_hex3s` fields and falls back to slash-joined for legacy
     * data, so we don't duplicate that logic here.
     */
    hydrateCustomHexesFromParts(
        parts: string[],
        mode: 'none' | 'single' | 'dual' | 'gradient' | 'multi'
    ): void {
        const safe = (h: string | undefined, fallback: string): string =>
            (h || '').trim() || fallback
        if (mode === 'multi' || parts.length >= 3) {
            this.colorMode = 'tri'
            this.editColorType = 'tri'
            this.customHexes = [
                safe(parts[0], 'FFFFFF'),
                safe(parts[1], '000000'),
                safe(parts[2], '808080'),
            ]
        } else if (mode === 'dual' || (mode === 'none' && parts.length === 2)) {
            this.colorMode = 'dual'
            this.editColorType = 'dual'
            this.customHexes = [safe(parts[0], 'FFFFFF'), safe(parts[1], '000000'), '808080']
        } else if (mode === 'gradient') {
            // Editor toggle has no gradient slot — fall back to single but
            // preserve the type for save.
            this.colorMode = 'single'
            this.editColorType = 'gradient'
            this.customHexes = [safe(parts[0], 'FFFFFF'), safe(parts[1], '000000'), '808080']
        } else {
            this.colorMode = 'single'
            this.editColorType = 'single'
            this.customHexes = [safe(parts[0], 'FFFFFF'), '000000', '808080']
        }
    }

    buildCustomHex(): string {
        const clean = (h: string): string =>
            h.replace(/^#/, '').padEnd(6, '0').substring(0, 6).toUpperCase()
        if (this.colorMode === 'single') {
            const first = (this.customHexes[0] || '').trim()
            if (!first) return ''
            return `#${clean(first)}`
        }
        const count = this.pieSliceCount
        return this.customHexes
            .slice(0, count)
            .map((h) => `#${clean(h || '000000')}`)
            .join('/')
    }

    async fetchBrands(): Promise<void> {
        this.loadingBrands = true
        try {
            const res = await axios.get(`${this.apiUrl}/machine/autoloader/brands`)
            this.brandItems = res.data?.result?.brands ?? []
        } catch (e) {
            this.brandItems = []
        } finally {
            this.loadingBrands = false
        }
    }

    async onBrandChange(filepath: string | null): Promise<void> {
        this.productLineItems = []
        this.colorItems = []
        this.selectedLineId = ''
        this.selectedColorId = ''
        if (!filepath) return
        this.loadingLines = true
        try {
            const res = await axios.get(`${this.apiUrl}/machine/autoloader/filaments`, {
                params: { brand: filepath },
            })
            const data = res.data?.result ?? {}
            this.productLineItems = data.product_lines ?? []
            if (data.brand) this.editBrand = data.brand
        } catch (e) {
            this.productLineItems = []
        } finally {
            this.loadingLines = false
        }
    }

    /**
     * Enrich catalog colors with `mode` + `hexes` so multi-color entries
     * render correctly in the dropdown pie swatches and can auto-set the
     * profile editor's single/dual/tri toggle on selection.
     */
    enrichColors(colors: SaColor[], line: SaProductLine): SaColor[] {
        return colors.map((c) => {
            const info = parseMultiColor(c.name, c.hex, line, {
                color_type: c.color_type,
                hex_2: c.hex_2,
                hex_3: c.hex_3,
            })
            return { ...c, mode: info.mode, hexes: info.hexes }
        })
    }

    /**
     * CSS background for a catalog color swatch, matching KlipperScreen:
     *   single   → solid circle
     *   dual     → vertical left/right split  (linear-gradient with hard 50% stop)
     *   tri      → conic 120° sectors starting from top
     *   gradient → horizontal linear-gradient (smooth). For gradient entries
     *              that only carry one hex, we generate a lighter variant so
     *              the swatch still visibly reads as a gradient.
     */
    catalogSwatchStyle(color: SaColor): Record<string, string> {
        if (!color) return { background: 'transparent' }
        const source = color.hexes && color.hexes.length > 0 ? color.hexes : [color.hex]
        const list = source
            .filter((h) => h)
            .map((h) => (h.startsWith('#') ? h : `#${h}`))
        if (list.length === 0) {
            return {
                background: 'transparent',
                border: '1px dashed rgba(255,255,255,0.35)',
            }
        }
        const border = `1px solid ${saBorderForHex(list[0])}`
        const mode = color.mode ?? 'single'
        if (mode === 'gradient') {
            const start = list[0]
            const end = list[1] ?? this.lightenHex(start, 0.35)
            return { background: `linear-gradient(to right, ${start}, ${end})`, border }
        }
        if (mode === 'dual' && list.length >= 2) {
            return {
                background: `linear-gradient(to right, ${list[0]} 0 50%, ${list[1]} 50% 100%)`,
                border,
            }
        }
        if (mode === 'tri' && list.length >= 3) {
            const step = 100 / 3
            const stops = list
                .slice(0, 3)
                .map(
                    (h, i) =>
                        `${h} ${(i * step).toFixed(2)}% ${((i + 1) * step).toFixed(2)}%`
                )
                .join(', ')
            return { background: `conic-gradient(from -90deg, ${stops})`, border }
        }
        return { background: list[0], border }
    }

    /** Nudge a hex color toward white by `amount` (0-1). Used for gradient previews
     *  when only one hex is available. */
    lightenHex(hex: string, amount: number): string {
        const h = hex.replace(/^#/, '').padEnd(6, '0').substring(0, 6)
        const ch = (i: number): number =>
            Math.min(255, parseInt(h.slice(i, i + 2), 16) + Math.round(amount * 255))
        const r = ch(0).toString(16).padStart(2, '0')
        const g = ch(2).toString(16).padStart(2, '0')
        const b = ch(4).toString(16).padStart(2, '0')
        return `#${r}${g}${b}`.toUpperCase()
    }

    onLineChange(lineId: string | null): void {
        this.colorItems = []
        this.selectedColorId = ''
        if (!lineId) return
        const line = this.productLineItems.find((l) => l.line_id === lineId)
        if (!line) return
        this.colorItems = [
            ...this.enrichColors(line.colors, line),
            { id: '__custom__', name: '✨ Custom color', hex: '' },
        ]
        this.editMaterial = line.material
        this.editLine = line.display_name
        this.editLoadTemp = line.load_temp
        this.editUnloadTemp = line.unload_temp
        this.editPurgeSpeed = line.purge_speed
        this.editPurgeLength = line.purge_length
    }

    onColorChange(colorId: string | null): void {
        if (!colorId) return
        if (colorId === '__custom__') {
            // Leave editColorName / editColorHex / customHexes as they are —
            // user will configure via picker/slider.
            return
        }
        const color = this.colorItems.find((c) => c.id === colorId)
        if (!color) return
        this.editColorName = color.name
        // Auto-set the mode toggle from the catalog's multi-color info. Gradient
        // falls back to single mode since the toggle has no gradient position,
        // but editColorType preserves it for the save payload.
        const rawMode = color.mode ?? 'single'
        const hexes = color.hexes ?? [color.hex]
        this.colorMode = rawMode === 'gradient' ? 'single' : rawMode
        this.editColorType = rawMode
        const clean = (h: string): string => h.replace(/^#/, '').toUpperCase()
        this.customHexes = [
            clean(hexes[0] || color.hex || 'FFFFFF'),
            clean(hexes[1] || '000000'),
            clean(hexes[2] || '808080'),
        ]
        // editColorHex still used by the "Current profile" summary in the header.
        // For multi-color entries, store the slash-joined form so saColorBackground
        // renders a pie there too.
        if (this.colorMode === 'single') {
            this.editColorHex = clean(hexes[0] || color.hex)
        } else {
            const count = this.colorMode === 'tri' ? 3 : 2
            this.editColorHex = hexes
                .slice(0, count)
                .map((h) => `#${clean(h)}`)
                .join('/')
        }
    }

    resetToDefault(): void {
        const line = this.selectedLine
        if (!line) return
        this.editLoadTemp = line.load_temp
        this.editUnloadTemp = line.unload_temp
        this.editPurgeSpeed = line.purge_speed
        this.editPurgeLength = line.purge_length
    }

    backToControls(): void {
        this.pathView = 'controls'
    }

    /**
     * Engage the currently selected path: move the selector to `pathModalIdx`
     * first, then engage the servo. Noop if not homed — the button should be
     * disabled in that case, but we guard again here defensively.
     */
    doEngage(): void {
        if (this.pathModalIdx === null) return
        if (!this.isSelectorHomed) return
        const script = [`SA_SELECT TOOL=${this.pathModalIdx}`, `SA_ENGAGE`].join('\n')
        this.saGcode(script)
    }

    doLoad(): void {
        if (this.pathModalIdx === null) return
        void this.runAction('load', `SA_LOAD TOOL=${this.pathModalIdx}`)
    }

    doUnload(): void {
        if (this.pathModalIdx === null) return
        void this.runAction('unload', `SA_UNLOAD TOOL=${this.pathModalIdx}`)
    }

    sendCalResponse(): void {
        const val = this.calResponse.trim()
        if (!val) return
        this.saGcode(`SA_RESPOND VALUE=${val}`)
        this.calResponse = ''
    }

    /** Quick-action button — sends a fixed VALUE for the most common prompts
     *  (yes/no/ok/continue/cancel) without making the user type. */
    sendPromptValue(value: string): void {
        this.saGcode(`SA_RESPOND VALUE=${value}`)
        this.calResponse = ''
    }

    /** Path-action button on the post-load/post-unload prompt — sends
     *  `SA_RESPOND VALUE=load:N` or `unload:N`, mirroring KlipperScreen's
     *  sa_post_load.py path grids. */
    sendPathAction(action: 'load' | 'unload', path: number): void {
        this.saGcode(`SA_RESPOND VALUE=${action}:${path}`)
        this.calResponse = ''
    }

    /** Which prompt UI to render for the current cal_state.
     *   'load'    → post-load action panel (PURGE / PARK / EXIT + path grids)
     *   'unload'  → post-unload action panel (PARK / EXIT / LOAD SAME + path grids)
     *   'generic' → calibration prompt (cal_prompt text + Yes/No/OK/...)
     *  Mirrors the cal_state values KlipperScreen's sa_post_load.py reacts to. */
    get promptKind(): 'load' | 'unload' | 'generic' {
        const s = this.saStatus.cal_state
        if (s === 'load_purge') return 'load'
        if (s === 'unload_done') return 'unload'
        return 'generic'
    }

    get promptDialogTitle(): string {
        if (this.promptKind === 'load') return this.$t('Panels.AutoloaderPanel.PromptTitleLoad') as string
        if (this.promptKind === 'unload') return this.$t('Panels.AutoloaderPanel.PromptTitleUnload') as string
        return this.$t('Panels.AutoloaderPanel.PromptTitle') as string
    }

    @Watch('saIsCalibrating', { immediate: true })
    onCalStateChange(active: boolean): void {
        // Auto-open the prompt dialog when the autoloader requests user
        // input, auto-close when it clears. Persistent + non-dismissable
        // to ensure the user always responds to a real printer prompt.
        // A prompt from the printer is not a peer of the dialogs the user
        // opened -- it is waiting on an answer, and stacking it on top of them
        // left two modals live at once with the focus and z-order decided by
        // whichever happened to mount last. Take the screen instead.
        if (active) {
            this.pathModalOpen = false
            this.pickerOpen = false
            // The guide is deliberately NOT closed here. onPromptWaitingChange
            // owns it, because closing it needs to record that the guide is
            // owed a reopen -- and whichever of the two ran first would
            // otherwise decide whether it ever came back.
        }

        // Calibration prompts are emitted by the backend as native
        // action:prompt_* now, and Mainsail renders those itself -- with the
        // phase title and only the buttons that phase offers. Opening this
        // panel for them too put two dialogs on screen at once: the native one
        // showing the computed positions, and this generic
        // "Autoloader needs your input" with Yes/No/OK/Continue/Cancel
        // covering it.
        //
        // 'load' and 'unload' stay, because those are path grids with colours
        // and per-tool buttons that the prompt protocol cannot express.
        this.promptOpen = active && this.promptKind !== 'generic'
        if (!active) this.calResponse = ''
    }

    /*
     * Give Mainsail's prompt dialog the calibration guide's structure.
     *
     * See the comment on saPromptSkin for why this is done by decorating the
     * rendered lines rather than by sending markup: the prompt protocol has no
     * markup, and Mainsail escapes the text.
     */
    private saPromptObserver: MutationObserver | null = null

    installPromptSkin(): void {
        if (this.saPromptObserver) return
        const CHECK = '✓'
        const WARN = '⚠'

        const decorate = (): void => {
            const dlg = document.querySelector('.macro_prompt-dialog')
            if (!dlg) return
            let block: '' | 'expect' | 'warn' = ''
            dlg.querySelectorAll('p').forEach((el, idx) => {
                const raw = (el.textContent || '')
                const t = raw.trim()
                el.classList.remove(
                    'sa-p-step', 'sa-p-blank', 'sa-p-expect', 'sa-p-warn',
                    'sa-p-expect-head', 'sa-p-warn-head')
                if (!t) {
                    // The spacer lines are what open those big gaps. The
                    // backend still sends them because KlipperScreen uses them
                    // for spacing; here the stylesheet provides it instead.
                    el.classList.add('sa-p-blank')
                    return
                }
                if (t.startsWith(CHECK)) { block = 'expect'; el.classList.add('sa-p-expect-head'); return }
                if (t.startsWith(WARN))  { block = 'warn';   el.classList.add('sa-p-warn-head');   return }
                if (t.startsWith('\u2022')) {
                    el.classList.add(block === 'warn' ? 'sa-p-warn' : 'sa-p-expect')
                    return
                }
                // A non-bullet line ends whichever block was running; the very
                // first one is the step name, which the guide prints as its
                // section header.
                block = ''
                if (idx === 0) el.classList.add('sa-p-step')
            })
        }

        this.saPromptObserver = new MutationObserver(() => decorate())
        this.saPromptObserver.observe(document.body,
                                      { childList: true, subtree: true })
        decorate()
    }

    saveProfile(): void {
        if (this.pathModalIdx === null) return
        const i = this.pathModalIdx
        const q = (s: string): string => `"${s}"`
        const clean = (h: string): string =>
            h.replace(/^#/, '').padEnd(6, '0').substring(0, 6).toUpperCase()
        // Use the editor's authoritative type ('single' | 'dual' | 'tri' | 'gradient').
        // Pack each slot into its own field — COLOR_HEX is the primary single
        // value, COLOR_HEX_2 / COLOR_HEX_3 carry secondary/tertiary. This is
        // the convention the autoloader klipper module exposes (path_color_types
        // / path_color_hex2s / path_color_hex3s), so KlipperScreen and mainsail
        // both read back consistent data.
        const type = this.editColorType
        const slot = (idx: number): string => {
            const raw = (this.customHexes[idx] || '').trim()
            return raw ? `#${clean(raw)}` : ''
        }
        const hex1 = slot(0)
        const hex2 = type === 'dual' || type === 'tri' || type === 'gradient' ? slot(1) : ''
        const hex3 = type === 'tri' ? slot(2) : ''

        let cmd = `SA_SET_MATERIAL TOOL=${i}`
        cmd += ` MATERIAL=${q(this.editMaterial)}`
        cmd += ` BRAND=${q(this.editBrand)}`
        cmd += ` LINE=${q(this.editLine)}`
        cmd += ` COLOR_NAME=${q(this.editColorName)}`
        cmd += ` COLOR_HEX=${q(hex1)}`
        cmd += ` COLOR_TYPE=${q(type)}`
        cmd += ` COLOR_HEX_2=${q(hex2)}`
        cmd += ` COLOR_HEX_3=${q(hex3)}`
        cmd += ` LOAD_TEMP=${this.editLoadTemp}`
        cmd += ` UNLOAD_TEMP=${this.editUnloadTemp}`
        cmd += ` PURGE_SPEED=${this.editPurgeSpeed}`
        cmd += ` PURGE_LENGTH=${this.editPurgeLength}`
        // Return to the controls view once the write has actually gone out,
        // rather than immediately — switching straight back made a failed save
        // look identical to a successful one.
        void this.runAction('save', cmd).then(() => {
            this.pathView = 'controls'
        })
    }

    clearProfile(): void {
        if (this.pathModalIdx === null) return
        const i = this.pathModalIdx
        this.saGcode(
            `SA_SET_MATERIAL TOOL=${i} MATERIAL="" BRAND="" LINE="" ` +
                `COLOR_NAME="" COLOR_HEX="" COLOR_TYPE="single" ` +
                `COLOR_HEX_2="" COLOR_HEX_3="" ` +
                `LOAD_TEMP=200 UNLOAD_TEMP=185 ` +
                `PURGE_SPEED=5 PURGE_LENGTH=30`
        )
        // Reset edit fields
        this.editMaterial = ''
        this.editBrand = ''
        this.editLine = ''
        this.editColorName = ''
        this.editColorHex = ''
        this.editLoadTemp = 200
        this.editUnloadTemp = 185
        this.editPurgeSpeed = 5
        this.editPurgeLength = 30
        // Reset catalog dropdowns
        this.selectedBrandPath = ''
        this.selectedLineId = ''
        this.selectedColorId = ''
        this.productLineItems = []
        this.colorItems = []
        // Reset custom-color state
        this.colorMode = 'single'
        this.editColorType = 'single'
        this.customHexes = ['FFFFFF', '000000', '808080']
    }
}
</script>

<style scoped>
/*
 * ── Guide step pages, on the prompt's design ──────────────────────────────
 *
 * These mirror the .sa-p-* rules used on Mainsail's prompt dialog. The numbers
 * are copied from there rather than chosen again, because the whole point is
 * that a step page and the prompt it raises are the same design.
 */
.sa-step-head {
    font-size: 0.875rem;
    font-weight: 500;
    margin-bottom: 6px;
}
.sa-step-body {
    font-size: 0.875rem;
    line-height: 1.45;
    margin-bottom: 8px;
}
.sa-step-note {
    font-size: 0.875rem;
    line-height: 1.45;
    margin-bottom: 8px;
}
.sa-step-note--ok {
    color: #81c784;
}
.sa-step-note--warn {
    color: #ffb74d;
}
/* Actions sit as a centred row, the way the prompt lays its answers out,
   rather than left-aligned against the text. */
.sa-step-btn {
    text-transform: none !important;
    letter-spacing: 0.02em !important;
}
/* The grid cells use the prompt's secondary button -- the BUZZ AGAIN one --
   so a six-cell grid reads as a set of choices rather than six primary
   actions competing with each other. */
.sa-step-btn--grid {
    background: rgba(127, 127, 127, 0.16) !important;
}
/* Mainsail's prompt puts its footer buttons in a v-card__actions with 8px of
   padding, right-aligned after a spacer. Same here. */
.sa-step-actions {
    padding: 8px !important;
}
/*
 * The guide is the same box as the prompt: 548px, fixed.
 *
 * Vuetify centres dialogs vertically, so a card sized to its content moves
 * every time the content changes -- which through nine steps of different
 * lengths meant the window jumped on every NEXT, and jumped again handing off
 * to a prompt of a different height. Mainsail's prompt avoids it by being
 * built with height: 548; this matches, and the body scrolls inside.
 */
.sa-guide-card {
    height: 548px;
    display: flex;
    flex-direction: column;
}
.sa-guide-card .sa-cal-body {
    flex: 1 1 auto;
    overflow-y: auto;
    max-height: none;
}
/* Phones get the full screen, the way Mainsail's prompt does. */
@media (max-height: 620px) {
    .sa-guide-card {
        height: auto;
        max-height: 92vh;
    }
}




/* ── Prompt dialog body ──────────────────────────────────── */
.sa-prompt-text {
    font-size: 14px;
    line-height: 1.5;
    color: rgba(255, 255, 255, 0.92);
    white-space: pre-wrap;
}
.sa-prompt-actions {
    background: rgba(255, 255, 255, 0.02);
}
.sa-prompt-header {
    text-align: center;
}
.sa-prompt-headline {
    font-size: 15px;
    letter-spacing: 0.5px;
    margin-bottom: 4px;
}
.sa-prompt-row {
    background: rgba(255, 255, 255, 0.02);
}
.sa-path-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(48px, 1fr));
    gap: 6px;
}
.sa-path-btn {
    min-width: 0 !important;
    padding: 0 !important;
    font-weight: 600;
}

/* ── Calibration toolbar ─────────────────────────────────── */
.sa-cal-bar {
    display: flex;
    justify-content: flex-end;
    padding: 8px 12px 6px;
    border-bottom: 1px solid rgba(255, 255, 255, 0.06);
}
.sa-cal-btn {
    text-transform: none !important;
    letter-spacing: 0 !important;
    min-height: 28px !important;
    border-color: rgba(255, 255, 255, 0.2) !important;
    color: rgba(255, 255, 255, 0.87) !important;
}

/* Calibration dialog body can scroll if a step gets tall */
.sa-cal-body {
    max-height: 60vh;
}

/* Status banner at top of each step — current calibrated values */
.sa-cal-status {
    padding: 8px 12px;
    border-radius: 4px;
    font-size: 12px;
    margin-bottom: 10px;
    line-height: 1.35;
    font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}
.sa-cal-status--ok {
    background: rgba(76, 175, 80, 0.15);
    color: #81c784;
    border-left: 3px solid #4caf50;
}
.sa-cal-status--warn {
    background: rgba(255, 152, 0, 0.12);
    color: #ffb74d;
    border-left: 3px solid #ff9800;
}

/* "What to expect" green callout */
.sa-cal-grid {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 8px;
}
.sa-cal-cell-val {
    text-align: center;
    font-size: 0.78rem;
    line-height: 1.4;
    margin-bottom: 2px;
}
/* Done and not-done read at a glance, the same two colours the status line
   uses, so one page does not invent a third vocabulary. */
.sa-cal-done { color: #66BB6A; }
.sa-cal-todo { color: #9E9E9E; }

.sa-cal-expect {
    margin-top: 10px;
    padding: 8px 12px;
    font-size: 12px;
    line-height: 1.45;
    color: rgba(129, 199, 132, 0.92);
    background: rgba(76, 175, 80, 0.06);
    border-left: 2px solid #4caf50;
    border-radius: 0 4px 4px 0;
    white-space: pre-line;
}

/* "Watch out for" amber callout */
.sa-cal-warn {
    margin-top: 6px;
    padding: 8px 12px;
    font-size: 12px;
    line-height: 1.45;
    color: rgba(255, 183, 77, 0.92);
    background: rgba(255, 152, 0, 0.05);
    border-left: 2px solid #ff9800;
    border-radius: 0 4px 4px 0;
    white-space: pre-line;
}

/* Per-tool calibration grid (steps 5 and 6) */
.sa-tool-grid {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 8px;
}
.sa-tool-cell {
    display: flex;
    flex-direction: column;
    align-items: stretch;
}

.sa-save-config {
    min-width: 0 !important;
    padding: 0 6px !important;
}

/* ── Grid layout ─────────────────────────────────────────── */
.sa-grid {
    width: 100%;
    /* Establish a containment context so the narrow-mode rules below react
       to the PANEL's own width, not the viewport. This means widescreen
       middle/right columns (which are wider) keep the full layout, while
       only the narrow leftmost widescreen column triggers compaction. */
    container-type: inline-size;
    container-name: sa-grid;
}
.sa-row {
    display: grid;
    grid-template-columns: 72px 24px 1fr 80px 24px 24px 24px;
    gap: 6px;
    align-items: center;
    padding: 6px 12px;
}

/* Narrow-panel layout (widescreen leftmost column).
   Drops the three sensor-dot columns — sensor state is still inspectable
   from the controls popup when you tap the row. The Loadout chip stays
   since it already conveys the combined sensor state via saEffectiveState.
   Material/brand/color text is forced to single-line with ellipsis so it
   never overflows the row height when the column is squeezed. */
@container sa-grid (max-width: 540px) {
    .sa-row {
        /* minmax(0, 1fr) is critical — the default 1fr won't shrink below
           the material cell's intrinsic content width, which is what was
           pushing text off the right edge. */
        grid-template-columns: 52px 22px minmax(0, 1fr) auto;
        gap: 6px;
    }
    .sa-row > :nth-child(5),
    .sa-row > :nth-child(6),
    .sa-row > :nth-child(7) {
        display: none;
    }
    .sa-material-cell {
        min-width: 0;
    }
    .sa-material-cell > div {
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }
}

.sa-center {
    display: flex;
    align-items: center;
    justify-content: center;
}

/* ── Header row ──────────────────────────────────────────── */
/* ── Status strip ────────────────────────────────────────── */
.sa-status-strip {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    border-bottom: 1px solid rgba(255, 255, 255, 0.06);
    background: rgba(0, 0, 0, 0.18);
}
.sa-status-cell {
    padding: 6px 12px;
    min-width: 0;
    border-right: 1px solid rgba(255, 255, 255, 0.06);
}
.sa-status-cell:last-child {
    border-right: none;
}
.sa-status-label {
    display: block;
    font-size: 10px;
    line-height: 1.4;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    color: rgba(255, 255, 255, 0.45);
}
.sa-status-value {
    display: block;
    font-size: 13px;
    font-weight: 600;
    line-height: 1.4;
    color: rgba(255, 255, 255, 0.87);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}
.sa-status-value--accent {
    color: var(--v-primary-base);
}
.sa-status-sub {
    font-weight: 400;
    font-size: 11px;
    color: rgba(255, 255, 255, 0.55);
}

/* Four columns is too tight on a phone; two rows read better than
   ellipsised values. */
@media (max-width: 480px) {
    .sa-status-strip {
        grid-template-columns: repeat(2, 1fr);
    }
    .sa-status-cell:nth-child(-n + 2) {
        border-bottom: 1px solid rgba(255, 255, 255, 0.06);
    }
    .sa-status-cell:nth-child(2n) {
        border-right: none;
    }
}

.sa-header-row {
    font-size: 10px;
    color: rgba(255, 255, 255, 0.45);
    text-transform: uppercase;
    letter-spacing: 0.5px;
    padding: 4px 12px;
    background: rgba(0, 0, 0, 0.18);
    border-bottom: 1px solid rgba(255, 255, 255, 0.06);
}

/* ── Data rows ───────────────────────────────────────────── */
.sa-data-row {
    border-left: 3px solid transparent;
    border-bottom: 1px solid rgba(255, 255, 255, 0.06);
    transition: background 0.12s, border-color 0.12s;
    cursor: pointer;
    height: 52px;
}
.sa-data-row:last-child {
    border-bottom: none;
}
.sa-data-row:hover {
    background: rgba(255, 255, 255, 0.04);
}
.sa-row--active {
    border-left-color: var(--v-primary-base);
}
.sa-row--open {
    border-left-color: var(--v-accent-base);
}
.sa-row--active.sa-row--open {
    border-left-color: var(--v-primary-base);
}

.sa-tool-label {
    font-weight: 600;
    font-size: 0.8rem;
}
.sa-swatch-cell {
    display: flex;
    align-items: center;
    justify-content: center;
}
.sa-material-cell {
    overflow: hidden;
    line-height: 1.15;
}

/* ── Color swatch ────────────────────────────────────────── */
.sa-color-swatch {
    width: 18px;
    height: 18px;
    border-radius: 50%;
    box-sizing: border-box;
}
.sa-color-swatch--svg {
    /* SVG paths form their own circle — strip the rounded background clip
       and any border so each slice's arc edge defines the perimeter. */
    border-radius: 0;
    border: none;
    background: transparent;
    overflow: visible;
    display: block;
}
.sa-color-swatch-lg {
    width: 36px;
    height: 36px;
    border-radius: 50%;
    flex-shrink: 0;
    box-sizing: border-box;
}
.sa-dd-swatch {
    width: 16px;
    height: 16px;
    border-radius: 50%;
    flex-shrink: 0;
    box-sizing: border-box;
}
.sa-current-profile {
    padding: 8px 12px;
    background: rgba(255, 255, 255, 0.03);
    border: 1px solid rgba(255, 255, 255, 0.06);
    border-radius: 4px;
}

/* ── Mode slider ─────────────────────────────────────────── */
.sa-mode-slider ::v-deep .v-slider__tick-label {
    font-size: 11px;
}
.sa-mode-slider {
    padding-top: 6px;
}

/* ── Custom pie preview ──────────────────────────────────── */
.sa-pie {
    width: 80px;
    height: 80px;
    display: block;
    flex-shrink: 0;
}
.sa-pie-slice {
    cursor: pointer;
    transition: filter 0.15s;
}
.sa-pie-slice:hover {
    filter: brightness(1.25);
}

/* ── Sensor dots ─────────────────────────────────────────── */
.sa-dot {
    width: 10px;
    height: 10px;
    border-radius: 50%;
    flex-shrink: 0;
    box-sizing: border-box;
}
.sa-dot--on {
    background-color: #4caf50;
}
.sa-dot--off {
    background-color: transparent;
    border: 2px solid rgba(255, 255, 255, 0.3);
}

/* ── Hint text ───────────────────────────────────────────── */
.sa-hint {
    font-size: 11px !important;
}

/* ── Dialog ──────────────────────────────────────────────── */
/*
 * .panel and .panel-toolbar are Mainsail's own, so these dialogs inherit the
 * theme the same way the native prompt and every dashboard panel do. What
 * follows only fills the gaps -- it must not repaint anything, or a light
 * theme goes back to showing dark cards.
 */
.sa-dialog-title {
    flex: 0 0 auto;
}
.sa-dialog-title >>> .v-toolbar__content {
    padding: 0 8px 0 16px;
}
.sa-dialog-heading {
    font-size: 1.25rem;
    font-weight: 400;
    line-height: 2rem;
    letter-spacing: 0.0125em;
}
/*
 * No fallback background here on purpose. The first attempt at one used a
 * higher-specificity selector than Mainsail's .panel-toolbar and so overrode
 * the colour it was meant to be backing up -- the header came out flat grey on
 * the very build where the real rule was present and working.
 */

/* ── Profile tile (replaces Edit Profile button) ─────────── */
.sa-profile-tile {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 10px 12px;
    background: #272727;
    border: 1px solid rgba(255, 255, 255, 0.12);
    border-radius: 4px;
    cursor: pointer;
    transition: background 0.12s, border-color 0.12s;
}
.sa-profile-tile:hover {
    background: #2f2f2f;
    border-color: rgba(255, 255, 255, 0.2);
}
.sa-profile-tile-swatch {
    width: 32px;
    height: 32px;
    flex-shrink: 0;
}
.sa-profile-tile-info {
    flex: 1;
    min-width: 0;
    line-height: 1.2;
}
.sa-profile-tile-icon {
    opacity: 0.6;
    flex-shrink: 0;
}

/* ── Connected button group ──────────────────────────────── */
.sa-btn-group {
    display: flex;
    border-radius: 4px;
    overflow: hidden;
}
.sa-group-btn {
    flex: 1;
    border-radius: 0 !important;
    background: #272727 !important;
    border: thin solid rgba(255, 255, 255, 0.12) !important;
    border-left-width: 0 !important;
    box-shadow: none !important;
    height: 28px !important;
    min-width: 0 !important;
    font-size: 0.75rem !important;
    text-transform: none !important;
    letter-spacing: 0 !important;
    color: rgba(255, 255, 255, 0.87) !important;
}
.sa-group-btn:first-child {
    border-radius: 4px 0 0 4px !important;
    border-left-width: thin !important;
}
.sa-group-btn:last-child {
    border-radius: 0 4px 4px 0 !important;
}

/* State-aware colors for selector buttons (Home/Engage/Disengage).
   Match Mainsail's existing home-axis indicator pattern: primary when
   the state is active (e.g. homed / engaged), warning when not. */
.sa-group-btn.sa-group-btn--primary {
    background: var(--v-primary-base) !important;
    border-color: var(--v-primary-base) !important;
    color: #fff !important;
}
.sa-group-btn.sa-group-btn--warning {
    background: var(--v-warning-base) !important;
    border-color: var(--v-warning-base) !important;
    color: #fff !important;
}

/* ── Preset quick-select (match extruder _btn-qs) ────────── */
.sa-preset-btn {
    opacity: 0.8;
    height: 24px !important;
    font-size: 0.75rem !important;
}
.sa-preset-btn--active {
    opacity: 1;
    background: rgba(var(--v-primary-base), 0.16) !important;
    color: var(--v-primary-base) !important;
    border-color: var(--v-primary-base) !important;
    /* Restore the left border so the active button is fully outlined on
       all four sides — not just three — regardless of its position in
       the connected button group. */
    border-left-width: thin !important;
    position: relative;
    z-index: 1;
}

/* ── Feed / Retract action buttons ───────────────────────── */
.sa-feed-btn {
    background: #272727 !important;
    border: 1px solid rgba(255, 255, 255, 0.12) !important;
    color: rgba(255, 255, 255, 0.87) !important;
    text-transform: none !important;
    letter-spacing: 0 !important;
    min-height: 32px !important;
}
</style>

<style>
/*
 * ── Mainsail's prompt dialog, wearing the guide's clothes ──────────────────
 *
 * Global on purpose. The dialog is rendered by Mainsail, not by this
 * component, so a scoped rule would never reach it. Everything here is under
 * .macro_prompt-dialog, Mainsail's own class for that card, so nothing else on
 * the page is touched.
 *
 * The classes on the <p> elements come from installPromptSkin(), which reads
 * the markers the backend puts at the start of each line. Mainsail renders
 * prompt_text as escaped plain text in <p class="mb-0"> -- no markup and no
 * per-line classes -- so a marker is the only channel there is.
 *
 * The colours are copied from .sa-cal-expect / .sa-cal-warn rather than picked
 * again by eye: the whole point is that a prompt and the guide page behind it
 * are the same two blocks.
 */
.macro_prompt-dialog .v-card__text {
    padding: 16px !important;
    font-size: 0.875rem;
}
/*
 * Kill the open/close animation on the prompt dialog.
 *
 * Every re-render of a prompt sends action:prompt_end before its
 * action:prompt_begin, and Mainsail's showDialog is
 *   lastPromptBeginPos > lastPromptClosePos
 * so the dialog genuinely unmounts and remounts between the two -- that is
 * the flash.
 *
 * The leading prompt_end cannot simply be dropped: KlipperScreen's
 * prompt_show handler is `if not self.prompt: self.show()`, so without the
 * close it leaves the OLD dialog on screen with the new buttons never
 * rendered. A stale dialog showing the wrong buttons is far worse than a
 * flash, so the emit order stays and the animation goes instead: the swap
 * becomes a single frame rather than a fade out and back in.
 */
.v-dialog:has(.macro_prompt-dialog),
.v-dialog__content:has(.macro_prompt-dialog),
.v-dialog:has(.sa-dialog-title),
.v-dialog__content:has(.sa-dialog-title) {
    transition: none !important;
    animation: none !important;
}

/* Every prompt_text is its own .row, and the row's default margins are what
   opened the wide gaps between each line. */
.macro_prompt-dialog .v-card__text > .row {
    margin: 0;
}
.macro_prompt-dialog .v-card__text > .row > .col {
    padding: 0;
}
.macro_prompt-dialog p {
    line-height: 1.45;
}
/* Spacer lines, sent for KlipperScreen's benefit. Hidden rather than dropped
   from the protocol, so this stays presentation-only and KlipperScreen keeps
   the spacing it relies on. */
.macro_prompt-dialog p.sa-p-blank {
    display: none;
}
.macro_prompt-dialog p:not([class*="sa-p-"]) {
    margin-bottom: 8px !important;
}
/* The step name, styled as the guide styles its section header. */
.macro_prompt-dialog p.sa-p-step {
    font-weight: 500;
    margin-bottom: 6px !important;
}
/* ✓ What to expect — .sa-cal-expect, applied per line so a heading and its
   bullets share one background and one rule and read as a single block. */
.macro_prompt-dialog p.sa-p-expect-head,
.macro_prompt-dialog p.sa-p-expect {
    font-size: 12px;
    line-height: 1.45;
    color: rgba(129, 199, 132, 0.92);
    background: rgba(76, 175, 80, 0.06);
    border-left: 2px solid #4caf50;
    padding: 1px 12px;
}
/* ⚠ Watch out for — .sa-cal-warn. */
.macro_prompt-dialog p.sa-p-warn-head,
.macro_prompt-dialog p.sa-p-warn {
    font-size: 12px;
    line-height: 1.45;
    color: rgba(255, 183, 77, 0.92);
    background: rgba(255, 152, 0, 0.05);
    border-left: 2px solid #ff9800;
    padding: 1px 12px;
}
.macro_prompt-dialog p.sa-p-expect-head,
.macro_prompt-dialog p.sa-p-warn-head {
    font-weight: 500;
    margin-top: 10px !important;
    padding-top: 8px;
    border-radius: 0 4px 0 0;
}
/* Close the box on the last line of a run. :has() is what makes this work
   without the decorator having to know where a run ends. */
.macro_prompt-dialog p.sa-p-expect:last-child,
.macro_prompt-dialog p.sa-p-warn:last-child,
.macro_prompt-dialog p.sa-p-expect:has(+ p:not(.sa-p-expect)),
.macro_prompt-dialog p.sa-p-warn:has(+ p:not(.sa-p-warn)) {
    padding-bottom: 8px;
    border-radius: 0 0 4px 0;
}
/* The buttons, at the guide's scale rather than the dialog's default. */
.macro_prompt-dialog .v-card__text .v-btn {
    text-transform: none;
    letter-spacing: 0.02em;
}
</style>

