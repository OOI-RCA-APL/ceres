<script lang="ts" setup>
import { useEventListener, useFullscreen, useTimeoutFn } from '@vueuse/core'
import { computed, watchEffect } from 'vue'

import icons from '@/icons'

// Drawn in place of the browser's own controls, which show a spinner over the picture whenever
// playback waits on the network. A live picture over a poor link waits often and briefly, and the
// spinner flashing over it reads as broken when the last frame held still would read as a pause.
const { video, container, isLive, liveState, muted } = defineProps<{
  /** The element played, with its own controls off. */
  video: HTMLVideoElement
  /** What fullscreen fills, so the controls stay over the picture there. */
  container: HTMLElement
  /** Whether the video is live. A recording seeks over its whole length and a live video over what
  it still holds behind the newest frame, while one not yet known to be either gets no bar. */
  isLive: boolean | null
  /** For live video, whether it plays at the newest frame or behind it. */
  liveState: 'live' | 'behind' | null
  muted: boolean
}>()

const emit = defineEmits<{
  'update:muted': [muted: boolean]
  /** The viewer moved the playback position. */
  seek: []
  /** The viewer asked to be taken back to the newest frame. */
  goLive: []
}>()

let isPaused = $ref(video.paused)
let currentTime = $ref(video.currentTime)
/** What can be sought, from the start of the recording or the oldest frame still held. */
let range = $ref<{ start: number; end: number } | null>(null)

/** The span a seek can reach, read anew as playback moves and the buffer grows and is trimmed. */
function readRange() {
  if (isLive === false && Number.isFinite(video.duration) && video.duration > 0) {
    return { start: 0, end: video.duration }
  }

  // A stream played over WebRTC holds nothing to go back to and reports no seekable time.
  // A `MediaSource` of unknown length reports everything from zero as seekable, trimmed or not, so
  // the start is the oldest frame still buffered.
  const { seekable, buffered } = video
  if (isLive === true && seekable.length > 0 && buffered.length > 0) {
    const start = Math.max(seekable.start(0), buffered.start(0))
    const end = Math.min(seekable.end(seekable.length - 1), buffered.end(buffered.length - 1))
    return end > start ? { start, end } : null
  }

  return null
}

useEventListener(
  () => video,
  ['play', 'pause', 'emptied'],
  () => (isPaused = video.paused),
)
useEventListener(
  () => video,
  ['timeupdate', 'durationchange', 'loadedmetadata', 'progress', 'emptied'],
  () => {
    currentTime = video.currentTime
    range = readRange()
  },
)

/** Whether the video carries sound, `null` until that can be told. */
let hasAudio = $ref<boolean | null>(null)

/** Read whether the video has sound from whichever of the browsers' ways to tell this one has. */
function readAudio(): boolean | null {
  const stream = video.srcObject
  if (stream instanceof MediaStream) {
    return stream.getAudioTracks().length > 0
  }
  if (video.readyState < HTMLMediaElement.HAVE_METADATA) {
    return null
  }

  // Not in every browser's types: Safari lists tracks, Firefox says outright, and Chromium only
  // counts the sound it has decoded, which stays zero for the first moments of a video with some.
  const media = video as HTMLVideoElement & {
    audioTracks?: { length: number }
    mozHasAudio?: boolean
    webkitAudioDecodedByteCount?: number
  }
  if (media.audioTracks != null) {
    return media.audioTracks.length > 0
  }
  if (media.mozHasAudio != null) {
    return media.mozHasAudio
  }
  if (media.webkitAudioDecodedByteCount != null) {
    if (media.webkitAudioDecodedByteCount > 0) {
      return true
    }
    const { played } = video
    return played.length > 0 && played.end(played.length - 1) - played.start(0) > 1 ? false : null
  }

  return null
}

useEventListener(
  () => video,
  ['loadedmetadata', 'timeupdate'],
  () => {
    if (hasAudio == null) {
      hasAudio = readAudio()
    }
  },
)
useEventListener(
  () => video,
  'emptied',
  () => (hasAudio = null),
)

const fullscreen = useFullscreen(computed(() => container))

// The controls show while the pointer moves over the picture and fade once it rests, the way a
// video player's do, which also clears them off a fullscreen picture the pointer never leaves.
/** How long a resting pointer keeps the controls up. */
const restingMs = 2000
let isPointerActive = $ref(false)
const rest = useTimeoutFn(() => (isPointerActive = false), restingMs, { immediate: false })

useEventListener(
  () => container,
  'pointermove',
  () => {
    isPointerActive = true
    rest.start()
  },
)
useEventListener(
  () => container,
  'pointerleave',
  () => {
    rest.stop()
    isPointerActive = false
  },
)

const isShown = $computed(() => isPaused || isPointerActive)

// A fullscreen picture also hides the pointer while the controls are away.
watchEffect(() => {
  container.style.cursor = fullscreen.isFullscreen.value && !isShown ? 'none' : ''
})

// White over the dark band at the foot of the picture, whatever the page's own theme.
const buttonClass =
  'text-[#ffffff] hover:bg-[#ffffff26] hover:text-[#ffffff] disabled:bg-transparent disabled:opacity-40'

/** How far a live video plays behind the newest frame it holds, in whole seconds. */
const behind = $computed(() =>
  range == null ? 0 : Math.max(Math.round(range.end - currentTime), 0),
)

function togglePlaying() {
  if (video.paused) {
    video.play().catch((error: unknown) => console.warn('Resuming the video failed.', error))
  } else {
    video.pause()
  }
}

// Space plays and pauses the video while focus is in it or it fills the screen, the way players
// do. It wins over a focused control's own press, so a click on fullscreen then space still pauses
// rather than leaving fullscreen.
useEventListener(document, 'keydown', (event: KeyboardEvent) => {
  const isFocused = container.contains(document.activeElement)
  if (
    event.key !== ' ' ||
    event.altKey ||
    event.ctrlKey ||
    event.metaKey ||
    event.shiftKey ||
    !(isFocused || fullscreen.isFullscreen.value)
  ) {
    return
  }
  event.preventDefault()
  if (!event.repeat) {
    togglePlaying()
  }
})

/** How far along the seek bar the pointer is, from 0 to 1, or `null` while it is off the bar. */
let hoverShare = $ref<number | null>(null)

function onSeekHover(event: PointerEvent) {
  const bounds = (event.currentTarget as HTMLElement).getBoundingClientRect()
  hoverShare = Math.min(Math.max((event.clientX - bounds.left) / bounds.width, 0), 1)
}

function seek(seconds: number | undefined) {
  if (seconds != null) {
    video.currentTime = seconds
    currentTime = seconds
    emit('seek')
  }
}

/** `seconds` as `m:ss`, or `h:mm:ss` from an hour. */
function clock(seconds: number) {
  const whole = Math.max(Math.floor(seconds), 0)
  const hours = Math.floor(whole / 3600)
  const minutes = Math.floor((whole % 3600) / 60)
  const rest = String(whole % 60).padStart(2, '0')
  return hours > 0 ? `${hours}:${String(minutes).padStart(2, '0')}:${rest}` : `${minutes}:${rest}`
}
</script>

<template>
  <!-- Shown while the pointer moves over the video, or while it is paused so the way back is in
  view. The pointer handlers keep a press on a control from starting a widget drag. -->
  <div
    :class="[
      'absolute inset-x-0 bottom-0 flex items-center gap-1 px-2 pt-2 pb-1.5 text-[#ffffff]',
      'bg-linear-to-t from-[#00000099] to-[#00000000] transition-opacity duration-300',
      // Keyboard focus only: a clicked button keeps its focus, which held the controls up for good
      // over a fullscreen picture once its button was pressed.
      'has-[:focus-visible]:opacity-100',
      isShown ? 'opacity-100' : 'opacity-0',
    ]"
    data-video-controls
    @mousedown.stop
    @pointerdown.stop
    @touchstart.stop
  >
    <c-button
      :aria-label="isPaused ? 'Play' : 'Pause'"
      :class="buttonClass"
      color="neutral"
      :icon="isPaused ? icons.start : icons.pause"
      size="xs"
      variant="ghost"
      @click="togglePlaying()"
    />
    <c-button
      :aria-label="hasAudio === false ? 'No Sound' : muted ? 'Unmute' : 'Mute'"
      :class="buttonClass"
      color="neutral"
      :disabled="hasAudio === false"
      :icon="muted || hasAudio === false ? icons.volumeOff : icons.volume"
      size="xs"
      variant="ghost"
      @click="emit('update:muted', !muted)"
    />
    <template v-if="range != null">
      <span v-if="isLive === false" class="text-[11px] tabular-nums">{{ clock(currentTime) }}</span>
      <!-- Thin at rest, and grown under the pointer so it is easy to hit and to drag. The bar up to
      the pointer is lightened, under a track see-through enough to show it, as players mark where
      a click would land. -->
      <div
        class="group/seek relative mx-2 grow cursor-pointer py-1.5"
        @pointerleave="hoverShare = null"
        @pointermove="onSeekHover"
      >
        <div
          v-if="hoverShare != null"
          class="pointer-events-none absolute top-1/2 left-0 h-[2px] -translate-y-1/2 rounded-full bg-[#ffffff59] group-hover/seek:h-1"
          :style="{ width: `${hoverShare * 100}%` }"
        />
        <c-slider
          :max="range.end"
          :min="range.start"
          :model-value="Math.min(Math.max(currentTime, range.start), range.end)"
          size="xs"
          :step="0.1"
          :ui="{
            track: 'h-[2px] bg-[#ffffff33] transition-[height] duration-150 group-hover/seek:h-1',
            thumb:
              'size-1.5 ring-[1.5px] ring-primary transition-[width,height] duration-150 group-hover/seek:size-2.5 group-hover/seek:ring-2',
          }"
          @update:model-value="seek"
        />
      </div>
      <span v-if="isLive === false" class="text-[11px] tabular-nums">{{ clock(range.end) }}</span>
      <span v-else-if="behind > 0" class="text-[11px] tabular-nums opacity-80">
        -{{ clock(behind) }}
      </span>
    </template>
    <div v-else class="grow" />
    <!-- The same mark as the header's, filled at the newest frame and taking the picture back to it
    from anywhere behind. -->
    <button
      v-if="liveState != null"
      :class="[
        'flex items-center gap-1 rounded px-1 text-[11px]',
        liveState === 'behind' && 'opacity-70 hover:opacity-100',
      ]"
      :data-live-state="liveState"
      :disabled="liveState === 'live'"
      :title="liveState === 'behind' ? 'Go to live' : undefined"
      type="button"
      @click="emit('goLive')"
    >
      <span
        :class="[
          'size-1.5 rounded-full border border-current',
          liveState === 'live' && 'bg-current',
        ]"
      />
      Live
    </button>
    <c-button
      v-if="fullscreen.isSupported.value"
      :aria-label="fullscreen.isFullscreen.value ? 'Exit Fullscreen' : 'Fullscreen'"
      :class="buttonClass"
      color="neutral"
      :icon="fullscreen.isFullscreen.value ? icons.fullscreenExit : icons.fullscreen"
      size="xs"
      variant="ghost"
      @click="fullscreen.toggle()"
    />
  </div>
</template>
