<script lang="ts" setup>
import { useRoute } from 'vue-router'

import AppLayoutDrawerComponent from '@/AppLayoutDrawerComponent.vue'
import { useAccess } from '@/api/access'
import { Address } from '@/api/address'
import { ComponentInfo } from '@/api/components'
import AlertsIndicator from '@/components/AlertsIndicator.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import { treeColumnCenter, treeColumnStart, treeNodeSize, useDrawer } from '@/drawer'
import icons from '@/icons'

const {
  address,
  component,
  filter = '',
  trail = [],
  hasFollowingSibling = false,
  pathTrail = [],
  activeAfterMe = false,
} = defineProps<{
  address: Address
  component: ComponentInfo
  /** What the tree is being narrowed to, matched against addresses. Empty shows everything. */
  filter?: string

  /** Whether each ancestor above this row's parent still has rows to come.

  One entry per column between the left edge and this row's parent. A column whose ancestor has
  more children below carries its line straight through this row on the way down to them, and one
  whose ancestor is finished leaves the column empty.
  */
  trail?: boolean[]

  /** Whether this row has a sibling after it, which is what decides whether the elbow reaching it
  is a corner or a junction the line carries on past. */
  hasFollowingSibling?: boolean

  /** Whether each column's line, as it passes this row, is on the way to the open component.

  One entry per column in `trail`. A line only carries the path where the open component is further
  down it, which is what keeps the highlight a single unbroken run from the top rather than a lit
  fragment beside every dim one.
  */
  pathTrail?: boolean[]

  /** Whether the open component is in a sibling after this one, told by the parent, which is the
  only thing that knows the order its children are in. */
  activeAfterMe?: boolean
}>()

const drawer = useDrawer()
const access = useAccess()
const route = useRoute()

/** Whether the component being looked at is this one or sits somewhere below it.

The whole branch down to it is drawn stronger, not just the corner reaching it, so the tree traces
the way back to where you are rather than marking only the end of it. The dot guards against a
sibling whose name merely starts the same way.
*/
const isOnPath = $computed(() => {
  const active = typeof route.params.address === 'string' ? route.params.address : null
  if (active == null) {
    return false
  }

  const own = address.toString()
  return active === own || active.startsWith(`${own}.`)
})

const badge = $ref<InstanceType<typeof StatusBadge> | null>(null)

// Components the user can only look at read quieter than the ones they can control, so a glance
// down the tree separates what can be acted on from what can only be read.
const canControl = $computed(() => access.canOperate(address.toString()))

const filterText = $computed(() => filter.trim().toLowerCase())

/** Whether this component or anything below it answers the filter.

A match keeps the whole path that leads to it rather than appearing detached from its parents, so
what is left still reads as a tree instead of as a list of addresses.
*/
function subtreeMatches(current: ComponentInfo, at: Address): boolean {
  if (at.toString().toLowerCase().includes(filterText)) {
    return true
  }

  return current.components.some((child) => subtreeMatches(child, at.append(child.name)))
}

const isShown = $computed(() => filterText === '' || subtreeMatches(component, address))

// Filtering opens whatever it had to look through, since a match hidden inside something collapsed
// is no answer at all. Collapsing is remembered rather than overwritten, so the tree returns to how
// it was left once the filter is cleared.
const isExpanded = $computed(
  () => filterText !== '' || !drawer.collapsed.some((current) => current.equals(address))
)

const isTopLevel = $computed(() => address.depth === 1)
const isLeaf = $computed(() => component.components.length === 0)

// Columns are numbered from the header's own, which is zero, so a top level component sits in
// column one and hangs off the header exactly as a child hangs off its parent.
const column = $computed(() => address.depth)

// Where this row's own column begins, which is where its toggle and everything after it start.
const railIndent = $computed(() => `${treeColumnStart(column)}px`)

// The columns that carry an ancestor's line straight down through this row on its way to
// something further below, and whether that something is the open component.
const passingGuides = $computed(() =>
  trail.flatMap((continues, index) =>
    continues ? [{ left: `${treeColumnCenter(index)}px`, lit: pathTrail[index] ?? false }] : []
  )
)

/** Which of this component's children the open one is in, or below.

Only a parent knows what order its children are in, so this is where each of them is told whether
the path carries on past it to a later one.
*/
const activeChildIndex = $computed(() => {
  const active = typeof route.params.address === 'string' ? route.params.address : null
  if (active == null) {
    return -1
  }

  return component.components.findIndex((child) => {
    const childAddress = `${address}.${child.name}`
    return active === childAddress || active.startsWith(`${childAddress}.`)
  })
})

/** The corner joining this row to whatever it hangs from, drawn in that column.

Three pieces rather than one, because each is on the way somewhere different. The stem above comes
down from the row before, the reach turns out of the column towards this row, and the stem below
carries on to whatever comes next. Only some of those lead to the open component, so each is lit on
its own.

They are cut so that none overlaps another, since two faded lines crossing leave a brighter mark
exactly where they meet.
*/
const elbow = $computed(() => {
  const from = treeColumnCenter(column - 1)
  const to = treeColumnCenter(column) - (isLeaf ? 0 : treeNodeSize / 2)

  return {
    left: `${from}px`,
    reachLeft: `${from + 1}px`,
    reachWidth: `${to - from - 1}px`,
  }
})

// Where this row sits on its own column, which is the dot ending a branch or the ring around the
// toggle that opens one. Drawn with the lines rather than in the row, so each reads as the branch
// arriving rather than as an icon the row happens to carry.
const nodeLeft = $computed(() => `${treeColumnCenter(column)}px`)

// What this row's children inherit, which is every column this row's own corner passes through.
const childTrail = $computed(() => [...trail, hasFollowingSibling])
const childPathTrail = $computed(() => [...pathTrail, activeAfterMe])

function toggleExpanded() {
  if (isExpanded) {
    drawer.collapsed = [...drawer.collapsed, address]
  } else {
    drawer.collapsed = drawer.collapsed.filter((current) => !current.equals(address))
  }
}
</script>

<template>
  <template v-if="isShown">
    <q-item
      :class="[$style.root, 'items-center', 'row']"
      clickable
      dense
      :to="`/components/${address}`"
    >
      <!-- One column per level. The lines are drawn rather than the space merely being left, so
      depth is read off the tree instead of measured, and a component with nothing under it needs
      no mark of its own to say it is there.

      Each segment carries its own strength, so the run leading to the open component is lit the
      whole way down rather than only where it happens to turn. The corner is the exception and is
      faded as one piece, because two faded lines crossing would leave a brighter dot where they
      join. -->
      <span :class="$style.guides">
        <span
          v-for="(guide, index) in passingGuides"
          :key="index"
          :class="[$style.passing, guide.lit && $style.lit]"
          :style="{ left: guide.left }"
        />
        <span
          :class="[$style.stemAbove, (isOnPath || activeAfterMe) && $style.lit]"
          :style="{ left: elbow.left }"
        />
        <span
          v-if="hasFollowingSibling"
          :class="[$style.stemBelow, activeAfterMe && $style.lit]"
          :style="{ left: elbow.left }"
        />
        <span
          :class="[$style.reach, isOnPath && $style.lit]"
          :style="{ left: elbow.reachLeft, width: elbow.reachWidth }"
        />
        <span
          v-if="isLeaf"
          :class="[$style.node, isOnPath && $style.lit]"
          :style="{ left: nodeLeft }"
        />
        <span
          v-else-if="isExpanded"
          :class="[$style.descender, activeChildIndex >= 0 && $style.lit]"
          :style="{ left: nodeLeft }"
        />
      </span>
      <div :class="[$style.rail, 'items-center', 'row']" :style="{ paddingLeft: railIndent }">
        <q-btn
          v-if="!isLeaf"
          :class="[$style.toggle, isOnPath && $style.toggleLit]"
          flat
          @click.stop.prevent="toggleExpanded"
        >
          <q-icon :name="isExpanded ? icons.menuDown : icons.menuRight" size="12px" />
        </q-btn>
        <span v-else :class="$style.spacer" />
      </div>
      <q-item-section no-wrap>
        <q-item-label
          :class="['text-no-wrap', !canControl && $style.readonly]"
          :style="!isTopLevel && { paddingLeft: '1.5px' }"
        >
          {{ isTopLevel ? component.address : '.' + component.name }}
        </q-item-label>
      </q-item-section>
      <q-item-section side>
        <div
          :class="[$style.status, 'items-center', 'justify-end', 'q-mr-xs', 'row']"
          @mouseenter="badge?.menu.onEnter()"
          @mouseleave="badge?.menu.onLeave()"
        >
          <alerts-indicator :address class="q-mr-xs" />
          <status-badge ref="badge" :address />
        </div>
      </q-item-section>
    </q-item>
    <div v-if="!isLeaf && isExpanded">
      <app-layout-drawer-component
        v-for="(subcomponent, index) in component.components"
        :key="subcomponent.name"
        :active-after-me="activeChildIndex > index"
        :address="address.append(subcomponent.name)"
        :component="subcomponent"
        :filter
        :has-following-sibling="index < component.components.length - 1"
        :path-trail="childPathTrail"
        :trail="childTrail"
      />
    </div>
  </template>
</template>

<style lang="scss" module>
/* The row's own left padding is carried by the rail instead, so the indent is one number and the
guides can be placed against it. */
.root {
  position: relative;
  padding-left: 0 !important;
}

/* Reaching for a component and arriving at it are the same gesture at two strengths, so both tint
towards primary and only the amount differs. */
.root:hover {
  background-color: rgba($primary, 0.14);
}

/* Quasar washes a hovered item in the current text color, which would sit over the tint above and
muddy it. The tint is the hover here. Left alone for focus, which still needs its own mark. */
.root:hover :global(.q-focus-helper) {
  opacity: 0 !important;
}

.rail {
  flex: none;
  align-self: stretch;
}

/* The toggle carries the branch's own ring as its border, so the outline and the button are one
thing rather than a circle drawn behind a square. Sized to `treeNodeSize`, which is where the lines
reaching it stop.

Pulled in by a pixel on each side so a ring wider than its column still advances the row by exactly
one column and a gap, leaving a parent's name in line with a leaf's. The width and that gap mirror
`treeToggleWidth` and `treeLabelGap`, which CSS cannot read, so changing either means changing
both. */
.toggle {
  position: relative;
  width: 16px;
  min-width: 16px !important;
  height: 16px;
  min-height: 16px !important;
  padding: 0 !important;
  margin: 0 5px 0 -1px;
  border: 1px solid;
  border-radius: 50%;
}

/* The hit area reaches past the ring without taking the width. */
.toggle::before {
  content: '';
  position: absolute;
  inset: -3px;
}

/* Where a component with nothing under it would have had a toggle, kept so every name in the
column starts in the same place. */
.spacer {
  width: 14px;
  margin-right: 6px;
}

/* Taken from the theme rather than inherited, for the same reason the lines are. A selected row
must not draw its own branch in the selection color.

The ring is a line and takes the lines' value. The chevron inside it is an arrow and takes the one
every other arrow in the drawer has, so the two read as a mark drawn on the branch with a control
sitting in it. The ring brightens only under the pointer that is on it rather than with the row
around it, since hovering a name is reading and not reaching for the toggle. */
:global(.dark) .toggle {
  border-color: #ffffff29;
  color: #ffffffb3;
}

:global(.light) .toggle {
  border-color: #00000029;
  color: #000000b3;
}

:global(.dark) .toggle:hover {
  border-color: #ffffff73;
}

:global(.light) .toggle:hover {
  border-color: #00000073;
}

/* A ring on the way to the open component is part of the run reaching it, so it takes what those
lines take. Written against the toggle itself so it outweighs the theme's own color for it, which
is set through a theme class and would otherwise win. */
:global(.dark) .toggle.toggleLit {
  border-color: #ffffff70;
}

:global(.light) .toggle.toggleLit {
  border-color: #00000070;
}

/* Enough of a difference to be seen down a column of names. The old value was a tenth of a stop,
which said nothing and so said it about every row equally. */
.readonly {
  opacity: 0.6;
}

/* Reserve the width an indicator would take so every row has the same status hover target. */
.status {
  min-width: 44px;
}

/* Faint enough to be structure rather than content, and each segment carrying its own strength so
the run reaching the open component is lit without lighting the rows it merely passes.

The color is taken from the theme rather than inherited from the row. The lines belong to the tree,
not to whichever component happens to be open, so a selected row must not paint the structure
running through it in the selection color. */
.guides {
  position: absolute;
  inset: 0;
  pointer-events: none;
}

:global(.dark) .guides {
  color: #fff;
}

:global(.light) .guides {
  color: #000;
}

.passing,
.stemAbove,
.stemBelow,
.reach,
.node,
.descender {
  position: absolute;
  background: currentColor;
  opacity: 0.16;
}

/* The run leading to the open component. The theme's own color drawn stronger rather than a color
of its own, since a coloured line down the sidebar pulls harder than whatever it points at. */
.lit {
  opacity: 0.44;
}

/* An ancestor's line on its way past this row to something further down. */
.passing {
  top: 0;
  bottom: 0;
  width: 1px;
}

/* Down from the row before to this row's middle, reaching a pixel past it so the corner itself
belongs to one segment rather than to two overlapping ones. */
.stemAbove {
  top: 0;
  height: calc(50% + 1px);
  width: 1px;
}

/* On from the corner to whatever comes after this row. */
.stemBelow {
  top: calc(50% + 1px);
  bottom: 0;
  width: 1px;
}

/* Out of the column towards where this row begins, starting clear of the stem for the same reason
the stem reaches past the middle. */
.reach {
  top: 50%;
  height: 1px;
}

/* The end of a branch, sitting where the toggle of a component with children would be.

Pulled back by half its width less half a pixel, because a line one pixel wide starting at a
position covers the pixel after it rather than straddling it. Centering the dot on the position
itself would leave it half a pixel above the line it terminates. */
.node {
  top: 50%;
  width: 3px;
  height: 3px;
  margin: -1px 0 0 -1.5px;
  border-radius: 50%;
}

/* Leaves the ring's underside on its way to the first child, which picks it up at the top of its
own row. */
.descender {
  top: calc(50% + 8px);
  bottom: 0;
  width: 1px;
}
</style>
