import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, nextTick, ref } from 'vue'
import * as z from 'zod'

import { isTimeoutError, request, timeoutSignal, useClient } from '@/api/client'
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

/** A socket the test drives by hand, standing in for the browser's. */
class FakeSocket extends EventTarget {
  static opened: FakeSocket[] = []
  closed = false

  constructor(readonly url: string) {
    super()
    FakeSocket.opened.push(this)
  }

  close() {
    this.closed = true
  }

  receive(data: unknown) {
    this.dispatchEvent(new MessageEvent('message', { data: JSON.stringify(data) }))
  }

  end() {
    this.dispatchEvent(new Event('close'))
  }
}

describe('useStream', () => {
  /** Streams `query` into the returned list until the test changes it. */
  function streamed() {
    FakeSocket.opened = []
    vi.stubGlobal('WebSocket', FakeSocket)
    setActivePinia(createPinia())
    const query = ref({ name: 'a' })
    const received: string[] = []
    mount(
      defineComponent({
        setup() {
          useClient().useStream({
            stream: () => ({ id: 'one', path: '/api/a', query: query.value }),
            parse: z.string(),
            onReceive: (message: string) => received.push(message),
          })
          return () => null
        },
      }),
    )
    return { query, received }
  }

  it('drops what a replaced socket still delivers', async () => {
    const { query, received } = streamed()
    query.value = { name: 'b' }
    await nextTick()
    const [replaced, current] = FakeSocket.opened

    replaced!.receive('old')
    current!.receive('new')

    expect(received).toEqual(['new'])
  })

  it('keeps the replacing socket open when the replaced one closes', async () => {
    const { query, received } = streamed()
    query.value = { name: 'b' }
    await nextTick()
    const [replaced, current] = FakeSocket.opened

    replaced!.end()
    current!.receive('new')

    expect(current!.closed).toBe(false)
    expect(received).toEqual(['new'])
  })
})
