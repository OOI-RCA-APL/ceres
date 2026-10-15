<script lang="ts" setup>
import { useEventListener, useIntervalFn } from '@vueuse/core'
import { onBeforeUnmount, watch, watchEffect } from 'vue'

import { useEngine } from '@/api/engine'
import { isMediaSourceSupported } from '@/environment'
import icons from '@/icons'
import { readInitSegment } from '@/mp4'
import { useReconnectSchedule } from '@/reconnect'
import { getHttpUrl } from '@/utilities'
import {
  openWhep,
  permanent,
  useVideoTransports,
  type VideoTransport,
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

let state = $ref<'loading' | 'error' | 'ok'>('loading')

let isUnloading = $ref(false)
const isMuted = $ref(widget.startMuted)
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

// A streaming query may read a camera the engine can send over WebRTC, which is tried first.
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
  const path = `/api/components/${queryComponent}/procedures/${queryName}/whep`
  return new URL(path, window.location.href).toString()
})

const transports = useVideoTransports()
// `null` while the first try over WebRTC decides between the two.
let transport = $ref<VideoTransport | null>(null)

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
// camera nor whether the stream is live can be told. A file plays directly, finished and rangeable,
// and so does a stream a `MediaSource` cannot take.
const isUsingMediaSourceBuffer = $computed(
  () => transport === 'http' && isStreamingOutput && isMediaSourceSupported && !isPlayingDirectly,
)

// The duration a `MediaSource` reported once its metadata loaded, `null` before then.
let bufferedDuration = $ref<number | null>(null)

// Whether the video is live rather than a recording, `null` while that is not known. A live stream
// has no end, so the media itself reports an infinite duration. Only a `MediaSource` reports the
// container's own, where an element playing a URL directly estimates one from the bytes so far and
// so calls a live stream finite.
const isLive = $computed(() => {
  if (queryInfo?.output.type === 'file') {
    return false
  }
  if (transport === 'webrtc') {
    return true
  }
  if (!isUsingMediaSourceBuffer || bufferedDuration == null) {
    return null
  }

  return bufferedDuration === Infinity
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

/** The buffer type for a stream, read from its init segment for MP4, or `null` when the browser's
`MediaSource` cannot take it. `head` is `null` while more of the stream is needed to tell. */
function mediaSourceBufferType(contentType: string, head: Uint8Array) {
  const mediaType = contentType.split(';')[0]!.trim()
  let bufferType = contentType
  if (mediaType === 'video/mp4' && !contentType.includes('codecs=')) {
    const segment = readInitSegment(head)
    if (segment.type === 'partial') {
      return undefined
    }
    if (segment.type === 'unknown') {
      return null
    }
    bufferType = `video/mp4; codecs="${segment.codecs}"`
  }

  return MediaSource.isTypeSupported(bufferType) ? bufferType : null
}

// How much already played video the `MediaSource` keeps, enough for a short seek back. Chromium
// gives a page about 150 MB of buffer, which a few 1080p streams at half a minute each would fill.
const KEPT_SECONDS = 10

// The request feeding the current `MediaSource`, aborted when a newer one replaces it.
let mediaSourceRequest: AbortController | null = null

/** Feed the stream at `url` into a fresh `MediaSource`, for as long as it stays the bound one. */
async function syncMediaSource(url: string | null | undefined) {
  mediaSourceRequest?.abort()
  mediaSourceRequest = null
  bufferedDuration = null

  if (url == null) {
    mediaSource = null
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
      playDirectly(`This browser cannot buffer "${contentType}" itself.`)
      return
    }

    const boundMediaSource = new MediaSource()
    mediaSource = boundMediaSource

    const once = { once: true, passive: true }
    await new Promise((resolve) => boundMediaSource.addEventListener('sourceopen', resolve, once))

    const buffer = boundMediaSource.addSourceBuffer(bufferType)
    let pending: Uint8Array<ArrayBuffer> | null = head
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
      const playedUntil = (element?.currentTime ?? 0) - KEPT_SECONDS
      if (
        isLive !== false &&
        buffer.buffered.length > 0 &&
        buffer.buffered.start(0) < playedUntil
      ) {
        buffer.remove(buffer.buffered.start(0), playedUntil)
        await new Promise((resolve) => buffer.addEventListener('updateend', resolve, once))
      }

      try {
        buffer.appendBuffer(chunk)
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
  if (element != null) {
    element.srcObject = null
  }
}

/** Play the camera at `target` over WebRTC, or settle on HTTP when a first try cannot. */
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
    transport = 'webrtc'
    if (widget.transport === 'auto') {
      transports.remember(target, 'webrtc')
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
      fail(`WebRTC failed. ${String(error)}`)
      return
    }

    if (transport === 'webrtc') {
      // The network carried WebRTC before, so a drop is a lost camera rather than a blocked path.
      fail(`WebRTC did not reconnect. ${String(error)}`)
      return
    }

    console.info(`Playing ${target} over HTTP. ${String(error)}`)
    transport = 'http'
    if (permanent(error)) {
      transports.remember(target, 'http')
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

function onError() {
  // A stream refused before its first metadata is one the buffer cannot take, such as an MP4 with
  // its index at the end, which the element can still play from the URL.
  if (isUsingMediaSourceBuffer && bufferedDuration == null) {
    playDirectly(`The buffer refused the stream. ${element?.error?.message ?? ''}`)
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

  fail('The video stream ended.')
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
  reconnect.recovered()
}

// A playing video that shows no new frame for this long has lost its stream without saying so.
// Frames are counted rather than time, which a WebRTC stream's clock keeps running without them.
const STALL_SECONDS = 10
let lastFrames = -1
let stillFor = 0

// Only watched while in sight, since browsers pause or starve video in a hidden tab. A recording
// standing still is only waiting on its download.
useIntervalFn(() => {
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

  const frames = element.getVideoPlaybackQuality().totalVideoFrames
  if (frames !== lastFrames) {
    lastFrames = frames
    stillFor = 0
    return
  }

  stillFor += 1
  if (stillFor >= STALL_SECONDS) {
    stillFor = 0
    fail(`No new frames for ${STALL_SECONDS} seconds.`)
  }
}, 1000)

// Every time playback waits on the network the picture falls that much further behind, and the
// element never makes the time up, so a live view left open drifts minutes behind the camera.
// A lagging video plays a little fast until it is back near the newest frame, which nobody
// watching a camera notices, and only a lag too long to play off that way is jumped.
/** How far short of the newest frame playback is steered, so the next fragment is there in time. */
const TARGET_LAG_SECONDS = 0.5
/** The lag past the target that starts a catch-up, so a passing hiccup does not. */
const CATCH_UP_AFTER_SECONDS = 0.5
/** The catch-up's speed, closing a second of lag in ten without motion looking hurried. */
const CATCH_UP_RATE = 1.1
/** A lag past this would take most of half a minute to play off, so it is jumped instead. */
const MAX_LAG_SECONDS = 3

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

useIntervalFn(() => {
  if (element == null || isLive !== true) {
    isBehindLive = false
    stopCatchingUp()
    return
  }

  if (element.paused) {
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
  const live = newest - TARGET_LAG_SECONDS
  // Trimming can leave playback behind what is still buffered, where it would wait forever.
  const isBeforeBuffer = element.currentTime < buffered.start(0)
  // A jump to a time that cannot be sought lands back at the start.
  const canJump = [...Array(seekable.length).keys()].some(
    (index) => seekable.start(index) <= live && live <= seekable.end(index),
  )
  isBehindLive = lag > TARGET_LAG_SECONDS + CATCH_UP_AFTER_SECONDS
  if ((lag > MAX_LAG_SECONDS || isBeforeBuffer) && canJump) {
    element.currentTime = live
    stopCatchingUp()
  } else if (lag > TARGET_LAG_SECONDS + CATCH_UP_AFTER_SECONDS) {
    element.playbackRate = CATCH_UP_RATE
    isCatchingUp = true
  } else if (lag <= TARGET_LAG_SECONDS) {
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
    isHoldingFrame = false
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
      // No retry could change that, so this skips the reconnecting that `fail` would start.
      transport = null
      reconnect.stop()
      console.warn(`The video at ${url} cannot play over WebRTC.`)
      state = 'error'
      return
    }

    if (target == null || forced === 'http') {
      transport = 'http'
      return
    }

    // A forced transport neither reads nor writes what an automatic choice remembers.
    transport = forced === 'auto' ? transports.verdict(target) : null
    if (transport !== 'http' && !isDisposed) {
      void playWhep(target)
    }
  },
  { immediate: true },
)

/** The transport in use, named so a fallback to HTTP is visible. */
const transportLabel = $computed(() => {
  if (transport == null || url == null) {
    return null
  }

  return transport === 'webrtc' ? 'WebRTC' : 'HTTP'
})

/** Play live video from its newest frame, resuming it if paused. */
function goLive() {
  if (element == null) {
    return
  }

  const { buffered } = element
  if (transport === 'http' && buffered.length > 0) {
    element.currentTime = buffered.end(buffered.length - 1) - TARGET_LAG_SECONDS
  }
  isMeantToPlay = true
  element.play().catch((error) => console.warn('Resuming the video failed.', error))
}

const status = $computed((): WidgetStatus | null => {
  if (transportLabel == null) {
    return null
  }

  return isLive === true
    ? { text: transportLabel, live: isBehindLive ? 'behind' : 'live', goLive }
    : { text: transportLabel }
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
  <div class="bg-elevated relative flex h-full w-full flex-col overflow-hidden">
    <video
      key="video"
      ref="element"
      :autoplay="widget.autoplay"
      class="h-full w-full"
      :controls="widget.showControls"
      :muted="isMuted"
      playsinline
      :src="src"
      :style="src == null && transport !== 'webrtc' ? { display: 'none' } : {}"
      @ended="onEnded"
      @error="onError"
      @loadeddata="onFrames"
      @loadedmetadata="onLoad"
      @pause="onPause"
      @play="onPlay"
      @playing="onFrames"
    />
    <canvas
      v-show="isHoldingFrame"
      ref="lastFrame"
      class="pointer-events-none absolute inset-0 h-full w-full object-contain"
    />
    <!-- A frameless widget has no header to carry the status, so it sits over the picture. -->
    <c-widget-status
      v-if="widget.frameless && status != null"
      class="absolute top-2 left-2"
      data-transport
      :status
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
      class="bg-default absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 rounded-md p-4 text-center"
    >
      <c-text class="text-error mb-2" variant="body2">
        An error occurred while loading the video.
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
