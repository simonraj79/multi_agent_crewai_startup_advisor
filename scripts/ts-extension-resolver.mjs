/**
 * Let plain `node` import this app's TypeScript modules by their own specifiers.
 *
 * Node 24 strips TypeScript types from a `.ts` file natively, so the only thing
 * standing between `node` and `frontend/src/data/builderTemplates.ts` is that
 * the app writes `from '../types/builder'` with no extension - which Vite
 * resolves and Node does not. This adds `.ts` on a relative specifier that
 * failed to resolve, and nothing else: no transform, no cache, no config, and
 * no package to install.
 *
 * Used by `scripts/dump-templates.mjs` only. It is deliberately not a general
 * loader - a specifier that resolves is never touched, so this can never change
 * what a working import means.
 */

import { register } from 'node:module'

export async function resolve(specifier, context, next) {
  try {
    return await next(specifier, context)
  } catch (error) {
    if (specifier.startsWith('.')) return await next(`${specifier}.ts`, context)
    throw error
  }
}

// Self-registering, so `node --import ./scripts/ts-extension-resolver.mjs` is
// the whole invocation. `register` re-imports this same file inside the loader
// thread, where the export above is what gets used.
if (!process.env.BUILDER_TS_RESOLVER_REGISTERED) {
  process.env.BUILDER_TS_RESOLVER_REGISTERED = '1'
  register(import.meta.url)
}
