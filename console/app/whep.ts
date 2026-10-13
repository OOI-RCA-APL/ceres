import { defineStore } from 'pinia'

/** How a video widget receives its picture, named on the widget so a fallback is visible. */
export type VideoTransport = 'webrtc' | 'http'

// A camera that takes longer than these to show its picture over WebRTC plays over HTTP instead,
// since a network that drops UDP fails WebRTC by silence rather than by an error.
const OFFER_TIMEOUT_MS = 10_000
const CONNECT_TIMEOUT_MS = 5_000
const FRAME_TIMEOUT_MS = 5_000
const FRAME_POLL_MS = 250

/** A procedure's camera playing over WebRTC. */
export interface WhepSession {
  /** The camera's picture, for a video element's `srcObject`. */
  readonly stream: MediaStream
  /** End the session, here and on the server. */
  close(): void
}

/** Play the camera behind a WHEP route at `url`, resolving once its first frame is decoded.

Rejects when the server refuses the offer, when the connection does not come up, or when no frame
arrives in time, and the caller then plays the procedure over HTTP. `onLost` reports a session
that dropped after it played, which the caller retries over WebRTC since the network carried it
before. Aborting `signal` ends the session wherever it got to.
*/
export async function openWhep(
  url: string,
  { signal, onLost }: { signal: AbortSignal; onLost: (reason: string) => void },
): Promise<WhepSession> {
  const connection = new RTCPeerConnection()
  let location: string | null = null
  const close = () => {
    connection.close()
    if (location != null) {
      // Ends the server's session at once rather than when its ICE times out.
      void fetch(location, { method: 'DELETE', keepalive: true }).catch(() => {})
      location = null
    }
  }
  signal.addEventListener('abort', close, { once: true })

  try {
    connection.addTransceiver('video', { direction: 'recvonly' })
    const stream = new Promise<MediaStream>((resolve) => {
      connection.addEventListener(
        'track',
        (event) => resolve(event.streams[0] ?? new MediaStream([event.track])),
        { once: true },
      )
    })

    await connection.setLocalDescription(await connection.createOffer())
    const response = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/sdp' },
      body: connection.localDescription?.sdp,
      signal: AbortSignal.any([signal, AbortSignal.timeout(OFFER_TIMEOUT_MS)]),
    })
    if (response.status !== 201) {
      throw new Error(`The offer was refused with status ${response.status}.`)
    }

    const answer = await response.text()
    location = new URL(response.headers.get('location') ?? '', url).toString()
    if (signal.aborted) {
      close()
      throw signal.reason
    }

    await connection.setRemoteDescription({ type: 'answer', sdp: answer })
    await connected(connection)
    await firstFrame(connection)
    connection.addEventListener('connectionstatechange', () => {
      const state = connection.connectionState
      if (state === 'failed' || state === 'disconnected') {
        onLost(`The WebRTC connection is ${state}.`)
      }
    })

    return { stream: await stream, close }
  } catch (error) {
    close()
    throw error
  } finally {
    signal.removeEventListener('abort', close)
  }
}

/** Resolves once `connection` is up, rejecting when it fails or takes too long. */
function connected(connection: RTCPeerConnection) {
  return new Promise<void>((resolve, reject) => {
    const timer = setTimeout(
      () => settle(new Error('The WebRTC connection did not come up.')),
      CONNECT_TIMEOUT_MS,
    )
    const check = () => {
      if (connection.connectionState === 'connected') {
        settle()
      } else if (['failed', 'closed'].includes(connection.connectionState)) {
        settle(new Error(`The WebRTC connection ${connection.connectionState}.`))
      }
    }
    const settle = (error?: Error) => {
      clearTimeout(timer)
      connection.removeEventListener('connectionstatechange', check)
      if (error == null) {
        resolve()
      } else {
        reject(error)
      }
    }
    connection.addEventListener('connectionstatechange', check)
    check()
  })
}

/** Resolves once `connection` has decoded a video frame, rejecting when none comes in time. */
async function firstFrame(connection: RTCPeerConnection) {
  const deadline = Date.now() + FRAME_TIMEOUT_MS
  while (Date.now() < deadline) {
    const stats = await connection.getStats()
    for (const report of stats.values()) {
      if (report.type === 'inbound-rtp' && report.kind === 'video' && report.framesDecoded > 0) {
        return
      }
    }

    await new Promise((resolve) => setTimeout(resolve, FRAME_POLL_MS))
  }

  throw new Error('The WebRTC connection brought no picture.')
}

/** Which transport each video plays over, decided by its first try and kept for the page's
life, so a network that drops WebRTC costs one wait per video rather than one per reconnect. */
export const useVideoTransports = defineStore('video-transports', () => {
  // One entry per WHEP route a widget on the page has tried, bounded by the videos in view.
  const verdicts = new Map<string, VideoTransport>()

  return {
    verdict: (url: string) => verdicts.get(url) ?? null,
    remember: (url: string, transport: VideoTransport) => void verdicts.set(url, transport),
  }
})
