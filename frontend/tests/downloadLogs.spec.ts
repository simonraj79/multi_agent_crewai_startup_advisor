import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { StudioApi } from '../src/services/studioApi'

/**
 * `downloadLogs` was left untested on the grounds that jsdom has no
 * `URL.createObjectURL`. That is no longer true - jsdom 30 implements the blob
 * URL store, mints real `blob:` URLs and revokes them - so everything this
 * function does with an object URL is observable for real.
 *
 * The single thing jsdom genuinely cannot do is *start a download*: an anchor
 * click tries to navigate and logs "Not implemented: navigation to another
 * Document". So `click` is the only thing replaced here, and it is replaced with
 * a recorder rather than a no-op: it captures what the anchor looked like at the
 * instant the browser would have taken the file, which is exactly the state
 * worth protecting.
 */
describe('StudioApi.downloadLogs', () => {
  let api: StudioApi
  let fetchMock: ReturnType<typeof vi.fn>
  let originalFetch: typeof globalThis.fetch
  let createSpy: ReturnType<typeof vi.spyOn>
  let revokeSpy: ReturnType<typeof vi.spyOn>
  let clickSpy: ReturnType<typeof vi.spyOn>

  interface ClickSnapshot {
    href: string
    download: string
    attached: boolean
    revokesBefore: number
  }
  let clicks: ClickSnapshot[]

  const mintedUrl = (index = 0) => createSpy.mock.results[index]?.value as string
  const blobResponse = (blob: Blob) => ({ ok: true, status: 200, blob: async () => blob })
  const strayAnchors = () => document.querySelectorAll('a[download]').length

  beforeEach(() => {
    api = new StudioApi()
    api.mode = 'live'
    clicks = []
    originalFetch = globalThis.fetch
    fetchMock = vi.fn()
    globalThis.fetch = fetchMock as unknown as typeof globalThis.fetch

    // Real jsdom implementations underneath: the spies observe, they do not stub.
    createSpy = vi.spyOn(URL, 'createObjectURL')
    revokeSpy = vi.spyOn(URL, 'revokeObjectURL')
    clickSpy = vi
      .spyOn(HTMLElement.prototype, 'click')
      .mockImplementation(function recordClick(this: HTMLAnchorElement) {
        clicks.push({
          href: this.href,
          download: this.download,
          attached: this.isConnected,
          revokesBefore: revokeSpy.mock.calls.length,
        })
      })
  })

  afterEach(() => {
    globalThis.fetch = originalFetch
    // `restoreMocks` puts the real click and the real URL statics back.
  })

  it('asks the service for the run log and hands the response to the browser', async () => {
    const body = new Blob(['{"type":"frame"}\n'], { type: 'application/x-ndjson' })
    fetchMock.mockResolvedValueOnce(blobResponse(body))

    await api.downloadLogs('run-1234abcd-ef')

    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(String(fetchMock.mock.calls[0][0])).toBe('/api/runs/run-1234abcd-ef/logs?format=ndjson')
    // The blob offered to the browser is the response body, not a copy of it.
    expect(createSpy).toHaveBeenCalledTimes(1)
    expect(createSpy.mock.calls[0][0]).toBe(body)

    expect(clicks).toHaveLength(1)
    expect(clicks[0].href).toBe(mintedUrl())
    expect(clicks[0].download).toBe('validator-run-1234.ndjson')
  })

  it('asks for the ZIP the endpoint also serves, and names the file for it', async () => {
    fetchMock.mockResolvedValueOnce(blobResponse(new Blob([new Uint8Array([80, 75, 3, 4])], { type: 'application/zip' })))

    await api.downloadLogs('run-1234abcd-ef', 'zip')

    expect(String(fetchMock.mock.calls[0][0])).toBe('/api/runs/run-1234abcd-ef/logs?format=zip')
    expect(clicks[0].download).toBe('validator-run-1234.zip')
  })

  it('percent-encodes the run id it puts in the path', async () => {
    fetchMock.mockResolvedValueOnce(blobResponse(new Blob([''])))
    await api.downloadLogs('run/../secrets')
    expect(String(fetchMock.mock.calls[0][0])).toBe('/api/runs/run%2F..%2Fsecrets/logs?format=ndjson')
  })

  /**
   * The object URL lifecycle. An entry in the blob URL store is never reclaimed
   * on its own, so every URL minted has to be released or the blob stays
   * resident for the life of the document.
   */
  it('keeps the object URL alive for the click and releases it straight after', async () => {
    fetchMock.mockResolvedValueOnce(blobResponse(new Blob(['x'])))

    await api.downloadLogs('run-1')

    // Still valid when the browser would have read it...
    expect(clicks[0].revokesBefore).toBe(0)
    // ...and released once, for the URL that was actually minted.
    expect(revokeSpy).toHaveBeenCalledTimes(1)
    expect(revokeSpy).toHaveBeenCalledWith(mintedUrl())
    expect(createSpy).toHaveBeenCalledTimes(1)
  })

  it('attaches the anchor before clicking and leaves no anchor behind', async () => {
    fetchMock.mockResolvedValueOnce(blobResponse(new Blob(['x'])))
    expect(strayAnchors()).toBe(0)

    await api.downloadLogs('run-1')

    expect(clicks[0].attached).toBe(true)
    expect(strayAnchors()).toBe(0)
  })

  /**
   * The regression this guards: the revoke used to sit on the happy path after
   * `click()`. A click that throws - a blocked download, a document being torn
   * down - skipped it, and the blob leaked for the life of the tab.
   */
  it('releases the object URL even when the click throws', async () => {
    fetchMock.mockResolvedValueOnce(blobResponse(new Blob(['x'])))
    clickSpy.mockImplementation(() => {
      throw new Error('Download blocked by the browser.')
    })

    await expect(api.downloadLogs('run-1')).rejects.toThrow('Download blocked by the browser.')

    expect(createSpy).toHaveBeenCalledTimes(1)
    expect(revokeSpy).toHaveBeenCalledWith(mintedUrl())
    expect(strayAnchors()).toBe(0)
  })

  it('reports a failed request and mints no object URL to leak', async () => {
    fetchMock.mockResolvedValueOnce({ ok: false, status: 503, blob: async () => new Blob([]) })

    await expect(api.downloadLogs('run-1')).rejects.toThrow('Log download failed (503)')

    expect(createSpy).not.toHaveBeenCalled()
    expect(revokeSpy).not.toHaveBeenCalled()
    expect(clicks).toEqual([])
  })

  it('propagates a network failure without touching the DOM', async () => {
    fetchMock.mockRejectedValueOnce(new Error('connection refused'))

    await expect(api.downloadLogs('run-1')).rejects.toThrow('connection refused')

    expect(createSpy).not.toHaveBeenCalled()
    expect(strayAnchors()).toBe(0)
  })

  describe('in mock mode', () => {
    beforeEach(() => {
      api.mode = 'mock'
      // `startRun` re-probes when the transport is mocked; keep it offline.
      fetchMock.mockRejectedValue(new Error('connection refused'))
      vi.useFakeTimers()
    })

    afterEach(() => {
      vi.useRealTimers()
    })

    it('serves the frames it has streamed, as NDJSON, without a request', async () => {
      const started = await api.startRun('session-1', 'An idea worth validating')
      api.subscribe(started.run_id, 'session-1', {
        onFrame: () => undefined,
        onStatus: () => undefined,
        getAfter: () => 0,
      })
      vi.advanceTimersByTime(4_000)
      const networkCallsBefore = fetchMock.mock.calls.length

      await api.downloadLogs(started.run_id)

      expect(fetchMock.mock.calls).toHaveLength(networkCallsBefore)
      const blob = createSpy.mock.calls[0][0] as Blob
      expect(blob.type).toBe('application/x-ndjson')

      const lines = (await blob.text()).split('\n')
      expect(lines.length).toBeGreaterThan(1)
      expect(JSON.parse(lines[0])).toMatchObject({ type: 'frame', data: { seq: 1 } })
      // The filename must SAY it is a demonstration. It was
      // `validator-${id8}.ndjson` for both transports until 2026-09-01, so the
      // export a scripted run hands you was indistinguishable by name from a
      // real archive - and its contents are plausible NDJSON. An operator
      // downloaded one, could not tell what it was, and concluded the backend
      // had failed to write a report.
      expect(clicks[0].download).toBe(
        `validator-DEMO-not-a-real-run-${started.run_id.slice(0, 8)}.ndjson`,
      )
      expect(clicks[0].download).toContain('DEMO')
    })

    it('will not label its in-memory NDJSON as a ZIP it never built', async () => {
      const started = await api.startRun('session-1', 'An idea worth validating')

      await api.downloadLogs(started.run_id, 'zip')

      expect(clicks[0].download).toMatch(/\.ndjson$/)
      expect((createSpy.mock.calls[0][0] as Blob).type).toBe('application/x-ndjson')
    })
  })
})
