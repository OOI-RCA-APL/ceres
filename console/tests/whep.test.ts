import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  fallbackWhy,
  openWhep,
  permanent,
  useVideoTransports,
  WhepRefusal,
  WhepSilence,
} from '@/whep'

const route = 'http://engine/api/components/@device/procedures/video/whep'

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

/** The engine answering every offer with `status` and refusal `reason`, recording each request. */
function engine(status = 201, reason = 'codec') {
  const fetch = vi.fn(async (_url: string, init: RequestInit) => {
    if (init.method === 'DELETE') {
      return new Response(null, { status: 200 })
    }
    if (status !== 201) {
      return Response.json({ status, reason }, { status })
    }

    return new Response('answer', { status, headers: { location: `${route}/abcd` } })
  })
  vi.stubGlobal('fetch', fetch)
  return fetch
}

function open() {
  return openWhep(route, { signal: new AbortController().signal, onLost: () => {} })
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
    expect(fetch).toHaveBeenCalledWith(route, expect.objectContaining({ body: 'offer' }))
  })

  it('ends the session on the server when closed', async () => {
    const peers = peer()
    const fetch = engine()

    const session = await open()
    session.close()

    expect(peers[0]?.closed).toBe(true)
    expect(fetch).toHaveBeenLastCalledWith(
      `${route}/abcd`,
      expect.objectContaining({ method: 'DELETE' }),
    )
  })

  it('rejects an offer the engine refuses with its status and reason', async () => {
    const peers = peer()
    engine(409, 'codec')

    await expect(open()).rejects.toEqual(new WhepRefusal(409, 'codec'))
    await expect(open()).rejects.toMatchObject({ status: 409, reason: 'codec' })
    expect(peers[0]?.closed).toBe(true)
  })

  it('rejects a connection that does not come up in time', async () => {
    peer({ state: 'connecting' })
    const fetch = engine()

    const opening = expect(open()).rejects.toThrow(WhepSilence)
    await vi.advanceTimersByTimeAsync(5000)
    await opening
    expect(fetch).toHaveBeenLastCalledWith(
      `${route}/abcd`,
      expect.objectContaining({ method: 'DELETE' }),
    )
  })

  it('rejects a connection that brings no picture', async () => {
    peer({ frames: 0 })
    engine()

    const opening = expect(open()).rejects.toThrow(WhepSilence)
    await vi.advanceTimersByTimeAsync(5000)
    await opening
  })
})

describe('permanent', () => {
  it('holds for silence and for refusals every try meets', () => {
    expect(permanent(new WhepSilence())).toBe(true)
    for (const reason of ['disabled', 'not-live', 'codec', 'offer']) {
      expect(permanent(new WhepRefusal(409, reason))).toBe(true)
    }
    expect(permanent(new WhepRefusal(415, null))).toBe(true)
  })

  it('passes for refusals a later try may not meet', () => {
    for (const reason of ['full', 'source', 'timeout']) {
      expect(permanent(new WhepRefusal(503, reason))).toBe(false)
    }
    expect(permanent(new WhepRefusal(500, null))).toBe(false)
    expect(permanent(new TypeError('Failed to fetch'))).toBe(false)
  })
})

describe('useVideoTransports', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('remembers the transport each route settled on, and why', () => {
    const transports = useVideoTransports()
    const choice = { transport: 'http', why: 'The network blocks WebRTC.' } as const
    transports.remember(route, choice)

    expect(transports.verdict(route)).toEqual(choice)
    expect(transports.verdict(`${route}x`)).toBeNull()
  })

  it('tells what each widget plays over until it stops', () => {
    const transports = useVideoTransports()
    transports.show('video', { transport: 'webrtc' })
    expect(transports.playing('video')?.transport).toBe('webrtc')

    transports.show('video', null)
    expect(transports.playing('video')).toBeNull()
  })
})

describe('fallbackWhy', () => {
  it('names why each first try fell to HTTP', () => {
    expect(fallbackWhy(new WhepSilence('silent'))).toBe('The network blocks WebRTC.')
    expect(fallbackWhy(new WhepRefusal(409, 'reordered'))).toBe(
      'The video has B-frames, which WebRTC cannot play smoothly.',
    )
    expect(fallbackWhy(new WhepRefusal(415, null))).toBe(
      'WebRTC could not be set up with this browser.',
    )
    expect(fallbackWhy(new WhepRefusal(500, 'unheard-of'))).toBe('The server refused WebRTC.')
    expect(fallbackWhy(new TypeError('Failed to fetch'))).toBe('The WebRTC request failed.')
  })
})
