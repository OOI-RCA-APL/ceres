<script lang="ts" setup>
import { useEventListener, useIntervalFn } from '@vueuse/core'
import { onBeforeUnmount, watch, watchEffect } from 'vue'

import { useEngine } from '@/api/engine'
import { isMediaSourceSupported, isSafari } from '@/environment'
import icons from '@/icons'
import { useReconnectSchedule } from '@/reconnect'
import { getHttpUrl } from '@/utilities'
import { useWorkspace } from '@/workspace'
import type { VideoWidget } from '@/workspace'

const { widget } = defineProps<{
  widget: VideoWidget
}>()

const emit = defineEmits<{
  reloadRequested: []
  settingsRequested: []
}>()

const engine = useEngine()
const workspace = useWorkspace()

const element = $ref<HTMLVideoElement | null>(null)
const lastFrame = $ref<HTMLCanvasElement | null>(null)

let state = $ref<'loading' | 'error' | 'ok'>('loading')

let isUnloading = $ref(false)
const isMuted = $ref(widget.startMuted)
let isDisposed = false

// Bumped for each reconnect attempt and sent along as a query parameter, so the element loads the
// stream anew rather than settling for what it already has.
let attempt = $ref(0)
// Whether the last frame is held up over the element while a new connection comes up.
let isHoldingFrame = $ref(false)
// Whether the video should be moving, so that a picture standing still means it was lost. A pause
// the viewer asked for clears it.
let isMeantToPlay = $ref(false)
// Whether a pause or reload in flight is the widget's own doing rather than the viewer's.
let isReloading = false

// The query field encodes a component address as `@component::queries::name` (or a relative
// address in place of `@component` inside a scoped workspace). Only the leading address portion
// resolves through the scope, the rest names a query on that component.
const queryComponent = $computed(() => {
  const raw = widget.query?.split('::')?.[0]
  if (raw == null || raw === '') {
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

const url = $computed(() => {
  if (queryComponent == null || queryName == null || isDisposed) {
    return undefined
  }

  // Absolute so the request goes straight to the engine. The dev proxy does not cancel a request
  // when the video element unloads, so the engine keeps streaming to it until the proxy restarts.
  const path = `/api/components/${queryComponent}/queries/${queryName}/call`
  return getHttpUrl(attempt === 0 ? path : `${path}?attempt=${attempt}`)
})

// Safari requires byte range support on a video response, which a live stream cannot offer, so
// there the stream is downloaded and fed to a `MediaSource` instead.
const isUsingMediaSourceBuffer = $computed(
  () => isStreamingOutput && isSafari && isMediaSourceSupported,
)

let mediaSource: MediaSource | null = $shallowRef(null)

const src = $computed(() => {
  if (isDisposed) {
    return undefined
  }

  if (isUsingMediaSourceBuffer) {
    return mediaSource == null ? undefined : URL.createObjectURL(mediaSource)
  }

  return url
})

/** The buffer type for a response's content type, or null when the browser cannot play it. */
function mediaSourceBufferType(contentType: string) {
  let bufferType: string
  switch (contentType) {
    case 'video/mp4':
      bufferType = 'video/mp4; codecs="avc1.42E01E, mp4a.40.2"'
      break
    case 'video/webm':
      bufferType = 'video/webm'
      break
    default:
      bufferType = contentType
      break
  }

  return MediaSource.isTypeSupported(bufferType) ? bufferType : null
}

// The request feeding the current `MediaSource`, aborted when a newer one replaces it.
let mediaSourceRequest: AbortController | null = null

/** Feed the stream at `url` into a fresh `MediaSource`, for as long as it stays the bound one. */
async function syncMediaSource(url: string | null | undefined) {
  mediaSourceRequest?.abort()
  mediaSourceRequest = null

  if (url == null) {
    mediaSource = null
    state = 'ok'
    return
  }

  const request = new AbortController()
  mediaSourceRequest = request
  state = 'loading'

  let result: Response
  try {
    result = await fetch(url, { signal: request.signal })
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

  const bufferType = mediaSourceBufferType(contentType)
  if (bufferType == null) {
    fail(`Unsupported video content type: "${contentType}"`)
    return
  }

  const reader = result.body?.getReader()
  if (reader == null) {
    fail('No data in response.')
    return
  }

  try {
    const boundMediaSource = new MediaSource()
    mediaSource = boundMediaSource

    const once = { once: true, passive: true }
    await new Promise((resolve) => boundMediaSource.addEventListener('sourceopen', resolve, once))

    const buffer = boundMediaSource.addSourceBuffer(bufferType)
    while (boundMediaSource === mediaSource && element?.src === src) {
      const { value: chunk } = await reader.read()
      if (chunk == null) {
        // The engine ended the stream, which a live view counts as losing it.
        if (boundMediaSource === mediaSource) {
          fail('The video stream ended.')
        }
        break
      }

      // A failure here means the `src` changed and detached the media source, so stop reading.
      try {
        buffer.appendBuffer(chunk)
      } catch {
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

const reconnect = useReconnectSchedule(() => {
  holdLastFrame()
  isReloading = true
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
  console.warn(
    `Lost the video at ${url} (attempt ${attempt}). ${reason}`,
    error != null ? { code: error.code, message: error.message } : '',
  )

  if (widget.reconnect && url != null) {
    reconnect.lost()
  } else {
    state = 'error'
  }
}

function onError() {
  fail('The video element reported an error.')
}

function onEnded() {
  fail('The video stream ended.')
}

async function onLoad() {
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
  if (!isReloading && !isDisposed) {
    isMeantToPlay = false
  }
}

/** Frames are arriving again, so whatever reconnecting there was is over. The first frame of a
paused video counts too, so a paused widget does not retry a connection that already came back. */
function onFrames() {
  isReloading = false
  isHoldingFrame = false
  reconnect.recovered()
}

// A playing video whose time stands still for this long has lost its stream without saying so.
const STALL_SECONDS = 10
let lastTime = -1
let stillFor = 0

// Only watched while in sight, since browsers pause or starve video in a hidden tab.
useIntervalFn(() => {
  const isWatching =
    widget.reconnect &&
    element != null &&
    !element.paused &&
    isMeantToPlay &&
    reconnect.countdown == null &&
    document.visibilityState === 'visible'
  if (!isWatching) {
    stillFor = 0
    return
  }

  if (element.currentTime !== lastTime) {
    lastTime = element.currentTime
    stillFor = 0
    return
  }

  stillFor += 1
  if (stillFor >= STALL_SECONDS) {
    stillFor = 0
    fail(`No new frames for ${STALL_SECONDS} seconds.`)
  }
}, 1000)

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

// A new query starts over, from a first attempt with nothing held.
watch(
  () => widget.query,
  () => {
    reconnect.recovered()
    attempt = 0
    isHoldingFrame = false
    state = 'loading'
    if (widget.reconnect && widget.autoplay) {
      reconnect.begin()
    }
  },
)

/** Stop the download, which the element goes on doing until its source is taken away. */
function dispose() {
  reconnect.stop()
  mediaSourceRequest?.abort()
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
      :style="src == null ? { display: 'none' } : {}"
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
