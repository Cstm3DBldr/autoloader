import { hostModule } from './host-runtime.js'
const mod = hostModule('vue-class-component')
export default mod.default ?? mod
export const createDecorator = mod.createDecorator
export const mixins = mod.mixins
