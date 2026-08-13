<script lang="ts">
/** The strip band's height, its 32px tab row plus the separator beneath it. */
export const stripBandHeight = 33

/** Width of the collapse toggle overlaid on the trailing edge, matching the button width in
the styles below. Passed to the slot so the tabs' own picker can sit beside it. */
export const stripToggleInset = 34

/** The overview height that rests the strip at the bottom edge, floored by the dragged
height. */
export function overviewFillHeight(stickyTop: number, dragged: number): string {
  return `max(${dragged}px, calc(100vh - ${stickyTop + stripBandHeight}px))`
}
</script>

<script lang="ts" setup>
import icons from '@/icons'
import { stepIntoWorkspaces, useStripDocked } from '@/tabs'

const { stickyTop } = defineProps<{
  /** Where the strip pins under the page's headers, set as its sticky top offset. */
  stickyTop: number
}>()

/** Whether the workspace content below the strip is hidden, toggled by the overlay button. */
let collapsed = $(defineModel<boolean>('collapsed', { required: true }))

let element = $ref<HTMLElement | null>(null)
const docked = $(useStripDocked(() => element))

/** Toggle the workspace content, easing a step down into it as it appears. */
function toggle() {
  collapsed = !collapsed
  if (!collapsed) {
    void stepIntoWorkspaces()
  }
}

/** Scroll to `top` when the strip is resting at the bottom edge, since a selection there is a
request to see the workspace itself. The content may still be mounting, so the scroll waits
until the page has grown the room to take it, and goes best-effort when nothing appears.
*/
async function scrollToPin(top: number) {
  if (!docked) {
    return
  }

  const deadline = performance.now() + 3000
  while (document.body.scrollHeight < top + window.innerHeight && performance.now() < deadline) {
    await new Promise((resolve) => requestAnimationFrame(resolve))
  }

  window.scrollTo({ top, behavior: 'smooth' })
}

defineExpose({ docked: $$(docked), scrollToPin })
</script>

<template>
  <div ref="element" :class="$style.tabStrip" :style="{ top: `${stickyTop}px` }">
    <!-- The same band the page header gives its tabs, so they fill it to the bottom edge. -->
    <div :class="[$style.tabStripRow, 'items-center', 'no-wrap', 'row']">
      <slot :docked="docked" :trailing-inset="stripToggleInset" />
      <!-- Overlaid on the strip's trailing edge so overgrown tabs scroll under it. -->
      <div :class="$style.stripToggle">
        <!-- Follows the collapsed state alone, the same way the "Details" toggle does. -->
        <q-btn
          dense
          flat
          :icon="collapsed ? icons.menuDown : icons.menuUp"
          size="sm"
          @click="toggle"
        >
          <q-tooltip class="bg-primary text-white">
            {{ collapsed ? 'Show' : 'Hide' }} Workspaces
          </q-tooltip>
        </q-btn>
      </div>
    </div>
    <!-- At the bottom edge there is nothing under the strip for it to separate. -->
    <q-separator :style="{ visibility: docked ? 'hidden' : undefined }" />
  </div>
</template>

<style lang="scss" module>
// Sticky at both edges so the strip never leaves the screen, and pushed to the bottom by the
// auto margin when nothing renders beneath it. Its top offset is set inline from the header
// heights above it. Raised over the workspace's floating action bar, which slides under this
// strip whenever both rest at the bottom edge.
.tabStrip {
  position: sticky;
  bottom: 0;
  z-index: 5;
  margin-top: auto;
}

:global(.dark) .tabStrip {
  background-color: $dark;
}

:global(.light) .tabStrip {
  background-color: #fff;
}

// The band the dense page header gives its own tabs, so these reach its bottom edge.
.tabStripRow {
  position: relative;
  height: 32px;
}

// Overlaid on the trailing edge so tabs that outgrow the strip scroll under it rather than
// pushing it aside.
.stripToggle {
  position: absolute;
  top: 0;
  right: 0;
  bottom: 0;
  z-index: 2;
  display: flex;
}

// Filled to the strip's height so the button reads as part of the bar rather than floating
// on it.
.stripToggle :global(.q-btn) {
  width: 34px;
  height: 100%;
  padding: 0;
  border-radius: 0;
}

:global(.dark) .stripToggle {
  background-color: $dark;
}

:global(.light) .stripToggle {
  background-color: #fff;
}
</style>
