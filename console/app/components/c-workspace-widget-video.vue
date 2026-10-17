<script lang="ts" setup>
import { useEventListener, useIntervalFn, useTimeoutFn } from '@vueuse/core'
import { onBeforeUnmount, watch, watchEffect } from 'vue'

import { useEngine } from '@/api/engine'
import { isMediaSourceSupported } from '@/environment'
import icons from '@/icons'
import { readInitSegment } from '@/mp4'
import { useReconnectSchedule } from '@/reconnect'
import { getHttpUrl } from '@/utilities'
import { keptSeconds } from '@/video-buffer'
import { videoCodec } from '@/video-codecs'
import {
  fallbackWhy,
  openWhep,
  permanent,
  type TransportChoice,
  useVideoTransports,
  type VideoTransport,
  WhepRefusal,
  type WhepSession,
} from '@/whep'
import type { WidgetStatus } from '@/widget-status'
import { useWorkspace } from '@/workspace'
import type { VideoWidget } from '@/workspace'

const { widget } = defineProps<{
  widget: VideoWidget
}>()

const emit = defineEmits<{
  reloadRequested: []
  settingsRequested: []
  /** A short note for the widget's header, or `null` to clear it. */
  status: [status: WidgetStatus | null]
}>()

const engine = useEngine()
const workspace = useWorkspace()

const element = $ref<HTMLVideoElement | null>(null)
const lastFrame = $ref<HTMLCanvasElement | null>(null)
const container = $ref<HTMLDivElement | null>(null)

let state = $ref<'loading' | 'error' | 'ok'>('loading')
// Why this browser cannot play the video at all, shown in place of the general error, since no
// reconnect would change it and a viewer can act on it by changing browser or transport.
let unplayable = $ref<string | null>(null)

let isUnloading = $ref(false)
let isMuted = $ref(widget.startMuted)
let isDisposed = false

// Bumped for each reconnect attempt and carried in the URL's fragment, so the element sees a new
// source and loads the stream anew. A query parameter would reach the query as an argument.
let attempt = $ref(0)
// Whether the last frame is held up over the element while a new connection comes up.
let isHoldingFrame = $ref(false)
// Whether the video should be moving, so that a picture standing still means it was lost. A pause
// the viewer asked for clears it.
let isMeantToPlay = $ref(false)
// Whether a pause or reload in flight is the widget's own doing rather than the viewer's.
let isReloading = false

// The query field encodes a component address as `@component::queries::name`, a relative address
// or nothing in place of `@component` naming one under or at the workspace's own component. Only
// the leading address portion resolves, the rest names a query on that component.
const queryComponent = $computed(() => {
  const raw = widget.query?.split('::')?.[0]
  if (raw == null) {
    return null
  }

  return workspace.resolveAddress(raw)?.toString() ?? null
})

const queryName = $computed(() => widget.query?.split('::')?.[2] ?? null)

const queryInfo = $computed(() => {
  if (queryComponent == null || queryName == null) {
    return null
  }

  return (
    engine.components
      .get(queryComponent)
      ?.procedures.find((current) => current.name === queryName && current.type === 'query') ?? null
  )
})

const isStreamingOutput = $computed(() => queryInfo?.output.type === 'streaming')

// A streaming query may read live video the engine can send over WebRTC, which is tried first.
const whepUrl = $computed(() => {
  if (
    !isStreamingOutput ||
    queryComponent == null ||
    queryName == null ||
    typeof RTCPeerConnection === 'undefined'
  ) {
    return null
  }

  // Same-origin, unlike the video's own URL, since a posted offer is a CORS request the
  // engine's port refuses in development while the dev proxy forwards it.
  const url = new URL(
    `/api/components/${queryComponent}/procedures/${queryName}/whep`,
    window.location.href,
  )
  // Video with frames out of display order plays back and forth over WebRTC. Automatic
  // lets the server refuse it for HTTP at the full frame rate, and WebRTC held asks it to drop
  // the frames nothing references, for the lower delay at a lower frame rate.
  if (widget.transport === 'webrtc') {
    url.searchParams.set('reordered', 'drop')
  }
  return url.toString()
})

const transports = useVideoTransports()
// `null` while the first try over WebRTC decides between the two.
let transport = $ref<VideoTransport | null>(null)
// Why `transport` was chosen, for the widget's settings to explain.
let transportWhy = $ref<string | null>(null)

/** Settle on `choice`, or on nothing while a first try decides. */
function choose(choice: TransportChoice | null) {
  transport = choice?.transport ?? null
  transportWhy = choice?.why ?? null
}

watchEffect(() =>
  transports.show(
    widget.id,
    transport == null
      ? null
      : { transport, ...(transportWhy == null ? {} : { why: transportWhy }) },
  ),
)
onBeforeUnmount(() => transports.show(widget.id, null))

const url = $computed(() => {
  if (queryComponent == null || queryName == null || isDisposed) {
    return undefined
  }

  // Absolute so the request goes straight to the engine. The dev proxy does not cancel a request
  // when the video element unloads, so the engine keeps streaming to it until the proxy restarts.
  const path = `/api/components/${queryComponent}/queries/${queryName}/call`
  return getHttpUrl(attempt === 0 ? path : `${path}#attempt=${attempt}`)
})

// Whether this attempt plays the stream straight from its URL, because it turned out not to be one
// a `MediaSource` can take. The next attempt tries a `MediaSource` again.
let isPlayingDirectly = $ref(false)

// A streaming output over HTTP is downloaded and fed to a `MediaSource` rather than played
// straight from its URL. Safari plays no video without byte ranges, which an endless stream cannot
// offer, and elsewhere the element reads ahead into its own cache, so neither the lag behind the
// source nor whether the stream is live can be told. A file plays directly, finished and rangeable,
// and so does a stream a `MediaSource` cannot take.
const isUsingMediaSourceBuffer = $computed(
  () => transport === 'http' && isStreamingOutput && isMediaSourceSupported && !isPlayingDirectly,
)

// The duration a `MediaSource` reported once its metadata loaded, `null` before then.
let bufferedDuration = $ref<number | null>(null)
// Whether the stream's MP4 init segment declares no length, `null` until it is read, or when it
// is not one this console reads.
let isDeclaredLive = $ref<boolean | null>(null)

// Whether the video is live rather than a recording, `null` while that is not known. A live stream
// has no end, so its init segment declares no length. The browser's duration says the same in
// Chrome, which reports it infinite, but Safari reports a finite one, so the init segment decides
// wherever it was read. Only a `MediaSource` reads the container's own, where an element playing
// a URL directly estimates a duration from the bytes so far and so calls a live stream finite.
const isLive = $computed(() => {
  if (queryInfo?.output.type === 'file') {
    return false
  }
  if (transport === 'webrtc') {
    return true
  }
  if (!isUsingMediaSourceBuffer) {
    return null
  }
  if (isDeclaredLive != null) {
    return isDeclaredLive
  }

  return bufferedDuration == null ? null : bufferedDuration === Infinity
})

let mediaSource: MediaSource | null = $shallowRef(null)

const src = $computed(() => {
  if (isDisposed || transport !== 'http') {
    return undefined
  }

  if (isUsingMediaSourceBuffer) {
    return mediaSource == null ? undefined : URL.createObjectURL(mediaSource)
  }

  return url
})

// A blob URL keeps its `MediaSource` alive until revoked, so each one replaced would leak.
watch(
  () => src,
  (_, previous) => {
    if (previous?.startsWith('blob:')) {
      URL.revokeObjectURL(previous)
    }
  },
)

/** Give up on the `MediaSource` for this attempt and let the element play the URL itself. */
function playDirectly(reason: string) {
  console.info(`Playing ${url} directly. ${reason}`)
  mediaSourceRequest?.abort()
  mediaSourceRequest = null
  mediaSource = null
  isPlayingDirectly = true
}

/** Concatenate two byte arrays. */
function joined(first: Uint8Array, second: Uint8Array) {
  const bytes = new Uint8Array(first.length + second.length)
  bytes.set(first)
  bytes.set(second, first.length)
  return bytes
}

/** The buffer type for a stream, read from its init segment for MP4, or `null` when its codecs
cannot be told. `undefined` while `head` holds too little of the stream to tell. */
function mediaSourceBufferType(contentType: string, head: Uint8Array) {
  const mediaType = contentType.split(';')[0]!.trim()
  const isNamingCodecs = contentType.includes('codecs=')
  if (mediaType !== 'video/mp4') {
    return contentType
  }

  // Read even when the type names the codecs, for the length the stream declares.
  const segment = readInitSegment(head)
  if (segment.type === 'partial') {
    return undefined
  }
  if (segment.type === 'codecs') {
    isDeclaredLive = segment.duration == null
  }
  if (isNamingCodecs) {
    return contentType
  }

  return segment.type === 'codecs' ? `video/mp4; codecs="${segment.codecs}"` : null
}

// The codecs of a stream the buffer refused, kept so that the element failing on it as well can
// say which codec this browser lacks.
let refusedCodecs: string | null = null

/** Why this browser cannot play video in `codecs`, with what a viewer might do about it. */
function cannotPlay(codecs: string) {
  const { name, advice } = videoCodec(codecs)
  return `This browser cannot play ${name} video. ${advice ?? 'Try another browser.'}`
}

// The request feeding the current `MediaSource`, aborted when a newer one replaces it.
let mediaSourceRequest: AbortController | null = null

/** Feed the stream at `url` into a fresh `MediaSource`, for as long as it stays the bound one. */
async function syncMediaSource(url: string | null | undefined) {
  mediaSourceRequest?.abort()
  mediaSourceRequest = null
  bufferedDuration = null
  isDeclaredLive = null
  refusedCodecs = null
  // A `MediaSource` attaches only once, so a reload of the element meanwhile would fail on it.
  mediaSource = null

  if (url == null) {
    state = 'ok'
    return
  }

  const request = new AbortController()
  mediaSourceRequest = request
  state = 'loading'

  // Read through the page's own origin. A `fetch`, unlike the element, is bound by CORS, which the
  // engine does not answer when the dev console serves the page from a port of its own.
  const { pathname, hash } = new URL(url)
  let result: Response
  try {
    result = await fetch(new URL(`${pathname}${hash}`, window.location.href), {
      signal: request.signal,
    })
  } catch (error) {
    if (!request.signal.aborted) {
      fail(`The video request failed. ${String(error)}`)
    }
    return
  }

  if (!result.ok) {
    fail(`The video request failed with status ${result.status}.`)
    return
  }

  const contentType = result.headers.get('content-type')
  if (contentType == null) {
    fail('Failed to get video content type from response headers.')
    return
  }

  const reader = result.body?.getReader()
  if (reader == null) {
    fail('No data in response.')
    return
  }

  try {
    // The bytes read before the buffer exists, held for its first append.
    let head = new Uint8Array(new ArrayBuffer(0))
    let bufferType: string | null | undefined
    while ((bufferType = mediaSourceBufferType(contentType, head)) === undefined) {
      const { value: chunk } = await reader.read()
      if (chunk == null) {
        fail('The video stream ended before its first frame.')
        return
      }
      head = joined(head, chunk)
    }

    if (bufferType == null) {
      playDirectly(`The codecs of "${contentType}" cannot be told.`)
      return
    }

    // The element may still play what the buffer cannot, so this only records what to blame.
    if (!MediaSource.isTypeSupported(bufferType)) {
      refusedCodecs = /codecs="([^"]*)"/.exec(bufferType)?.[1] ?? null
      playDirectly(`This browser cannot buffer "${bufferType}" itself.`)
      return
    }

    const boundMediaSource = new MediaSource()
    mediaSource = boundMediaSource

    const once = { once: true, passive: true }
    await new Promise((resolve) => boundMediaSource.addEventListener('sourceopen', resolve, once))

    const buffer = boundMediaSource.addSourceBuffer(bufferType)
    // Safari takes the duration from what is buffered, so playback that catches up with the
    // newest frame reaches the end and ends a live stream. An endless duration has no end.
    if (isDeclaredLive === true) {
      boundMediaSource.duration = Infinity
    }
    let pending: Uint8Array<ArrayBuffer> | null = head
    // The stream's bitrate, from all it sent over the time it covers, to size what is kept.
    let appendedBytes = 0
    let firstTime: number | null = null
    while (boundMediaSource === mediaSource && element?.src === src) {
      const chunk: Uint8Array<ArrayBuffer> | undefined = pending ?? (await reader.read()).value
      pending = null
      if (chunk == null) {
        // A recording has finished downloading, where a live view counts that as losing it.
        if (isLive === false) {
          if (boundMediaSource.readyState === 'open') {
            boundMediaSource.endOfStream()
          }
        } else if (boundMediaSource === mediaSource) {
          fail('The video stream ended.')
        }
        break
      }

      // A `SourceBuffer` keeps every fragment until told otherwise, so a live view left open for
      // hours fills it and the next append throws. A recording keeps all of it to seek over.
      const { buffered } = buffer
      if (buffered.length > 0) {
        firstTime ??= buffered.start(0)
      }
      const span =
        buffered.length > 0 && firstTime != null ? buffered.end(buffered.length - 1) - firstTime : 0
      const playedUntil =
        (element?.currentTime ?? 0) - keptSeconds(span > 0 ? appendedBytes / span : 0)
      if (isLive !== false && buffered.length > 0 && buffered.start(0) < playedUntil) {
        buffer.remove(buffer.buffered.start(0), playedUntil)
        await new Promise((resolve) => buffer.addEventListener('updateend', resolve, once))
      }

      try {
        buffer.appendBuffer(chunk)
        appendedBytes += chunk.byteLength
      } catch (error) {
        // Any other failure means the `src` changed and detached the media source.
        if (error instanceof DOMException && error.name === 'QuotaExceededError') {
          fail('The video buffer is full.')
        }
        break
      }

      await new Promise((resolve) => buffer.addEventListener('updateend', resolve, once))
    }
  } catch (error) {
    if (!request.signal.aborted) {
      fail(`Reading the video stream failed. ${String(error)}`)
    }
  } finally {
    // Without this the request runs until the tab closes or the server hangs up, and the engine
    // keeps streaming to a widget nobody watches.
    await reader.cancel().catch(() => {})
  }
}

watchEffect(() => {
  if (isUsingMediaSourceBuffer) {
    void syncMediaSource(url)
  }
})

let whep: WhepSession | null = null
// The negotiation in flight, aborted when a newer attempt or the widget's end replaces it.
let whepRequest: AbortController | null = null

function closeWhep() {
  whepRequest?.abort()
  whepRequest = null
  whep?.close()
  whep = null
  // Setting `srcObject`, even to the value it holds, reloads the element from its `src`.
  if (element?.srcObject != null) {
    element.srcObject = null
  }
}

/** Play the live video at `target` over WebRTC, or settle on HTTP when a first try cannot. */
async function playWhep(target: string) {
  closeWhep()
  const request = new AbortController()
  whepRequest = request
  // The negotiation bounds itself, and an HTTP fallback gets a deadline of its own.
  reconnect.stop()
  try {
    const session = await openWhep(target, {
      signal: request.signal,
      onLost: (reason) => {
        if (whep === session) {
          fail(reason)
        }
      },
    })
    whep = session
    const choice: TransportChoice =
      widget.transport === 'auto'
        ? { transport: 'webrtc' }
        : { transport: 'webrtc', why: 'Set to WebRTC in the settings.' }
    choose(choice)
    if (widget.transport === 'auto') {
      transports.remember(target, choice)
    }
    if (element != null) {
      element.srcObject = session.stream
    }
  } catch (error) {
    if (request.signal.aborted) {
      return
    }

    if (widget.transport === 'webrtc') {
      // Held to WebRTC, so its failure shows rather than being hidden by a fallback.
      if (error instanceof WhepRefusal && error.reason === 'codec') {
        refuse(
          "This browser cannot decode this video's codec over WebRTC. Choose HTTP in the widget's settings, or try another browser.",
        )
        return
      }

      fail(`WebRTC failed. ${String(error)}`)
      return
    }

    if (transport === 'webrtc') {
      // The network carried WebRTC before, so a drop is a lost source rather than a blocked path.
      fail(`WebRTC did not reconnect. ${String(error)}`)
      return
    }

    console.info(`Playing ${target} over HTTP. ${String(error)}`)
    const choice: TransportChoice = { transport: 'http', why: fallbackWhy(error) }
    choose(choice)
    if (permanent(error)) {
      transports.remember(target, choice)
    }
    if (widget.reconnect) {
      reconnect.begin()
    }
  }
}

const reconnect = useReconnectSchedule(() => {
  holdLastFrame()
  isReloading = true
  isPlayingDirectly = false
  isHoldingBack = false
  attempt += 1
})

/** Draw the frame on screen onto the canvas over the element, so a reconnect does not flash to
black. Nothing is drawn before the first frame, leaving the canvas hidden. */
function holdLastFrame() {
  if (isHoldingFrame || element == null || lastFrame == null || element.videoWidth === 0) {
    return
  }

  lastFrame.width = element.videoWidth
  lastFrame.height = element.videoHeight
  lastFrame.getContext('2d')?.drawImage(element, 0, 0)
  isHoldingFrame = true
}

/** The stream was lost. Reconnects when the widget is set to, otherwise shows the error box. */
function fail(reason: string) {
  if (isDisposed) {
    return
  }

  const error = element?.error
  const at = transport === 'webrtc' ? `${whepUrl} over WebRTC` : `${url} over HTTP`
  console.warn(
    `Lost the video at ${at} (attempt ${attempt}). ${reason}`,
    error != null ? { code: error.code, message: error.message } : '',
  )

  if (widget.reconnect && url != null) {
    reconnect.lost()
  } else {
    state = 'error'
  }
}

/** This browser cannot play the video, for `reason`. Shows it rather than reconnecting, since no
retry would change it. */
function refuse(reason: string) {
  if (isDisposed) {
    return
  }

  console.warn(`The video at ${url} cannot play. ${reason}`)
  reconnect.stop()
  unplayable = reason
  state = 'error'
}

function onError() {
  // A stream refused before its first metadata is one the buffer cannot take, such as an MP4 with
  // its index at the end, which the element can still play from the URL. A decode error is not.
  const isRefused = element?.error?.code === MediaError.MEDIA_ERR_SRC_NOT_SUPPORTED
  if (isUsingMediaSourceBuffer && bufferedDuration == null && isRefused) {
    playDirectly(`The buffer refused the stream. ${element?.error?.message ?? ''}`)
    return
  }

  // The element failing on a codec the buffer already refused confirms this browser lacks it.
  if (isPlayingDirectly && refusedCodecs != null) {
    refuse(cannotPlay(refusedCodecs))
    return
  }

  fail('The video element reported an error.')
}

function onEnded() {
  // A recording has played to its end, where a live view counts that as losing the stream.
  if (isLive === false) {
    isMeantToPlay = false
    return
  }

  fail('The video played to its end.')
}

async function onLoad() {
  if (isUsingMediaSourceBuffer && element != null) {
    bufferedDuration = element.duration
  }

  if (element != null && (widget.autoplay || isMeantToPlay)) {
    try {
      await element.play()
      state = 'ok'
    } catch (error) {
      console.warn('Autoplay failed.', error)
    }
  }
}

function onPlay() {
  state = 'ok'
  isMeantToPlay = true
}

function onPause() {
  // A browser pauses muted video in a hidden tab on its own, which is not a choice to stop it.
  if (!isReloading && !isDisposed && document.visibilityState === 'visible') {
    isMeantToPlay = false
    // Pausing a live picture over HTTP keeps the frames it missed, so it plays on from where it was
    // paused at its own pace, as one sought back does. WebRTC holds nothing to play on from.
    if (isLive === true && transport === 'http') {
      isHoldingBack = true
    }
  }
}

// A paused live stream is frozen rather than buffering, and a browser does not always resume
// what it paused while hidden, so the widget does once the tab is back.
useEventListener(document, 'visibilitychange', () => {
  if (document.visibilityState === 'visible' && element?.paused && isMeantToPlay) {
    element.play().catch((error) => console.warn('Resuming the video failed.', error))
  }
})

/** Frames are arriving again, so whatever reconnecting there was is over. The first frame of a
paused video counts too, so a paused widget does not retry a connection that already came back. */
function onFrames() {
  isReloading = false
  isHoldingFrame = false
  hasPicture = true
  onPlaying()
  reconnect.recovered()
}

// A spinner shows only for a real wait, never the passing ones a live stream over a poor link has
// every few seconds. Before the first frame it takes the middle of the empty widget, and after it a
// small one keeps to the corner so the held picture stays in view.
/** How long playback must wait on the network before it counts as loading. */
const loadingAfterMs = 1000
/** Whether the element has a frame to show, which a wait leaves on screen. */
let hasPicture = $ref(false)
/** Whether playback has waited on the network past `loadingAfterMs`. */
let isLoadingMore = $ref(false)
const loadingMore = useTimeoutFn(() => (isLoadingMore = true), loadingAfterMs, {
  immediate: false,
})

function onWaiting() {
  loadingMore.start()
}

function onPlaying() {
  loadingMore.stop()
  isLoadingMore = false
}

function onEmptied() {
  hasPicture = false
  onPlaying()
}

// A playing video that shows no new frame for this long has lost its stream without saying so.
// Frames are counted rather than time, which a WebRTC stream's clock keeps running without them.
const stallSeconds = 10
let lastFrames = -1
let stillFor = 0

// A video set to Automatic whose WebRTC stalls this often plays over HTTP instead, since a decoder
// that fails on its video fails again on every new session. Chrome's hardware H.265 decoder does
// so on a picture loss damaged, and falls back to a decoder that decodes nothing.
const stallsBeforeHttp = 2
const stallWindowMs = 60_000
let webrtcStalls: number[] = []

/** The frames the browser has decoded so far. Over WebRTC the decoder's own count, since the
element's misses a decoder that fails while frames keep arriving. */
async function framesDecoded(video: HTMLVideoElement) {
  if (transport === 'webrtc' && whep != null) {
    return (await whep.decoding())?.decoded ?? 0
  }
  return video.getVideoPlaybackQuality().totalVideoFrames
}

/** The WebRTC video stopped showing frames. Logs what the decoder did, then reconnects, over
HTTP once it happened too often for a video set to Automatic. */
async function stallWebrtc(session: WhepSession) {
  const decoding = await session.decoding()
  console.warn(
    `WebRTC decoded ${decoding?.decoded ?? 0} of the ${decoding?.received ?? 0} frames it received, with ${decoding?.decoder ?? 'no decoder'}.`,
  )
  fail(`No new frames for ${stallSeconds} seconds.`)
  const now = Date.now()
  webrtcStalls = [...webrtcStalls.filter((at) => now - at < stallWindowMs), now]
  if (widget.transport === 'auto' && whepUrl != null && webrtcStalls.length >= stallsBeforeHttp) {
    webrtcStalls = []
    const choice: TransportChoice = {
      transport: 'http',
      why: 'WebRTC stopped showing frames twice in a minute.',
    }
    // The reconnect `fail` scheduled reads this, so it starts over HTTP.
    choose(choice)
    transports.remember(whepUrl, choice)
  }
}

// Only watched while in sight, since browsers pause or starve video in a hidden tab. A recording
// standing still is only waiting on its download.
useIntervalFn(async () => {
  const isWatching =
    widget.reconnect &&
    isLive !== false &&
    element != null &&
    !element.paused &&
    isMeantToPlay &&
    reconnect.countdown == null &&
    document.visibilityState === 'visible'
  if (!isWatching) {
    stillFor = 0
    return
  }

  const session = transport === 'webrtc' ? whep : null
  const frames = await framesDecoded(element)
  if (frames !== lastFrames) {
    lastFrames = frames
    stillFor = 0
    return
  }

  stillFor += 1
  if (stillFor >= stallSeconds) {
    stillFor = 0
    if (session != null) {
      await stallWebrtc(session)
    } else {
      fail(`No new frames for ${stallSeconds} seconds.`)
    }
  }
}, 1000)

// Every time playback waits on the network the picture falls that much further behind, and the
// element never makes the time up, so a live view left open drifts minutes behind its source.
// A lagging video plays fast until it is back near the newest frame, faster the further behind it
// is, so a small lag closes unnoticed and a large one closes in a few seconds without skipping any
// of it. Only a lag past what that plays off is jumped.
/** How far short of the newest frame playback is steered, so the next fragment is there in time. */
const targetLagSeconds = 0.5
/** The lag past the target that starts a catch-up, so a passing hiccup does not. */
const catchUpAfterSeconds = 0.5
/** The catch-up's speed just past where it starts, and while it closes the last of the lag. */
const minCatchUpRate = 1.1
/** The catch-up's speed as the lag nears `maxLagSeconds`. */
const maxCatchUpRate = 3
/** A lag past this is jumped instead of played off. */
const maxLagSeconds = 5

/** The catch-up's speed for `lag`, rising in a line from the minimum where a catch-up starts to the
maximum at the jump, in tenths so a steady lag does not set a new rate every tick. */
function catchUpRate(lag: number) {
  const start = targetLagSeconds + catchUpAfterSeconds
  const share = Math.min(Math.max((lag - start) / (maxLagSeconds - start), 0), 1)
  const rate = minCatchUpRate + share * (maxCatchUpRate - minCatchUpRate)
  return Math.round(rate * 10) / 10
}

// Whether the playback rate is the catch-up's, so only that is undone and a speed the viewer
// picked for a recording stays.
let isCatchingUp = false

function stopCatchingUp() {
  if (isCatchingUp && element != null) {
    element.playbackRate = 1
  }
  isCatchingUp = false
}

/** Whether a live picture is paused or lagging, which grays its live dot in the header. */
let isBehindLive = $ref(false)

/** Whether the viewer sought back in a live picture, which plays on from there at its own pace
until the viewer goes back to live, rather than being caught up the moment it was moved. */
let isHoldingBack = $ref(false)

/** The viewer moved a live picture's position, holding it there unless that was to the newest. */
function onSeek() {
  if (element == null || isLive !== true) {
    return
  }

  const { buffered } = element
  const lag = buffered.length > 0 ? buffered.end(buffered.length - 1) - element.currentTime : 0
  isHoldingBack = lag > targetLagSeconds + catchUpAfterSeconds
}

useIntervalFn(() => {
  if (element == null || isLive !== true) {
    isBehindLive = false
    stopCatchingUp()
    return
  }

  if (element.paused || isHoldingBack) {
    isBehindLive = true
    stopCatchingUp()
    return
  }

  // WebRTC plays each frame as it arrives, so only a live stream over HTTP lags or is steered.
  const { buffered, seekable } = element
  if (transport !== 'http' || buffered.length === 0) {
    isBehindLive = false
    stopCatchingUp()
    return
  }

  const newest = buffered.end(buffered.length - 1)
  const lag = newest - element.currentTime
  const live = newest - targetLagSeconds
  // Trimming can leave playback behind what is still buffered, where it would wait forever.
  const isBeforeBuffer = element.currentTime < buffered.start(0)
  // A jump to a time that cannot be sought lands back at the start.
  const canJump = [...Array(seekable.length).keys()].some(
    (index) => seekable.start(index) <= live && live <= seekable.end(index),
  )
  isBehindLive = lag > targetLagSeconds + catchUpAfterSeconds
  if ((lag > maxLagSeconds || isBeforeBuffer) && canJump) {
    element.currentTime = live
    stopCatchingUp()
  } else if (
    lag > targetLagSeconds + catchUpAfterSeconds ||
    (isCatchingUp && lag > targetLagSeconds)
  ) {
    // Eased down as the lag closes, so playback does not overshoot the newest frame and wait.
    const rate = catchUpRate(lag)
    if (element.playbackRate !== rate) {
      element.playbackRate = rate
    }
    isCatchingUp = true
  } else if (lag <= targetLagSeconds) {
    stopCatchingUp()
  }
}, 250)

// A first connection gets the same deadline as a retry, so one that never answers is retried too.
watch(
  () => [url == null, widget.reconnect] as const,
  ([isUnset, isReconnecting]) => {
    if (isUnset || !isReconnecting) {
      reconnect.stop()
    } else if (attempt === 0 && widget.autoplay) {
      reconnect.begin()
    }
  },
  { immediate: true },
)

// A new query or transport starts over, from a first attempt with nothing held.
watch(
  () => [widget.query, widget.transport] as const,
  () => {
    reconnect.recovered()
    attempt = 0
    isPlayingDirectly = false
    isHoldingBack = false
    isHoldingFrame = false
    unplayable = null
    // Stalls on another video say nothing about this one.
    webrtcStalls = []
    state = 'loading'
    if (widget.reconnect && widget.autoplay) {
      reconnect.begin()
    }
  },
)

// Each attempt over WebRTC negotiates a new session, where HTTP takes a new `src` instead.
watch(
  () => [whepUrl, attempt, widget.transport] as const,
  ([target, , forced]) => {
    closeWhep()
    if (forced === 'webrtc' && target == null) {
      choose(null)
      refuse("This video cannot play over WebRTC. Choose Auto or HTTP in the widget's settings.")
      return
    }

    if (forced === 'http') {
      choose({ transport: 'http', why: 'Set to HTTP in the settings.' })
      return
    }

    if (target == null) {
      choose({
        transport: 'http',
        why: isStreamingOutput ? 'This browser has no WebRTC.' : 'WebRTC only carries live video.',
      })
      return
    }

    // A forced transport neither reads nor writes what an automatic choice remembers.
    choose(forced === 'auto' ? transports.verdict(target) : null)
    if (transport !== 'http' && !isDisposed) {
      void playWhep(target)
    }
  },
  { immediate: true },
)

/** The transport in use, named so a fallback to HTTP is visible, or the setting's own name
while the first try decides. */
const transportLabel = $computed(() => {
  if (url == null) {
    return null
  }

  return transport === 'http' ? 'HTTP' : 'WebRTC'
})

/** Play live video from its newest frame, resuming it if paused. */
function goLive() {
  if (element == null) {
    return
  }

  isHoldingBack = false
  const { buffered } = element
  if (transport === 'http' && buffered.length > 0) {
    element.currentTime = buffered.end(buffered.length - 1) - targetLagSeconds
  }
  isMeantToPlay = true
  element.play().catch((error) => console.warn('Resuming the video failed.', error))
}

const transportNames: Record<VideoWidget['transport'], string> = {
  auto: 'Auto',
  webrtc: 'WebRTC',
  http: 'HTTP',
}

const transportCycle: Record<VideoWidget['transport'], VideoWidget['transport']> = {
  auto: 'webrtc',
  webrtc: 'http',
  http: 'auto',
}

/** Switch the widget's transport setting to the next one, as the header's transport does. */
function cycleTransport() {
  widget.transport = transportCycle[widget.transport]
}

const status = $computed((): WidgetStatus | null => {
  if (transportLabel == null) {
    return null
  }

  let text: string = transportLabel
  if (transport == null) {
    // Still deciding, so the setting shows, which keeps the header still while a click cycles.
    text = widget.transport === 'auto' ? 'Auto' : transportNames[widget.transport]
  } else if (widget.transport === 'auto') {
    text = `${transportLabel} (Auto)`
  }
  const transportStatus = { text, cycle: cycleTransport }
  return isLive === true
    ? { ...transportStatus, live: isBehindLive ? 'behind' : 'live', goLive }
    : transportStatus
})

// The header lives in the parent widget, so the status is sent up rather than computed there.
watch(
  () => status,
  (current) => emit('status', current),
  { immediate: true },
)

/** Stop the download, which the element goes on doing until its source is taken away. */
function dispose() {
  reconnect.stop()
  mediaSourceRequest?.abort()
  closeWhep()
  if (src?.startsWith('blob:')) {
    URL.revokeObjectURL(src)
  }
  if (element != null) {
    element.pause()
    isDisposed = true
    element.removeAttribute('src')
    element.load()
  }
}

onBeforeUnmount(() => {
  isUnloading = true
  dispose()
})

useEventListener('beforeunload', () => {
  isUnloading = true
  dispose()
})
</script>

<template>
  <!-- Focusable so a click on the picture puts focus in the widget, where space plays and
  pauses. -->
  <div
    ref="container"
    class="bg-elevated relative flex h-full w-full flex-col overflow-hidden outline-none [&:fullscreen]:bg-[#000000]"
    tabindex="-1"
  >
    <video
      key="video"
      ref="element"
      :autoplay="widget.autoplay"
      class="h-full w-full"
      :muted="isMuted"
      playsinline
      :src="src"
      :style="src == null && transport !== 'webrtc' ? { display: 'none' } : {}"
      @emptied="onEmptied"
      @ended="onEnded"
      @error="onError"
      @loadeddata="onFrames"
      @loadedmetadata="onLoad"
      @pause="onPause"
      @play="onPlay"
      @playing="onFrames"
      @waiting="onWaiting"
    />
    <canvas
      v-show="isHoldingFrame"
      ref="lastFrame"
      class="pointer-events-none absolute inset-0 h-full w-full object-contain"
    />
    <c-video-controls
      v-if="
        widget.showControls &&
        element != null &&
        container != null &&
        (src != null || transport === 'webrtc')
      "
      v-model:muted="isMuted"
      :container
      :is-live="isLive"
      :live-state="isLive === true ? (isBehindLive ? 'behind' : 'live') : null"
      :video="element"
      @go-live="goLive()"
      @seek="onSeek()"
    />
    <!-- A frameless widget has no header to carry the status, so it sits over the picture. -->
    <c-widget-status
      v-if="widget.frameless && status != null"
      class="absolute top-2 left-2"
      data-transport
      :status
    />
    <c-icon
      v-if="
        url != null &&
        state !== 'error' &&
        !hasPicture &&
        !isHoldingFrame &&
        !reconnect.isReconnecting &&
        !isUnloading
      "
      class="text-muted pointer-events-none absolute top-1/2 left-1/2 size-7 -translate-x-1/2 -translate-y-1/2 animate-spin opacity-60"
      data-video-loading="first"
      :name="icons.loading"
    />
    <c-icon
      v-else-if="isLoadingMore && !reconnect.isReconnecting && !isUnloading"
      class="pointer-events-none absolute top-2 right-2 size-3.5 animate-spin text-[#ffffff] opacity-60"
      data-video-loading="more"
      :name="icons.loading"
    />
    <div
      v-if="reconnect.isReconnecting && !isUnloading"
      class="bg-default/80 text-muted absolute top-2 right-2 flex items-center gap-1 rounded-md px-2 py-1 text-[11px]"
    >
      <c-icon
        v-if="reconnect.countdown == null"
        class="animate-spin"
        :name="icons.loading"
        size="12"
      />
      <span v-else>Reconnecting in {{ reconnect.countdown }}…</span>
    </div>
    <div
      v-if="state === 'error' && !isUnloading"
      class="bg-default absolute top-1/2 left-1/2 w-max max-w-[min(28rem,90%)] -translate-x-1/2 -translate-y-1/2 rounded-md p-4 text-center"
    >
      <c-text class="text-error mb-2" data-video-error variant="body2">
        {{ unplayable ?? 'An error occurred while loading the video.' }}
      </c-text>
      <c-button
        color="error"
        :icon="icons.refresh"
        label="Reload"
        size="sm"
        @click="emit('reloadRequested')"
      />
    </div>
    <div v-else-if="url == null" class="flex h-full items-center justify-center text-center">
      <c-tooltip text="Choose Video">
        <c-button
          aria-label="Choose Video"
          class="rounded-full"
          color="primary"
          icon="i-mdi-video-plus"
          @click="emit('settingsRequested')"
        />
      </c-tooltip>
    </div>
  </div>
</template>
