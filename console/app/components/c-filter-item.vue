<script lang="ts" setup>
import { getFilterDefinition } from '@/filters/definitions'
import { isBlock } from '@/filters/model'
import type { FilterItem } from '@/filters/model'
import icons from '@/icons'

const {
  item,
  selected = false,
  focusId = null,
  addressOptions = [],
} = defineProps<{
  item: FilterItem
  /** Whether the root item renders highlighted. Children never highlight on their own. */
  selected?: boolean
  /** The item whose value input claims focus, for a condition just accepted from the input. */
  focusId?: string | null
  addressOptions?: readonly string[]
}>()

const emit = defineEmits<{
  /** A condition's value changed, `id` naming the condition wherever it nests. */
  change: [id: string, value: unknown]
  /** The X on a condition or block, `id` naming the item to remove. */
  remove: [id: string]
  /** A value input finished, so the bar can return focus to its own input. */
  commit: []
}>()

const definition = $computed(() => (isBlock(item) ? null : getFilterDefinition(item.kind)))
</script>

<template>
  <div
    v-if="isBlock(item)"
    :class="[
      'border-default flex min-h-5 cursor-default items-center gap-1 rounded-md border',
      'border-dashed py-0.5 pr-0.5 pl-1.5 select-none',
      selected && $style.selected,
    ]"
  >
    <template v-for="(child, index) in item.children" :key="child.id">
      <c-text v-if="index > 0" class="text-muted uppercase" element="span" variant="mono-xs">
        {{ item.op }}
      </c-text>
      <c-filter-item
        :address-options="addressOptions"
        :focus-id="focusId"
        :item="child"
        @change="(id, value) => emit('change', id, value)"
        @commit="emit('commit')"
        @remove="(id) => emit('remove', id)"
      />
    </template>
    <!-- Set apart from the last child's own remove so the two do not read as one control. -->
    <button
      class="text-muted hover:text-default ml-1 cursor-pointer p-0.5"
      type="button"
      @click.stop="emit('remove', item.id)"
      @pointerdown.stop
    >
      <c-icon :name="icons.close" size="11" />
    </button>
  </div>
  <div
    v-else
    :class="[
      'bg-elevated hover:bg-accented/60 flex min-h-5 cursor-default items-center gap-1',
      'rounded-md py-0.5 pr-0.5 pl-1.5 select-none',
      selected && $style.selected,
    ]"
  >
    <c-text class="text-muted" element="span" variant="mono-xs">
      {{ definition?.label ?? item.kind }}:
    </c-text>
    <c-filter-value-input
      :address-options="addressOptions"
      :autofocus="focusId === item.id"
      :input="definition?.input ?? { type: 'text' }"
      :model-value="item.value"
      @commit="emit('commit')"
      @update:model-value="(value) => emit('change', item.id, value)"
    />
    <button
      class="text-muted hover:text-default cursor-pointer p-0.5"
      type="button"
      @click.stop="emit('remove', item.id)"
      @pointerdown.stop
    >
      <c-icon :name="icons.close" size="11" />
    </button>
  </div>
</template>

<style module>
.selected {
  outline: 1.5px solid var(--ui-primary);
  outline-offset: 0;
}
</style>
