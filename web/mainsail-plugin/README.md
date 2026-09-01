# Autoloader panel — Mainsail plugin

The autoloader dashboard panel, packaged as a **runtime-loaded Mainsail
plugin** instead of a patch against Mainsail's source tree.

Previously this panel lived at
`src/components/panels/autoloader/SAStatusPanel.vue` inside a fork of
Mainsail, which meant every Mainsail release had to be re-forked, rebuilt
and re-deployed to keep the panel. As a plugin it is a single `.mjs` file
that stock Mainsail loads at runtime, so Mainsail can be updated normally.

Requires Mainsail with custom-panel support (the `feat/custom-panel-plugins`
work). It will not load on a Mainsail build without it.

## Build

```bash
npm install && npm run build
```

Produces one self-contained file, `dist/autoloader-panel-plugin.js`
(~90 kB, ~21 kB gzipped). Styles are folded into that file, so there is no
second asset to deploy.

## Install

Serve `dist/autoloader-panel-plugin.js` from anywhere the browser can
reach it, then register it. Prefer the Moonraker database over
`config.json`: Moonraker's update manager wipes Mainsail's web root on a
client update, which takes `config.json` with it unless it is listed under
`persistent_files`.

```json
{
    "id": "autoloader",
    "title": "Autoloader",
    "icon": "<svg path string>",
    "entryUrl": "/plugins/autoloader-panel-plugin.js",
    "collapsible": true,
    "requiresPrinterObject": "autoloader"
}
```

`title` and `icon` are rendered by Mainsail's own panel chrome, which is
why the component itself no longer draws a `<panel>` wrapper.

`requiresPrinterObject` hides the panel on a printer that does not report an
`[autoloader]` Klipper object. Without it the panel still draws its frame
there and shows an empty card, because the panel hides its own body but the
host draws the surrounding chrome. Its dashboard position is remembered
either way, so the panel returns where you put it if the object comes back.

Register it in the **Moonraker database** rather than `config.json` where you
can. `config.json` lives in Mainsail's web root, which the update manager
wipes on a Mainsail update, and it is a cacheable static file -- a browser
holding an old copy will not show a newly added panel and gives no clue why:

```bash
curl -X POST 'http://your-printer:7125/server/database/item'     -H 'Content-Type: application/json'     -d '{"namespace":"mainsail","key":"view.customPanels","value":[ ... ]}'
```

Note the plugin file itself is not covered by that durability. If it lives in
`~/mainsail/plugins/` a Mainsail update deletes it, leaving a registration
pointing at a missing file -- the panel then shows a load error. Serve it
from outside the web root, or add it to Moonraker's `persistent_files`.


## How it talks to the host

Mainsail publishes its Vue instance and decorator packages on
`window.__mainsail_plugin_runtime__`. The `shims/` directory maps `vue`,
`vue-class-component` and `vue-property-decorator` onto that runtime via
Vite aliases, so:

- the plugin ships **no** copy of Vue, and shares the host's reactivity;
- panel source keeps ordinary `import` statements and `@Component` /
  `@Prop` decorators, matching Mainsail's own house style rather than
  being forced into the options API by how it happens to be loaded.

Because the host's Vue constructor is shared, and Mainsail installs the
full Vuetify build (`Vue.use(Vuetify)` registers every component
globally), all `v-*` components resolve inside the plugin with no
registration. `$store`, `$socket`, `$i18n` and `$vuetify` resolve too.
`<panel>` is the one exception — it is imported per-file in Mainsail, and
the host's `CustomPanel` already supplies it.

## Differences from the in-tree version

The port is close to a straight copy. Only these changed:

| In-tree | Plugin | Why |
|---|---|---|
| `<panel>` wrapper in the template | dropped | Host `CustomPanel` renders the chrome; `title`/`icon` moved to panel config |
| `BaseMixin` | local `apiUrl` getter | `BaseMixin` lives in Mainsail's source tree; the panel used only `apiUrl` |
| `axios` | `src/lib/http.ts` | Three plain GETs did not justify bundling ~35 kB; the shim matches axios's `get`/`res.data`/reject-on-non-2xx surface |
| translations in Mainsail's `locales/*.json` | `src/locales/index.json` | The host carries no strings for a panel it does not know about; merged via `$i18n.mergeLocaleMessage` in `created()` before first render |

The ~2600 lines of template, state and logic are otherwise unchanged, as
are all 135 `$t` call sites and the Vuetify markup.

## Two things that will stop it loading on a printer

**Serve it as `.js`, not `.mjs`.** Plugins are fetched with a dynamic
`import()`, and browsers refuse to execute a module served with a
non-JavaScript MIME type. nginx as shipped on a standard Klipper host has no
mapping for `.mjs` and serves it as `application/octet-stream`, so the plugin
never loads — and the console says only *"Failed to fetch dynamically
imported module"*, which looks like a missing file rather than a MIME
problem. Check with:

```bash
curl -sI http://your-printer/plugins/autoloader-panel-plugin.js | grep -i content-type
```

**Do not set `hostname`/`port` in `config.json`.** A stock install leaves
them null so the browser talks to its own origin and nginx reverse-proxies
to Moonraker. Pinning them to `printer:7125` makes the browser cross-origin,
and Moonraker's `cors_domains` usually does not allow a bare IP — Mainsail
loads and then reports it cannot connect to Moonraker.
