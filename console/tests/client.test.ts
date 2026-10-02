import { afterEach, describe, expect, it, vi } from 'vitest'

import { isTimeoutError, request, timeoutSignal } from '@/api/client'
import { Failure } from '@/errors'

/** A `fetch` that never answers, which is what a request the browser has queued behind every
connection it allows looks like, until its signal aborts it. */
function hangingFetch() {
  return vi.fn(
    (_url: unknown, init?: RequestInit) =>
      new Promise<Response>((_resolve, reject) => {
        init?.signal?.addEventListener('abort', () => reject(init.signal?.reason))
      }),
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('timeoutSignal', () => {
  it('passes the caller signal through when no timeout is set', () => {
    const controller = new AbortController()

    expect(timeoutSignal(undefined, controller.signal)).toBe(controller.signal)
    expect(timeoutSignal(undefined, null)).toBeUndefined()
  })

  it('aborts with a timeout error once the timeout passes', async () => {
    const signal = timeoutSignal(10, null)

    await vi.waitFor(() => expect(signal?.aborted).toBe(true))
    expect(isTimeoutError(signal?.reason)).toBe(true)
  })

  it('aborts when the caller signal aborts first', () => {
    const controller = new AbortController()
    const signal = timeoutSignal(60_000, controller.signal)

    controller.abort()

    expect(signal?.aborted).toBe(true)
    expect(isTimeoutError(signal?.reason)).toBe(false)
  })
})

describe('request', () => {
  it('fails a request the server never answers with request-timeout-error', async () => {
    vi.stubGlobal('fetch', hangingFetch())
    vi.spyOn(console, 'error').mockImplementation(() => {})

    const promise = request('PATCH', '/api/workspaces/abc', { data: {}, timeout: 10 })

    await expect(promise).rejects.toBeInstanceOf(Failure)
    await expect(promise).rejects.toMatchObject({
      error: { type: 'request-timeout-error', timeout: 10 },
    })
  })

  it('hangs without a timeout', async () => {
    const fetch = hangingFetch()
    vi.stubGlobal('fetch', fetch)

    const settled = vi.fn()
    void request('PATCH', '/api/workspaces/abc', { data: {} }).then(settled, settled)
    await new Promise((resolve) => setTimeout(resolve, 30))

    expect(fetch).toHaveBeenCalledOnce()
    expect(settled).not.toHaveBeenCalled()
  })
})
