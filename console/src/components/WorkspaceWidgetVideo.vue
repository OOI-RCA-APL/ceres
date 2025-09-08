<script lang="ts"></script>

<script lang="ts" setup>
import { useEventListener } from '@vueuse/core'
import { onBeforeUnmount, watchEffect } from 'vue'

import { useEngine } from '@/api/engine'
import { isMediaSourceSupported, isSafari } from '@/environment'
import icons from '@/icons'
import { getHttpUrl } from '@/utilities'
import { VideoWidget } from '@/workspace'

const { widget } = defineProps<{
  widget: VideoWidget
}>()

defineEmits(['reload-requested', 'settings-requested'])

const engine = useEngine()

const element = $ref<HTMLVideoElement>()

let state = $ref<'loading' | 'error' | 'ok'>('loading')

let isUnloading = $ref(false)
let isMuted = $ref(widget.startMuted)
let isDisposed = false

const queryComponent = $computed(() => widget.query?.split('::')?.[0] ?? null)
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

// API URL we video data will be streamed from.
const url = $computed(() => {
  if (queryComponent == null || queryName == null || isDisposed) {
    return undefined
  }

  // We need to use this in development to ensure the video is requested directly through the real
  // API and not through the Vite dev server proxy. The proxy will NOT cancel the HTTP request when
  // the video element is unloaded, and as such the video will continue to download until the proxy
  // is restarted, leading to a bunch of duplicate `ffmpeg` processes being created on your machine
  // which are never stopped, and Jakey here going absolutely insane over the course of two days
  // trying to figure out why.
  return getHttpUrl(`/api/components/${queryComponent}/queries/${queryName}/call`)
})

// Use a `MediaSource` to stream the video data directly from the server if we're running in Safari
// and the query outputs a data stream. Apple had to go ahead and think different and require video
// streaming responses to support byte range requests which don't really make sense when you're live
// streaming video. So we're downloading the video ourselves and appending it to the `SourceBuffer`
// of a `MediaSource` which we bind to the `video` element. Pretty cool. Really wish we didn't have
// to do this.
const isUsingMediaSourceBuffer = $computed(
  () => isStreamingOutput && isSafari && isMediaSourceSupported
)

// Log which method we're using for video playback.
watchEffect(() => {
  if (url && isUsingMediaSourceBuffer) {
    console.log(`Using media source buffer for video playback of "${url}".`)
  } else {
    console.log(`Using standard video "src" URL for video playback of "${url}".`)
  }
})

let mediaSource: MediaSource | null = $shallowRef(null)

// Passed to the `video` element's `src` attribute.
const src = $computed(() => {
  if (isDisposed) {
    return undefined
  }

  // If we're using a media source buffer to store video data, once the media source loads, the
  // video's `src` will be set to its object URL.
  if (isUsingMediaSourceBuffer) {
    if (mediaSource == null) {
      return undefined
    }

    return URL.createObjectURL(mediaSource)
  }

  return url
})

// Sync and live update the media source with data from the given `url`. If the `url` is null or
// undefined, the media source will be cleared. Only used when using media source buffers.
async function syncMediaSource(url: string | null | undefined) {
  if (url == null) {
    mediaSource = null
    state = 'ok'
    return
  }

  // Determine the `type` to pass to the current source buffer based on the `Content-Type` header of
  // the HTTP response.
  function getMediaSourceBufferType(contentType: string) {
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

    if (!MediaSource.isTypeSupported(bufferType)) {
      return null
    }

    return bufferType
  }

  state = 'loading'
  const result = await fetch(url)
  const contentType = result.headers.get('content-type')
  if (contentType == null) {
    console.error('Failed to get video content type from response headers.')
    state = 'error'
    return
  }

  const bufferType = getMediaSourceBufferType(contentType)
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

  const boundMediaSource = new MediaSource()
  mediaSource = boundMediaSource

  // Event listener options.
  const once = { once: true, passive: true }
  // Wait for the media source to open.
  await new Promise((resolve) => boundMediaSource.addEventListener('sourceopen', resolve, once))

  // Create a new source buffer.
  const buffer = boundMediaSource.addSourceBuffer(bufferType)
  // If the destination media source has changed we should exit.
  while (boundMediaSource === mediaSource && element?.src === src) {
    // Wait for the next chunk of video data.
    const { value: chunk } = await reader.read()
    // If the chunk is null, the stream has ended.
    if (chunk == null) {
      break
    }

    // Append the latest video data to the buffer.
    try {
      buffer.appendBuffer(chunk)
    } catch {
      // If this fails, the `src` has probably changed, causing the media source to be detached.
      // When this happens, stop downloading.
      break
    }

    // Wait for the append operation to complete before continuing.
    await new Promise((resolve) => buffer.addEventListener('updateend', resolve, once))
  }
}

// If using media source buffers, sync video data whenever the input `url` changes.
watchEffect(() => {
  if (isUsingMediaSourceBuffer) {
    syncMediaSource(url)
  }
})

async function onError() {
  state = 'error'
}

async function onLoad() {
  if (element != null && widget.autoplay) {
    try {
      // Run autoplay ourselves, if possible.
      await element.play()
      state = 'ok'
    } catch (error) {
      console.warn('Autoplay failed.', error)
    }
  }
}

async function onPlay() {
  state = 'ok'
}

/// Ensure the video element stops downloading when removed from the DOM.
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
  <div :class="[$style.root, 'relative-position column full-height full-width']">
    <video
      key="video"
      ref="element"
      :autoplay="widget.autoplay"
      class="full-height full-width"
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
      :class="[$style.error, 'absolute-center q-pa-md text-center']"
    >
      <div class="q-mb-sm text-body2 text-negative">An error occurred while loading the video.</div>
      <q-btn
        color="negative"
        :icon="icons.refresh"
        label="Reload"
        size="sm"
        unelevated
        @click="$emit('reload-requested')"
      />
    </div>
    <div v-else-if="url == null" class="full-height items-center justify-center row text-center">
      <q-btn color="primary" icon="mdi-video-plus" round @click="$emit('settings-requested')">
        <q-tooltip class="bg-primary text-white">Choose Video</q-tooltip>
      </q-btn>
    </div>
  </div>
</template>

<style module lang="scss">
.root {
  overflow: hidden;
}

:global(.light) .root {
  background-color: $grey-4 !important;
}

:global(.dark) .root {
  background-color: $dark !important;
}

.error {
  border-radius: 3px;
}

:global(.light) .error {
  background-color: white;
}

:global(.dark) .error {
  background-color: $dark;
}
</style>
