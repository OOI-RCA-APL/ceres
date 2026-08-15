<script lang="ts" setup>
import { useEventListener } from '@vueuse/core'
import { onBeforeUnmount, watchEffect } from 'vue'

import { useEngine } from '@/api/engine'
import { isMediaSourceSupported, isSafari } from '@/environment'
import icons from '@/icons'
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

let state = $ref<'loading' | 'error' | 'ok'>('loading')

let isUnloading = $ref(false)
const isMuted = $ref(widget.startMuted)
let isDisposed = false

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
  // when the video element unloads, which leaves an `ffmpeg` process per load running until the
  // proxy restarts.
  return getHttpUrl(`/api/components/${queryComponent}/queries/${queryName}/call`)
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

/** Feed the stream at `url` into a fresh `MediaSource`, for as long as it stays the bound one. */
async function syncMediaSource(url: string | null | undefined) {
  if (url == null) {
    mediaSource = null
    state = 'ok'
    return
  }

  state = 'loading'
  const result = await fetch(url)
  const contentType = result.headers.get('content-type')
  if (contentType == null) {
    console.error('Failed to get video content type from response headers.')
    state = 'error'
    return
  }

  const bufferType = mediaSourceBufferType(contentType)
  if (bufferType == null) {
    console.error(`Unsupported video content type: "${contentType}"`)
    state = 'error'
    return
  }

  const reader = result.body?.getReader()
  if (reader == null) {
    console.error('No data in response.')
    state = 'error'
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
  } finally {
    // Without this the request runs until the tab closes or the server hangs up, leaving stray
    // `ffmpeg` processes behind.
    await reader.cancel()
  }
}

watchEffect(() => {
  if (isUsingMediaSourceBuffer) {
    void syncMediaSource(url)
  }
})

function onError() {
  state = 'error'
}

async function onLoad() {
  if (element != null && widget.autoplay) {
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
}

/** Stop the download, which the element goes on doing until its source is taken away. */
function dispose() {
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
      @error="onError"
      @loadedmetadata="onLoad"
      @play="onPlay"
    />
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
