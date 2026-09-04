/**
 * Hands a blob to the browser's download machinery.
 *
 * Moved here from `services/studioApi.ts` unchanged, because the builder's
 * export needs the same three steps and `builderApi.ts` is not allowed to
 * import `studioApi.ts` to get them - the two clients share `httpCore` and
 * nothing else, by that file's own declaration. A second copy in the builder
 * would have been a second place for the revoke to go missing, and
 * `tests/downloadLogs.spec.ts` pins only this one.
 *
 * An object URL is a document-lifetime entry in the blob URL store: nothing
 * reclaims it, so every one that is minted has to be revoked or the blob stays
 * resident until the tab closes. The revoke is in `finally` because `click()`
 * can throw - a blocked popup, a detached document during teardown - and a
 * throw on the happy path was the one way this could leak.
 *
 * The revoke is synchronous, immediately after the click. Chromium and Firefox
 * both resolve the blob URL while the click is still being dispatched, so the
 * download is already underway by then. WebKit has historically been less
 * forgiving; if a Safari download ever comes back empty, this is the line, and
 * the fix is to defer the revoke rather than to drop it.
 */
export function saveBlob(blob: Blob, filename: string): void {
  const href = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = href
  anchor.download = filename
  anchor.rel = 'noopener'
  anchor.style.display = 'none'
  document.body.append(anchor)
  try {
    anchor.click()
  } finally {
    anchor.remove()
    URL.revokeObjectURL(href)
  }
}
