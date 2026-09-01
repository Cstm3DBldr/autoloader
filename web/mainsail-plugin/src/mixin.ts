import Vue from 'vue'
import Component from 'vue-class-component'
import { SAStatus } from './types'

const DEFAULT_SA: SAStatus = {
    num_paths: 0,
    current_path: -1,
    servo_engaged: false,
    path_states: [],
    encoder_dist: [],
    entry_filament: [],
    toolhead_filament: [],
    extruder_filament: [],
    filament_loaded: [],
    selector_position: 0,
    path_materials: [],
    path_brands: [],
    path_product_lines: [],
    path_color_names: [],
    path_color_hexes: [],
    path_color_types: [],
    path_color_hex2s: [],
    path_color_hex3s: [],
    path_load_temps: [],
    path_unload_temps: [],
    feed_speed: 0,
    purge_length: 0,
    nozzle_distance: 0,
    bowden_lengths: [],
    selector_positions: [],
    encoder_mpp: [],
    drive_rotation_distance: 0,
    cal_state: '',
    cal_path: -1,
    cal_prompt: '',
}

@Component
export default class SaMixin extends Vue {
    get saExists(): boolean {
        return 'autoloader' in this.$store.state.printer
    }

    get saStatus(): SAStatus {
        return (this.$store.state.printer.autoloader as SAStatus) ?? DEFAULT_SA
    }

    get saPathIndices(): number[] {
        return Array.from({ length: this.saStatus.num_paths }, (_, i) => i)
    }

    get saIsCalibrating(): boolean {
        return this.saStatus.cal_state !== ''
    }

    saStateColor(state: string): string {
        switch (state) {
            case 'loaded':
                return 'success'
            case 'partial':
                return 'warning'
            case 'unknown':
                return 'amber'
            default:
                return 'grey'
        }
    }

    /**
     * Mirror of KlipperScreen _effective_state() — derive path state from
     * sensors when available. The raw path_states from Klipper can read
     * 'unknown' before a load cycle completes even when sensors clearly
     * indicate filament presence.
     */
    saEffectiveState(idx: number): string {
        const sa = this.saStatus
        const entry = sa.entry_filament?.[idx]
        const toolhead = sa.toolhead_filament?.[idx]
        const extruder = sa.extruder_filament?.[idx]
        const reported = sa.path_states?.[idx] ?? 'unknown'

        if (entry === undefined || entry === null) return reported
        if (!entry && !toolhead && !extruder) return 'empty'
        if (entry && toolhead && extruder) return 'loaded'
        if (entry || toolhead || extruder) return 'partial'
        return reported
    }

    saColorHex(idx: number): string {
        const stored = (this.saStatus.path_color_hexes?.[idx] ?? '').trim()
        if (!stored) return ''
        // Multi-color hex is encoded slash-separated, e.g. "#FF0000/#00FF00".
        // For single-value consumers, return the first color.
        const first = stored.split('/')[0].trim().replace(/^#/, '')
        return first ? `#${first}` : ''
    }

    /**
     * CSS `background` value for a path's color swatch. Mirrors the KlipperScreen
     * sa_color_swatch rendering:
     *   - single hex     → solid flat color
     *   - 2 hexes, gradient name → horizontal linear-gradient (smooth blend)
     *   - 2 hexes, dual name     → vertical split (left = hex[0], right = hex[1])
     *   - 3+ hexes               → conic-gradient 120° sectors starting at 12 o'clock
     */
    saColorBackground(idx: number): string {
        const parts = this.saColorParts(idx)
        if (parts.length === 0) return ''
        if (parts.length === 1) return `#${parts[0]}`

        if (parts.length === 2) {
            const mode = this.saColorMode(idx)
            if (mode === 'gradient') {
                return `linear-gradient(to right, #${parts[0]}, #${parts[1]})`
            }
            // Dual → sharp vertical left/right split
            return `linear-gradient(to right, #${parts[0]} 0 50%, #${parts[1]} 50% 100%)`
        }
        // 3+ colors → conic pie, equal sectors, starting from top (12 o'clock).
        // Use degree-based hard stops to avoid the 100/3 rounding sliver.
        const step = 360 / parts.length
        const stops = parts.map((hex, i) => {
            const start = (i * step).toFixed(3)
            const end = ((i + 1) * step).toFixed(3)
            return `#${hex} ${start}deg ${end}deg`
        })
        return `conic-gradient(from -90deg, ${stops.join(', ')})`
    }

    /**
     * Raw hex parts ('FFFFFF', no '#') for a path's stored color.
     *
     * Authoritative source is the structured fields the autoloader klipper
     * module exposes — `path_color_hexes[i]` (primary), `path_color_hex2s[i]`
     * and `path_color_hex3s[i]`. Falls back to splitting `path_color_hexes[i]`
     * on '/' for legacy slash-joined data so older saved profiles still render.
     */
    saColorParts(idx: number): string[] {
        const norm = (h: string): string => h.trim().replace(/^#/, '').toUpperCase()
        const primary = norm(this.saStatus.path_color_hexes?.[idx] ?? '')
        const hex2 = norm(this.saStatus.path_color_hex2s?.[idx] ?? '')
        const hex3 = norm(this.saStatus.path_color_hex3s?.[idx] ?? '')
        // Structured fields take precedence when any secondary is populated.
        if (hex2 || hex3) {
            return [primary, hex2, hex3].filter((h) => h)
        }
        if (!primary) return []
        // Legacy slash-joined fallback (e.g. data saved before structured fields existed).
        if (primary.includes('/')) {
            return primary
                .split('/')
                .map((p) => norm(p))
                .filter((p) => p)
        }
        return [primary]
    }

    /**
     * Render mode for a path's stored color. Reads `path_color_types[i]`
     * directly when set — the klipper module exposes it as 'single', 'dual',
     * 'tri', or 'gradient'. Falls back to a name+count heuristic for legacy
     * data that predates the structured fields.
     */
    saColorMode(idx: number): 'none' | 'single' | 'dual' | 'gradient' | 'multi' {
        const parts = this.saColorParts(idx)
        if (parts.length === 0) return 'none'
        const stored = (this.saStatus.path_color_types?.[idx] ?? '').toLowerCase()
        if (stored === 'gradient') return 'gradient'
        if (stored === 'dual') return 'dual'
        if (stored === 'tri') return 'multi'
        if (stored === 'single') return 'single'
        // Legacy heuristic
        if (parts.length === 1) return 'single'
        if (parts.length === 2) {
            const name = (this.saStatus.path_color_names?.[idx] ?? '').toLowerCase()
            const isGradient = /gradient|rainbow|ocean|sunset|forest|galaxy|fade|shift/i.test(
                name
            )
            return isGradient ? 'gradient' : 'dual'
        }
        return 'multi'
    }

    /**
     * SVG paths for a dual swatch: two semicircles split vertically (left =
     * parts[0], right = parts[1]), matching the linear-gradient layout. Used
     * by the small panel swatch where a CSS hard-stop linear-gradient inside
     * border-radius:50% leaks one half past the perimeter on the other side.
     */
    saDualSlices(idx: number): Array<{ d: string; fill: string }> {
        const parts = this.saColorParts(idx)
        if (parts.length !== 2) return []
        const cx = 18
        const r = 18
        const yTop = 0
        const yBot = 36
        return [
            // Left half: arc from top → bottom going counter-clockwise (sweep=0).
            { d: `M ${cx} ${yTop} A ${r} ${r} 0 0 0 ${cx} ${yBot} Z`, fill: `#${parts[0]}` },
            // Right half: arc from top → bottom going clockwise (sweep=1).
            { d: `M ${cx} ${yTop} A ${r} ${r} 0 0 1 ${cx} ${yBot} Z`, fill: `#${parts[1]}` },
        ]
    }

    /**
     * SVG pie slices for multi-color swatches. Used by the small (18px) panel
     * swatch where conic-gradient anti-aliasing leaks the underlying slice
     * colors past the perimeter. Each slice is a true arc path bounded by the
     * circle, so there's no AA bleed at slice boundaries.
     *
     * Coordinates are in a 36×36 viewBox (the SVG scales to its container).
     */
    saPieSlices(idx: number): Array<{ d: string; fill: string }> {
        const parts = this.saColorParts(idx)
        if (parts.length < 3) return []
        const cx = 18
        const cy = 18
        const r = 18
        const step = 360 / parts.length
        const toRad = (deg: number) => (deg * Math.PI) / 180
        return parts.map((hex, i) => {
            // -90 puts 0° at 12 o'clock so the first slice starts at top.
            const startDeg = -90 + i * step
            const endDeg = -90 + (i + 1) * step
            const x1 = cx + r * Math.cos(toRad(startDeg))
            const y1 = cy + r * Math.sin(toRad(startDeg))
            const x2 = cx + r * Math.cos(toRad(endDeg))
            const y2 = cy + r * Math.sin(toRad(endDeg))
            const largeArc = step > 180 ? 1 : 0
            return {
                d: `M ${cx} ${cy} L ${x1.toFixed(3)} ${y1.toFixed(3)} A ${r} ${r} 0 ${largeArc} 1 ${x2.toFixed(3)} ${y2.toFixed(3)} Z`,
                fill: `#${hex}`,
            }
        })
    }

    /**
     * Send g-code, returning the dispatch promise so a caller can show
     * progress for its own action. Callers that do not care may ignore it.
     */
    saGcode(script: string): Promise<unknown> {
        return this.$store.dispatch('printer/sendGcode', script)
    }

    /**
     * Border / outline color for a swatch, chosen so dark filaments don't
     * blend into Mainsail's dark panel background. Uses YIQ perceived
     * luminance of the primary hex — under threshold returns a translucent
     * white outline; otherwise the standard translucent black.
     */
    saSwatchBorderColor(idx: number): string {
        const primary = this.saColorParts(idx)[0] ?? ''
        return saBorderForHex(primary)
    }
}

/**
 * Standalone helper so catalog dropdown swatches and other hex-only
 * consumers can pick the same outline color without an idx.
 */
export function saBorderForHex(hex: string): string {
    const clean = (hex || '').replace(/^#/, '').padEnd(6, '0').substring(0, 6)
    if (!/^[0-9a-fA-F]{6}$/.test(clean)) return 'rgba(0,0,0,0.35)'
    const r = parseInt(clean.slice(0, 2), 16)
    const g = parseInt(clean.slice(2, 4), 16)
    const b = parseInt(clean.slice(4, 6), 16)
    // YIQ — Rec. 601 perceived luminance, threshold ~0.5 (128/255).
    const yiq = (r * 299 + g * 587 + b * 114) / 1000
    return yiq < 110 ? 'rgba(255,255,255,0.65)' : 'rgba(0,0,0,0.35)'
}
