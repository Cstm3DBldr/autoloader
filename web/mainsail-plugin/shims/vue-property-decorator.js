import { hostModule } from './host-runtime.js'
const mod = hostModule('vue-property-decorator')
export default mod.default ?? mod
export const Component = mod.Component
export const Prop = mod.Prop
export const Watch = mod.Watch
export const Ref = mod.Ref
export const Emit = mod.Emit
export const Inject = mod.Inject
export const Provide = mod.Provide
export const Model = mod.Model
export const Mixins = mod.Mixins
export const Vue = mod.Vue
