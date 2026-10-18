// Stand-in for @hermes/plugin-sdk: components are tags, hooks are inert.
const tag = name => Object.assign(props => ({ type: name, props }), { displayName: name })
export const Badge = tag('Badge')
export const Button = tag('Button')
export const EmptyState = tag('EmptyState')
export const ErrorState = tag('ErrorState')
export const GlyphSpinner = tag('GlyphSpinner')
export const Input = tag('Input')
export const ScrollArea = tag('ScrollArea')
export const PALETTE_AREA = 'palette'
export const ROUTES_AREA = 'routes'
export const SIDEBAR_NAV_AREA = 'sidebar-nav'
export const host = { navigate: () => {} }
export const queryClient = { invalidateQueries: () => {} }
export const useQuery = () => ({ data: undefined, isLoading: false, isError: false })
