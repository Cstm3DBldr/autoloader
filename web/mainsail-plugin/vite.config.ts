import { defineConfig } from 'vite'
import vue from '@pedrolamas/plugin-vue2'
import { resolve } from 'path'
import type { Plugin } from 'vite'

const NEWLINE = String.fromCharCode(10)

/**
 * Folds the emitted stylesheet into the JS bundle.
 *
 * A panel plugin is delivered as a single ES module that Mainsail pulls in
 * with a dynamic import. Nothing on the host side reads the plugin's asset
 * manifest, so a sibling .css file would simply never be requested and the
 * panel would render unstyled. Injecting a <style> on module evaluation keeps
 * the plugin to one file with no install step for its styles.
 */
const inlineCss = (styleId: string): Plugin => ({
    name: 'mainsail-plugin-inline-css',
    apply: 'build',
    enforce: 'post',
    generateBundle(_options, bundle) {
        const cssFiles = Object.keys(bundle).filter((name) => name.endsWith('.css'))
        if (cssFiles.length === 0) return

        const css = cssFiles
            .map((name) => {
                const asset = bundle[name]
                delete bundle[name]

                return asset.type === 'asset' ? String(asset.source) : ''
            })
            .join(NEWLINE)

        const entry = Object.values(bundle).find((chunk) => chunk.type === 'chunk' && chunk.isEntry)
        if (!entry || entry.type !== 'chunk') return

        // A stable id keeps a re-import, or a second instance of the panel,
        // from stacking duplicate <style> elements in the document head.
        entry.code =
            `(function(){var id=${JSON.stringify(styleId)};` +
            `if(typeof document==='undefined'||document.getElementById(id))return;` +
            `var s=document.createElement('style');s.id=id;` +
            `s.textContent=${JSON.stringify(css)};` +
            `document.head.appendChild(s);})();` +
            NEWLINE +
            entry.code
    },
})

// Build config for a Mainsail panel plugin.
//
// The output is a single ES module loaded at runtime, so it cannot resolve
// bare specifiers the way a bundled app can. Rather than shipping its own
// copy of Vue -- which would bloat the plugin and break reactivity across the
// host boundary -- 'vue' and the two decorator packages are aliased to shims
// that read them back out of the runtime Mainsail publishes on window.
//
// The practical effect is that plugin source is written exactly like any
// component in Mainsail itself, with @Component and @Prop, instead of being
// pushed into the options API by how it happens to be loaded.
const shim = (name: string) => resolve(import.meta.dirname, 'shims', name)

export default defineConfig({
    plugins: [vue(), inlineCss('mainsail-plugin-style-autoloader')],
    resolve: {
        alias: {
            vue: shim('vue.js'),
            'vue-class-component': shim('vue-class-component.js'),
            'vue-property-decorator': shim('vue-property-decorator.js'),
        },
    },
    define: {
        'process.env.NODE_ENV': JSON.stringify('production'),
    },
    esbuild: {
        // Class components need legacy decorators; without this they are
        // emitted untranspiled and the browser cannot parse the module.
        tsconfigRaw: {
            compilerOptions: {
                experimentalDecorators: true,
                target: 'es2020',
                useDefineForClassFields: false,
            },
        },
    },
    build: {
        outDir: resolve(import.meta.dirname, 'dist'),
        emptyOutDir: true,
        lib: {
            entry: 'src/main.ts',
            name: 'AutoloaderPanelPlugin',
            formats: ['es'],
            fileName: () => 'autoloader-panel-plugin.mjs',
        },
    },
})
