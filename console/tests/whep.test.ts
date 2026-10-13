import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { openWhep, useVideoTransports } from '@/whep'

const ROUTE = 'http://engine/api/components/@camera/procedures/video/whep'

/** A peer connection whose remote answer brings it up as `state`, decoding `frames` frames. */
function peer({ state = 'connected', frames = 1 } = {}) {
  const peers: FakePeer[] = []

  class FakePeer extends EventTarget {
    connectionState = 'new'
    localDescription: { sdp: string } | null = null
    closed = false

    constructor() {
      super()
      peers.push(this)
    }

    addTransceiver() {}

    async createOffer() {
      return { type: 'offer', sdp: 'offer' }
    }

    async setLocalDescription(description: { sdp: string }) {
      this.localDescription = description
    }

    async setRemoteDescription() {
      const track = new Event('track') as Event & { streams: string[] }
      track.streams = ['stream']
      this.dispatchEvent(track)
      this.connectionState = state
      this.dispatchEvent(new Event('connectionstatechange'))
    }

    async getStats() {
      return new Map([['a', { type: 'inbound-rtp', kind: 'video', framesDecoded: frames }]])
    }

    close() {
      this.closed = true
    }
  }

  vi.stubGlobal('RTCPeerConnection', FakePeer)
  return peers
}

/** The engine answering every offer with `status`, recording each request. */
function engine(status = 201) {
  const fetch = vi.fn(async (_url: string, init: RequestInit) => {
    if (init.method === 'DELETE') {
      return new Response(null, { status: 200 })
    }

    return new Response('answer', { status, headers: { location: `${ROUTE}/abcd` } })
  })
  vi.stubGlobal('fetch', fetch)
  return fetch
}

function open() {
  return openWhep(ROUTE, { signal: new AbortController().signal, onLost: () => {} })
}

describe('openWhep', () => {
  beforeEach(() => vi.useFakeTimers())

  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it('posts the offer and resolves with the stream once a frame is decoded', async () => {
    peer()
    const fetch = engine()

    const session = await open()

    expect(session.stream).toBe('stream')
    expect(fetch).toHaveBeenCalledWith(ROUTE, expect.objectContaining({ body: 'offer' }))
  })

  it('ends the session on the server when closed', async () => {
    const peers = peer()
    const fetch = engine()

    const session = await open()
    session.close()

    expect(peers[0]?.closed).toBe(true)
    expect(fetch).toHaveBeenLastCalledWith(
      `${ROUTE}/abcd`,
      expect.objectContaining({ method: 'DELETE' }),
    )
  })

  it('rejects an offer the engine refuses', async () => {
    const peers = peer()
    engine(409)

    await expect(open()).rejects.toThrow('409')
    expect(peers[0]?.closed).toBe(true)
  })

  it('rejects a connection that does not come up in time', async () => {
    peer({ state: 'connecting' })
    const fetch = engine()

    const opening = expect(open()).rejects.toThrow('did not come up')
    await vi.advanceTimersByTimeAsync(5000)
    await opening
    expect(fetch).toHaveBeenLastCalledWith(
      `${ROUTE}/abcd`,
      expect.objectContaining({ method: 'DELETE' }),
    )
  })

  it('rejects a connection that brings no picture', async () => {
    peer({ frames: 0 })
    engine()

    const opening = expect(open()).rejects.toThrow('no picture')
    await vi.advanceTimersByTimeAsync(5000)
    await opening
  })
})

describe('useVideoTransports', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('remembers the transport each route settled on', () => {
    const transports = useVideoTransports()
    transports.remember(ROUTE, 'http')

    expect(transports.verdict(ROUTE)).toBe('http')
    expect(transports.verdict(`${ROUTE}x`)).toBeNull()
  })
})
