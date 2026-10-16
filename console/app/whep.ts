import { defineStore } from 'pinia'
import { reactive } from 'vue'

/** How a video widget receives its picture, named on the widget so a fallback is visible. */
export type VideoTransport = 'webrtc' | 'http'

/** The transport a video plays over, and `why`, one sentence a viewer can act on. */
export interface TransportChoice {
  transport: VideoTransport
  why: string
}

// A video that takes longer than these to show its picture over WebRTC plays over HTTP instead,
// since a network that drops UDP fails WebRTC by silence rather than by an error.
const offerTimeoutMs = 10_000
const connectTimeoutMs = 5_000
const frameTimeoutMs = 5_000
const framePollMs = 250

/** The server's refusal of an offer, with the `reason` its envelope gives. */
export class WhepRefusal extends Error {
  constructor(
    readonly status: number,
    readonly reason: string | null,
  ) {
    super(`The offer was refused with status ${status}${reason == null ? '' : `, ${reason}`}.`)
  }
}

/** A session the server answered that never connected or never brought a picture. */
export class WhepSilence extends Error {}

// Refusals that the same video meets on every try, where `full`, `source`, and `timeout` pass.
const permanentReasons = new Set(['disabled', 'not-live', 'codec', 'offer', 'reordered'])

/** Whether `error` failing a first try means the video plays over HTTP for the page's life.

Silence counts, since a network that drops UDP stays that way, while a refusal the server may lift
on the next try falls back for that try alone.
*/
export function permanent(error: unknown) {
  if (error instanceof WhepSilence) {
    return true
  }
  if (error instanceof WhepRefusal) {
    return error.status === 415 || (error.reason != null && permanentReasons.has(error.reason))
  }
  return false
}

const offerWhy = 'WebRTC could not be set up with this browser.'

// Why a first try over WebRTC fell to HTTP, by the reason the server's refusal gives. Each is one
// short fact, since it shows in a tooltip.
const refusalWhys: Record<string, string> = {
  disabled: 'WebRTC is turned off on the server.',
  'not-live': 'WebRTC only carries live video.',
  codec: "This browser cannot decode the video's codec over WebRTC.",
  offer: offerWhy,
  reordered: 'The video has B-frames, which WebRTC cannot play smoothly.',
  full: 'The server is at its WebRTC limit.',
  source: 'The video did not start over WebRTC.',
  timeout: 'The video did not start over WebRTC in time.',
}

/** Why `error` failing a first try over WebRTC left the video playing over HTTP. */
export function fallbackWhy(error: unknown) {
  if (error instanceof WhepSilence) {
    return 'The network blocks WebRTC.'
  }
  if (error instanceof WhepRefusal) {
    if (error.status === 415) {
      return offerWhy
    }
    return refusalWhys[error.reason ?? ''] ?? 'The server refused WebRTC.'
  }
  return 'The WebRTC request failed.'
}

/** A procedure's live video playing over WebRTC. */
export interface WhepSession {
  /** The video's picture, for a video element's `srcObject`. */
  readonly stream: MediaStream
  /** End the session, here and on the server. */
  close(): void
}

/** Play the live video behind a WHEP route at `url`, resolving once its first frame is decoded.

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
      signal: AbortSignal.any([signal, AbortSignal.timeout(offerTimeoutMs)]),
    })
    if (response.status !== 201) {
      throw new WhepRefusal(response.status, await refusalReason(response))
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

/** The `reason` a refusal's JSON envelope gives, `null` for any other body. */
async function refusalReason(response: Response) {
  try {
    const { reason } = (await response.json()) as { reason?: unknown }
    return typeof reason === 'string' ? reason : null
  } catch {
    return null
  }
}

/** Resolves once `connection` is up, rejecting when it fails or takes too long. */
function connected(connection: RTCPeerConnection) {
  return new Promise<void>((resolve, reject) => {
    const timer = setTimeout(
      () => settle(new WhepSilence('The WebRTC connection did not come up.')),
      connectTimeoutMs,
    )
    const check = () => {
      if (connection.connectionState === 'connected') {
        settle()
      } else if (['failed', 'closed'].includes(connection.connectionState)) {
        settle(new WhepSilence(`The WebRTC connection ${connection.connectionState}.`))
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
  const deadline = Date.now() + frameTimeoutMs
  while (Date.now() < deadline) {
    const stats = await connection.getStats()
    for (const report of stats.values()) {
      if (report.type === 'inbound-rtp' && report.kind === 'video' && report.framesDecoded > 0) {
        return
      }
    }

    await new Promise((resolve) => setTimeout(resolve, framePollMs))
  }

  throw new WhepSilence('The WebRTC connection brought no picture.')
}

/** Which transport each video plays over, decided by its first try and kept for the page's
life, so a network that drops WebRTC costs one wait per video rather than one per reconnect.

Also what each video widget on the page plays over now, for its settings to explain. */
export const useVideoTransports = defineStore('video-transports', () => {
  // One entry per WHEP route a widget on the page has tried, bounded by the videos in view.
  const verdicts = new Map<string, TransportChoice>()
  // One entry per video widget on the page, by its ID, while it plays.
  const playing = reactive(new Map<string, TransportChoice>())

  return {
    verdict: (url: string) => verdicts.get(url) ?? null,
    remember: (url: string, choice: TransportChoice) => void verdicts.set(url, choice),
    playing: (widget: string) => playing.get(widget) ?? null,
    show: (widget: string, choice: TransportChoice | null) => {
      if (choice == null) {
        playing.delete(widget)
      } else {
        playing.set(widget, choice)
      }
    },
  }
})
