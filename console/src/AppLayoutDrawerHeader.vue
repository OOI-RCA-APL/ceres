<script lang="ts" setup>
import StatusBadge from '@/components/StatusBadge.vue'
import { treeColumnCenter } from '@/drawer'
import icons from '@/icons'

const { count, onPath = false } = defineProps<{
  /** How many components the tree is showing, which is every one until the filter narrows it. */
  count: number

  /** Whether the open component is somewhere in the tree below, which lights the line into it. */
  onPath?: boolean
}>()

const filter = defineModel<string>('filter', { default: '' })

// The count sits inside the badge's own hover target, so reaching for either opens the same menu
// rather than the number being a hole in the middle of it.
const badge = $ref<InstanceType<typeof StatusBadge> | null>(null)

// Clicking anywhere on the row puts the caret in the field, so the whole row is the target rather
// than the few pixels the text happens to occupy.
let field = $ref<HTMLInputElement | null>(null)

// The tree hangs off this row the way a component's children hang off it, so the line into column
// zero starts here and every top level component reaches back to it.
const descender = `${treeColumnCenter(0)}px`
</script>

<template>
  <!-- Names the tree, narrows it, and carries the engine's own status. One row rather than three,
  because a heading with nothing to say beyond its own name is a row spent on punctuation. -->
  <q-item :class="[$style.root, 'items-center', 'row']" dense @click="field?.focus()">
    <span :class="[$style.descender, onPath && $style.lit]" :style="{ left: descender }" />
    <q-item-section avatar>
      <q-icon :name="icons.components" />
    </q-item-section>
    <q-item-section>
      <!-- Deliberately not remembered. A filter left in place from last time would hide components
      with no sign of why, which is the one thing a tree of live equipment must never do. -->
      <input
        ref="field"
        v-model="filter"
        :class="$style.filter"
        placeholder="Components"
        spellcheck="false"
        type="text"
      />
    </q-item-section>
    <q-item-section v-if="filter !== ''" side>
      <q-btn dense flat :icon="icons.close" round size="8px" @click="filter = ''" />
    </q-item-section>
    <!-- Laid out exactly as a component's own trailing pair is, so the count sits in the column
    the connection dots run down and the badge in the column the status badges do.

    The count is kept while searching rather than replaced by it, so the number that was the size
    of the tree becomes the size of the answer without the eye having to find it somewhere else. -->
    <q-item-section side>
      <div
        :class="[$style.status, 'items-center', 'justify-end', 'q-mr-xs', 'row']"
        @mouseenter="badge?.menu.onEnter()"
        @mouseleave="badge?.menu.onLeave()"
      >
        <span :class="[$style.count, 'q-mr-sm']">{{ count }}</span>
        <status-badge ref="badge" />
      </div>
    </q-item-section>
  </q-item>
</template>

<style lang="scss" module>
/* Mirrors the width a component row reserves for its own indicators, so both rows put the same
things in the same columns. Takes a pointer over the row's own text cursor, since this end of the
row opens a menu rather than being somewhere to type. */
.status {
  min-width: 44px;
  cursor: pointer;
}

/* Quiet enough to read as a note against the heading rather than as a state of its own, which the
status badge beside it already is.

Spaced from the badge exactly as a component's connection dots are from theirs, so the pair reads
as the same column on both rows. That is spacing rather than centering, so a longer number grows
leftwards and its middle drifts off the dots above it. */
.count {
  padding: 1px 5px;
  border-radius: 8px;
  font-size: 10px;
  line-height: 14px;
}

:global(.dark) .count {
  background: #ffffff14;
  color: #ffffffb3;
}

:global(.light) .count {
  background: #0000000d;
  color: #000000b3;
}

.root {
  position: relative;
  cursor: text;
}

/* Leaves the underside of the icon on its way to the first component, which picks it up at the
top of its own row. Offset by half the icon's height and a pixel clear of it, so the tree reads as
hanging from the icon rather than as passing behind it. */
.descender {
  position: absolute;
  top: calc(50% + 13px);
  bottom: 0;
  width: 1px;
  background: currentColor;
  opacity: 0.16;
  pointer-events: none;
}

/* Lit when the open component is below, so the run down to it starts here rather than at the first
component that happens to be on the way. Mirrors what the tree's own segments do. */
.lit {
  opacity: 0.44;
}

/* Nothing is drawn around it. Left alone it is the heading it reads as, and only once the pointer
reaches it does it fall back to say it is a field waiting on something. What gets typed is at full
strength either way, since by then it is an answer rather than a prompt. */
.filter {
  width: 100%;
  min-width: 0;
  padding: 0;
  border: none;
  background: transparent;
  color: inherit;
  font: inherit;
  outline: none;
}

.filter::placeholder {
  color: inherit;
  opacity: 1;
  transition: opacity 0.15s;
}

.root:hover .filter::placeholder {
  opacity: 0.6;
}

.root:focus-within .filter::placeholder {
  opacity: 0.4;
}
</style>
