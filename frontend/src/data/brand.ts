/**
 * The product's name, spelled here and nowhere else.
 *
 * Seeded by the orchestrator on 2026-09-06 (docs/ux-shell/DEFINITION-OF-DONE.md
 * D1): the owner's PRODUCT_NAME slot was blank, so the brand is built as
 * "Crew Studio". Changing the owner's mind costs one edit to this constant —
 * the wordmark, `document.title`, the sign-in wall, `index.html` (through
 * `tests/brand.spec.ts`, which asserts the two agree) and every heading read
 * it from here. A second spelling anywhere in `frontend/src` is a defect.
 */
export const PRODUCT_NAME = 'Crew Studio'

/** The `<title>` of a canvas route: the workflow, then the product. */
export function pageTitle(workflowName?: string | null): string {
  const name = workflowName?.trim()
  return name ? `${name} · ${PRODUCT_NAME}` : PRODUCT_NAME
}
