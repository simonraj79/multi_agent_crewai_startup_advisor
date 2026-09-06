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

/**
 * What the product IS, in one line, spelled here and nowhere else.
 *
 * It existed already and only signed-OUT people could read it: `SignInPanel`
 * rendered it as the wall's lede and the signed-in home carried no sentence
 * under the brand at all, so the one screen that answers "what can I do here"
 * was the one screen you see before you have an account (AUDIT-R2 H1, and the
 * reason its cold read scored Q1 a weak pass and Q2 a fail). ROUND-2 §5 ruling
 * 2 puts it on the home verbatim, which makes it two surfaces reading one
 * string rather than two strings that agree today.
 *
 * `flow` here is CrewAI's own primitive and is deliberately NOT the X1 rename:
 * a workflow is what you draw, a CrewAI flow is what it becomes.
 */
export const PRODUCT_SENTENCE =
  'Draw a workflow on a canvas in Build, then Run it as a real CrewAI flow ' +
  'and watch every agent work — live.'

/** The `<title>` of a canvas route: the workflow, then the product. */
export function pageTitle(workflowName?: string | null): string {
  const name = workflowName?.trim()
  return name ? `${name} · ${PRODUCT_NAME}` : PRODUCT_NAME
}
