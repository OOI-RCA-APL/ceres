<script lang="ts" setup>
import StatusBadge from '@/components/StatusBadge.vue'
import { treeColumnCenter } from '@/drawer'
import icons from '@/icons'

const { count, onPath = false } = defineProps<{
  /** How many components the tree is showing. */
  count: number

  /** Whether the open component is somewhere in the tree below, which lights the line into it. */
  onPath?: boolean
}>()

const filter = defineModel<string>('filter', { default: '' })

// The count shares the badge's hover target so hovering either opens the same menu.
const badge = $ref<InstanceType<typeof StatusBadge> | null>(null)

// Clicking anywhere on the row focuses the field.
let field = $ref<HTMLInputElement | null>(null)

// The tree's line into column zero starts at this row.
const descender = `${treeColumnCenter(0)}px`
</script>

<template>
  <!-- Names the tree, narrows it, and carries the engine's own status. -->
  <q-item :class="[$style.root, 'items-center', 'row']" dense @click="field?.focus()">
    <span :class="[$style.descender, onPath && $style.lit]" :style="{ left: descender }" />
    <q-item-section avatar>
      <q-icon :name="icons.components" />
    </q-item-section>
    <q-item-section>
      <!-- Deliberately not remembered. A filter left in place from last time would hide
      components with no sign of why, which a tree of live equipment must never do. -->
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
    <!-- Laid out as a component row's trailing pair so the count and badge sit in the same
    columns the connection dots and status badges do. -->
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
/* Mirrors the width a component row reserves for its indicators. Pointer cursor because this end
of the row opens a menu rather than accepting text. */
.status {
  min-width: 44px;
  cursor: pointer;
}

/* Spaced from the badge as a component's connection dots are so the pair reads as the same
column on both rows. */
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

/* Offset a pixel clear of the icon's underside so the tree reads as hanging from it rather than
passing behind it. */
.descender {
  position: absolute;
  top: calc(50% + 13px);
  bottom: 0;
  width: 1px;
  background: currentColor;
  opacity: 0.16;
  pointer-events: none;
}

/* Lit when the open component is below, mirroring the tree's own segments. */
.lit {
  opacity: 0.44;
}

/* Undecorated so it reads as a heading, with the placeholder dimming on hover to hint that it is
a field. */
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
