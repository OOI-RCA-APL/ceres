<script lang="ts" setup>
import { useResizeObserver } from '@vueuse/core'
import { watch } from 'vue'

import CComponentWorkspaceStrip, {
  overviewFillHeight,
} from '@/components/c-component-workspace-strip.vue'
import { appHeaderHeight, pageHeaderHeight } from '@/components/c-full-page.vue'
import CWorkspace from '@/components/c-workspace.vue'
import { useNavigation } from '@/navigation'
import { peekAt, useScrollMemory } from '@/scroll'
import { useLastWorkspace, useRequestedWorkspaces, useTabs } from '@/tabs'
import type { Workspace } from '@/workspace'

const {
  placement,
  workspaces,
  openable,
  adoptable,
  canCreate = false,
  canManage = false,
  bound = false,
  showPlacement = false,
  resizable = true,
  refresh = null,
} = defineProps<{
  /** The address the strip's tabs are kept under, and the scroll memory's key. */
  placement: string

  /** The workspaces on the strip, resolved by the hosting page. */
  workspaces: Workspace[]

  /** Workspaces not on the strip that the add button offers. */
  openable: Workspace[]

  /** The workspaces an address request may open. Empty means the page's list has not landed
  yet, and a request waits rather than writing a tab that resolves to nothing. */
  adoptable: Workspace[]

  canCreate?: boolean
  canManage?: boolean

  /** Forwarded to the tabs, which draw a bound strip differently. */
  bound?: boolean

  /** Whether each tab names where its workspace came from, for a strip spanning several
  placements. */
  showPlacement?: boolean

  /** Whether the overview keeps a dragged height. A page whose overview reflows to one column
  turns this off so the drag never clips it mid-item. */
  resizable?: boolean

  /** Refetches the page's placed workspaces, awaited before a copy joins the strip so the
  strip can resolve it. Pages whose lists follow the store need none. */
  refresh?: (() => Promise<void>) | null
}>()

const emit = defineEmits<{
  create: []
  import: [files: File[]]
  share: [ids: string[]]
}>()

/** Whether the overview shows at all, toggled from the page header. */
let overviewCollapsed = $(defineModel<boolean>('overviewCollapsed', { default: false }))

/** The overview's dragged height, null while it still sizes to the fill. */
let overviewSize = $(defineModel<number | null>('overviewSize', { default: null }))

/** Whether workspace content below the strip is hidden. */
let workspaceCollapsed = $(defineModel<boolean>('workspaceCollapsed', { default: false }))

const navigation = useNavigation()
const tabs = useTabs()

// The tab strip pins under the page's own header so scrolling the overview away leaves the
// tabs directly beneath it.
const workspaceStickyTop = appHeaderHeight + pageHeaderHeight

const lastWorkspace = useLastWorkspace(() => placement)

// Held here rather than read from the address. The address asks for a workspace and is cleared
// once it has been given one so what is showing is this host's own state from then on.
let activeWorkspaceId = $ref<string | null>(null)

// What the address is currently asking for, which the fallback below waits for rather than
// choosing a workspace that is about to be replaced.
const requested = useRequestedWorkspaces(navigation.router)
const requestedIds = $computed(() => requested.workspace)

let overviewElement = $ref<HTMLElement | null>(null)

// Unsized, the overview reaches to where the strip rests on the bottom edge. Dragged, it is
// that height exactly, so shortening it takes effect rather than being floored back to the
// fill.
const overviewHeightStyle = $computed(() => ({
  height: overviewSize != null ? `${overviewSize}px` : overviewFillHeight(workspaceStickyTop),
}))

// What a drag starts from while the overview is still unsized, read off the box rather than
// recomputed, so the first move carries on from the height already on screen.
let overviewMeasuredHeight = $ref(0)
useResizeObserver($$(overviewElement), ([entry]) => {
  if (entry != null) {
    overviewMeasuredHeight = entry.contentRect.height
  }
})

// Zero until the box has been measured, and the handle waits for a real size rather than
// mounting on that and storing the minimum it clamps up to.
const overviewDragSize = $computed(() => overviewSize ?? overviewMeasuredHeight)

// Whether the dragged height applies, which is also when the handle shows.
const sized = $computed(() => activeWorkspaceId != null && !workspaceCollapsed && resizable)

/** How far the page must be scrolled for the tab strip to have pinned under the header.

Measured from the overview, which sits above the strip and is never itself pinned, so its box
is reliable. The strip's own box stops moving once it pins. With no overview showing, the strip
is at the top from the start and there is nothing to scroll past.
*/
function pinnedAt(): number {
  if (overviewCollapsed || overviewElement == null) {
    return 0
  }

  const bottom = overviewElement.getBoundingClientRect().bottom + window.scrollY
  return Math.max(0, bottom - workspaceStickyTop)
}

/** Whether moving the page on a tab switch would be welcome.

With the overview showing and the page still above the pin, the overview is what is being read,
so jumping to wherever another workspace was left moves all of that out from under. Past the
pin the overview is out of view and the page is the workspace, which is when returning to where
it was left is the helpful thing.
*/
function isScrollSettled(): boolean {
  return window.scrollY >= pinnedAt()
}

// Switching tabs returns to where each workspace was left, the way switching browser tabs
// does, and never above the pin so a strip that was stuck to the header stays exactly where it
// was rather than dropping back down the page.
useScrollMemory(
  () => (activeWorkspaceId == null ? null : `${placement}/${activeWorkspaceId}`),
  isScrollSettled,
  pinnedAt,
)

// Whatever is showing is what the page reopens on so it is recorded here rather than at each
// of the places that can choose one.
function showWorkspace(id: string) {
  activeWorkspaceId = id
  lastWorkspace.id = id
}

// Followed reactively so the floating action bar can yield while the strip rests at the
// bottom edge.
let stripRef = $ref<InstanceType<typeof CComponentWorkspaceStrip> | null>(null)
const stripDocked = $computed(() => stripRef?.docked ?? false)

// Reached for the tab strip's active workspace actions and state, and exposed so a page can
// land widgets on the open workspace's live working copy.
let workspaceRef = $ref<InstanceType<typeof CWorkspace> | null>(null)

/** Show a workspace the user explicitly chose, bringing hidden content back and scrolling to
it when the strip is stuck at the bottom edge. The fallback selections after a close keep to
`showWorkspace` so a context menu action or a drag never unhides anything. */
function reveal(id: string) {
  workspaceCollapsed = false
  showWorkspace(id)
  if (stripRef == null) {
    return
  }

  // Resting at the bottom edge, the workspace is still below the fold and a peek is enough to
  // show it has opened. Anywhere else the strip is already up the page and the choice is a
  // request to see the workspace itself.
  const target = stripRef.docked ? peekAt(workspaceTop(), pinnedAt()) : pinnedAt()
  if (window.scrollY < target) {
    void stripRef.scrollTo(target)
  }
}

/** Where the workspace starts, which is directly under the strip.

Derived from the overview rather than read off the strip, whose own box stops describing its
place in the page the moment it sticks to either edge.
*/
function workspaceTop(): number {
  if (overviewElement == null) {
    return 0
  }

  const bottom = overviewElement.getBoundingClientRect().bottom + window.scrollY
  return bottom + (stripRef?.element?.getBoundingClientRect().height ?? 0)
}

/** Show a workspace picked from the page's own list, peeking it into view.

Only ever downwards. Past the pin the workspace is already what fills the screen, and
scrolling back to the pin from there would carry off whatever the user had scrolled to.
*/
function openListed(id: string) {
  workspaceCollapsed = false
  showWorkspace(id)
  if (!isScrollSettled()) {
    void stripRef?.scrollTo(peekAt(workspaceTop(), pinnedAt()))
  }
}

async function open(id: string) {
  await tabs.open(placement, id)
  reveal(id)
}

// A copy belongs next to its original so the strip reads as the original followed by its copy.
async function openBeside(afterId: string, id: string) {
  await refresh?.()
  await tabs.openBeside(
    placement,
    id,
    afterId,
    workspaces.map((workspace) => workspace.id),
  )
  reveal(id)
}

/** Give the address what it asked for, then take the request back out of it.

Workspaces named there join the strip if they were not already on it so a link behaves the same
as opening them from the strip itself, and the first of them is what ends up showing. Only what
`adoptable` carries can join, and nothing is done until that list has landed since a link can
arrive before it does.
*/
async function adoptRequested() {
  if (requestedIds.length === 0) {
    return
  }

  const known = new Set(adoptable.map((workspace) => workspace.id))
  const opening = requestedIds.filter((id) => known.has(id))
  if (opening.length === 0 && adoptable.length === 0) {
    return
  }

  // Only this host's own request is taken back out, leaving whatever else the bar carries.
  requested.workspace = []
  if (opening.length === 0) {
    return
  }

  await tabs.openMany(placement, opening)
  showWorkspace(opening[0] as string)
}

// Closing moves to whichever tab takes the closed one's place, or to nothing when it was the
// last one. The workspace itself is untouched, which separates closing from deleting.
async function close(id: string) {
  const remaining = workspaces.filter((workspace) => workspace.id !== id)
  await tabs.close(placement, id)

  if (activeWorkspaceId !== id) {
    return
  }

  activeWorkspaceId = remaining.length > 0 ? (remaining[0]?.id ?? null) : null
  if (activeWorkspaceId != null) {
    lastWorkspace.id = activeWorkspaceId
  }
}

// Closing the rest leaves the kept one showing, whether or not it was the one being looked at.
async function closeOthers(id: string) {
  const others = workspaces.filter((workspace) => workspace.id !== id)
  await tabs.closeMany(
    placement,
    others.map((workspace) => workspace.id),
  )
  showWorkspace(id)
}

// Closing everything leaves the page showing nothing, which is its own empty state.
async function closeAll() {
  await tabs.closeMany(
    placement,
    workspaces.map((workspace) => workspace.id),
  )
  activeWorkspaceId = null
}

// Opening the rest keeps whatever was already showing since opening tabs is not a request to
// look somewhere else. With nothing showing it lands on the first of them.
async function openAll() {
  const opening = openable.map((workspace) => workspace.id)
  await tabs.openMany(placement, opening)

  if (activeWorkspaceId == null && opening.length > 0) {
    showWorkspace(opening[0] as string)
  }
}

// Dragging positions this user's own tabs. A shared standard order is edited from the overview
// so one user arranging their strip does not rearrange everyone else's.
async function reorder(ordered: Workspace[]) {
  await tabs.reorder(
    placement,
    ordered.map((workspace) => workspace.id),
  )
}

// Watched rather than read once because the page stays mounted while an action elsewhere sends
// a workspace here, which arrives as a change of address rather than as a fresh visit.
watch(
  () => [requestedIds, adoptable] as const,
  () => {
    void adoptRequested()
  },
  { immediate: true },
)

// With nothing showing, the page opens on whichever workspace it last showed, falling back to
// the first tab when that one is gone. An empty strip has nothing to open on, and a request
// still pending is about to name one itself. The remembered workspace may only appear once the
// adoptable list has landed, so an empty one is waited for rather than guessed past.
watch(
  () => [activeWorkspaceId, workspaces, requestedIds] as const,
  ([active, listed, pending]) => {
    if (active != null || listed.length === 0 || pending.length > 0) {
      return
    }

    if (adoptable.length === 0) {
      return
    }

    const remembered = listed.find((workspace) => workspace.id === lastWorkspace.id)
    showWorkspace((remembered ?? (listed[0] as Workspace)).id)
  },
  { immediate: true },
)

defineExpose({
  /** The open workspace's component, through which a page lands widgets on its live working
  copy. */
  workspace: $$(workspaceRef),
  activeWorkspaceId: $$(activeWorkspaceId),
  reveal,
  openListed,
  openBeside,
  close,
  showWorkspace,
})
</script>

<template>
  <div v-if="!overviewCollapsed" ref="overviewElement" class="relative">
    <!-- The dragged height only applies while workspace content shows below, and never less
    than what puts the strip at the bottom edge, where it rests until the page is scrolled.
    With workspace content hidden the overview is the page and takes its full height. -->
    <div
      class="max-h-[calc(100vh-92px)] overflow-x-hidden overflow-y-auto"
      :style="sized ? overviewHeightStyle : undefined"
    >
      <slot name="overview" :open-listed="openListed" />
    </div>
    <c-resize-handle
      v-if="sized && overviewDragSize > 0"
      class="absolute bottom-0 left-0"
      direction="vertical"
      :max="800"
      :min="120"
      :model-value="overviewDragSize"
      @update:model-value="(value: number) => (overviewSize = value)"
    />
  </div>

  <!-- The strip sits in flow between the overview and the workspace, and sticks at both edges
  so it is always on screen, pinning under the header the way it always has and resting at the
  bottom while its own place is still below the fold. -->
  <c-component-workspace-strip
    v-if="workspaces.length > 0 || canCreate"
    ref="stripRef"
    v-model:collapsed="workspaceCollapsed"
    :sticky-top="workspaceStickyTop"
  >
    <template #default="{ docked, trailingInset }">
      <c-component-workspace-tabs
        :active="activeWorkspaceId"
        :active-actions="workspaceRef?.headerActions"
        :active-state="workspaceRef?.headerState"
        :bound="bound"
        :can-create="canCreate"
        :can-manage="canManage"
        :docked="docked"
        :openable="openable"
        :show-placement="showPlacement"
        :trailing-inset="trailingInset"
        :workspaces="workspaces"
        @close="close"
        @close-all="closeAll"
        @close-others="closeOthers"
        @create="emit('create')"
        @import="(files: File[]) => emit('import', files)"
        @open="open"
        @open-all="openAll"
        @open-beside="openBeside"
        @reorder="reorder"
        @select="reveal"
        @share="(ids: string[]) => emit('share', ids)"
      />
    </template>
  </c-component-workspace-strip>

  <!-- Deliberately not keyed on the workspace ID. The workspace context follows its ID, so
  switching tabs updates this in place. -->
  <c-workspace
    v-if="activeWorkspaceId != null && !workspaceCollapsed"
    :id="activeWorkspaceId"
    ref="workspaceRef"
    :sticky-top="workspaceStickyTop"
    :strip-docked="stripDocked"
    @duplicated="openBeside"
  />
</template>
