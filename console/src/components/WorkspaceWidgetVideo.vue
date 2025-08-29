<script lang="ts" setup>
import { useEventListener } from '@vueuse/core'
import { onBeforeUnmount } from 'vue'

import icons from '@/icons'
import { getHttpUrl } from '@/utilities'
import { VideoWidget } from '@/workspace'

const { widget } = defineProps<{
  widget: VideoWidget
}>()

defineEmits(['reload-requested', 'settings-requested'])

const element = $ref<HTMLVideoElement>()

let state = $ref<'loading' | 'error' | 'ok'>('loading')

let isUnloading = $ref(false)
let isMuted = $ref(widget.startMuted)
let isDisposed = false

const queryComponent = $computed(() => widget.query?.split('::')?.[0] ?? null)
const queryName = $computed(() => widget.query?.split('::')?.[2] ?? null)
const src = $computed(() => {
  if (queryComponent == null || queryName == null || isDisposed) {
    return ''
  }

  // We need to use this in development to ensure the video is requested directly through the real
  // API and not through the Vite dev server proxy. The proxy will NOT cancel the HTTP request when
  // the video element is unloaded, and as such the video will continue to download until the proxy
  // is restarted, leading to a bunch of duplicate `ffmpeg` processes being created on your machine
  // which are never stopped, and Jakey here going absolutely insane over the course of two days
  // trying to figure out why.
  return getHttpUrl(`/api/components/${queryComponent}/queries/${queryName}/call`)
})

// const agent = navigator.userAgent.toLowerCase()
// const isSafari = agent.includes('safari') && !agent.includes('chrome')
const isSafari = /^((?!chrome|android).)*safari/i.test(navigator.userAgent)

function onError() {
  console.error(src)
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

async function onPlay() {
  state = 'ok'
}

/// Ensure the video element stops downloading when removed from the DOM.
function dispose() {
  if (element != null) {
    element.pause()
    isDisposed = true
    element.src = ''
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
      @error="onError"
      @loadedmetadata="onLoad"
      @play="onPlay"
    />
    <div v-if="isSafari && state != 'ok'">
      <div class="absolute-top-left full-width q-pa-md text-center">
        <div class="text-body2 text-negative">
          Video playback is not supported in Safari-based browsers.
        </div>
      </div>
    </div>
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
    <div v-else-if="src === ''" class="full-height items-center justify-center row text-center">
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

.video {
  object-fit: contain;
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
