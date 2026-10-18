// Resolve the three host-provided modules to local stubs.
const map = {
  '@hermes/plugin-sdk': new URL('./stubs/sdk.mjs', import.meta.url).href,
  'react/jsx-runtime': new URL('./stubs/jsx-runtime.mjs', import.meta.url).href,
  react: new URL('./stubs/react.mjs', import.meta.url).href
}
export async function resolve (specifier, context, next) {
  if (map[specifier]) return { url: map[specifier], shortCircuit: true }
  return next(specifier, context)
}
