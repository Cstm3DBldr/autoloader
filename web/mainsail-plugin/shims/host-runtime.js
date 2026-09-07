// Resolves the packages Mainsail shares with plugins at runtime.
//
// The plugin's vite config aliases 'vue', 'vue-class-component' and
// 'vue-property-decorator' to the shims beside this file, so plugin source
// keeps its ordinary imports while the built module reads them back out of
// the host instead of bundling its own copies.
const runtime = window.__mainsail_plugin_runtime__

if (!runtime) {
    throw new Error(
        'Mainsail plugin runtime not found. This bundle must be loaded by ' +
            'Mainsail as a custom panel, not opened on its own.'
    )
}

export const hostRuntime = runtime

export function hostModule(name) {
    const mod = runtime.modules[name]
    if (!mod) {
        throw new Error(`Mainsail does not share the module "${name}" with plugins.`)
    }
    return mod
}
