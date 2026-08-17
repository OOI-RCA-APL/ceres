<script lang="ts">
/** The strip band's height, its 32px tab row plus the separator beneath it. */
const stripBandHeight = 33

/** Width of the collapse toggle overlaid on the trailing edge, matching the button width in
the styles below. Passed to the slot so the tabs' own picker can sit beside it. */
const stripToggleInset = 34

/** The overview height that rests the strip at the bottom edge, which is where an unsized one
sits. */
export function overviewFillHeight(stickyTop: number): string {
  return `calc(100vh - ${stickyTop + stripBandHeight}px)`
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

/** Toggle the workspace content, easing a step down into it as it appears. Decided before
the write because the model reads stale until the parent flushes it back. */
function toggle() {
  const showing = collapsed
  collapsed = !collapsed
  if (showing) {
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

<!-- Sticky at both edges so the strip never leaves the screen, and pushed to the bottom by the
auto margin when nothing renders beneath it. Raised over the workspace's floating action bar,
which slides under this strip whenever both rest at the bottom edge. -->
<template>
  <div
    ref="element"
    class="sticky bottom-0 z-[5] mt-auto bg-default"
    :style="{ top: `${stickyTop}px` }"
  >
    <!-- The same band the page header gives its tabs, so they fill it to the bottom edge. -->
    <div class="relative flex h-8 flex-nowrap items-center">
      <slot :docked="docked" :trailing-inset="stripToggleInset" />
      <!-- Overlaid on the strip's trailing edge so overgrown tabs scroll under it. -->
      <div class="absolute inset-y-0 right-0 z-[2] flex bg-default">
        <c-tooltip :text="`${collapsed ? 'Show' : 'Hide'} Workspaces`">
          <!-- Follows the collapsed state alone, the same way the "Details" toggle does. -->
          <button
            class="h-full w-[34px] text-muted hover:text-default"
            type="button"
            @click="toggle"
          >
            <c-icon :name="collapsed ? icons.menuUp : icons.menuDown" size="18" />
          </button>
        </c-tooltip>
      </div>
    </div>
    <!-- At the bottom edge there is nothing under the strip for it to separate. -->
    <c-separator :style="{ visibility: docked ? 'hidden' : undefined }" />
  </div>
</template>
