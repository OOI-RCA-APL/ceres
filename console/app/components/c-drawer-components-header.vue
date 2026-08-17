<script lang="ts" setup>
import { treeColumnCenter } from '@/drawer'
import icons from '@/icons'

const { count, onPath = false } = defineProps<{
  /** How many components the tree is showing. */
  count: number

  /** Whether the open component is somewhere in the tree below, which lights the line into it. */
  onPath?: boolean
}>()

const filter = defineModel<string>('filter', { default: '' })

// Clicking anywhere on the row focuses the field.
let field = $ref<HTMLInputElement | null>(null)

// The tree's line into column zero starts at this row.
const descender = `${treeColumnCenter(0)}px`
</script>

<!-- Names the tree, narrows it, and carries the engine's own status. -->
<template>
  <div
    class="relative flex cursor-text items-center gap-2 py-1 pr-3 pl-3 text-sm"
    :class="$style.root"
    @click="field?.focus()"
  >
    <span :class="[$style.descender, onPath && $style.lit]" :style="{ left: descender }" />
    <c-icon class="size-5" :name="icons.components" />
    <!-- Deliberately not remembered. A filter left in place from last time would hide components
    with no sign of why, which a tree of live equipment must never do. -->
    <input
      ref="field"
      v-model="filter"
      :class="$style.filter"
      placeholder="Components"
      spellcheck="false"
      type="text"
    />
    <c-button
      v-if="filter !== ''"
      color="neutral"
      :icon="icons.close"
      size="xs"
      variant="ghost"
      @click="filter = ''"
    />
    <!-- Laid out as a component row's trailing pair so the count and badge sit in the same columns
    the connection dots and status badges do. -->
    <div class="flex min-w-11 items-center justify-end">
      <c-status-badge>
        <template #leading>
          <c-badge class="mr-2" color="neutral" size="sm" variant="subtle">{{ count }}</c-badge>
        </template>
      </c-status-badge>
    </div>
  </div>
</template>

<style module>
/* Offset a pixel clear of the icon's underside so the tree reads as hanging from it rather than
passing behind it. */
.descender {
  position: absolute;
  top: calc(50% + 13px);
  bottom: 0;
  width: 1px;
  background: var(--ui-text);
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
  flex: 1;
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
