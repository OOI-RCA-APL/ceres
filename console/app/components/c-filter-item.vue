<script lang="ts" setup>
import type { DropdownMenuItem } from '@nuxt/ui'
import { inject } from 'vue'

import { getFilterDefinition } from '@/filters/definitions'
import { filterLiftKey } from '@/filters/lift'
import { isBlock } from '@/filters/model'
import type { FilterItem } from '@/filters/model'
import icons from '@/icons'

const {
  item,
  selected = false,
  groupTarget = false,
  nested = false,
  focusId = null,
  addressOptions = [],
} = defineProps<{
  item: FilterItem
  /** Whether the root item renders highlighted. Children never highlight on their own. */
  selected?: boolean
  /** Whether releasing the chip being dragged would group it with this one. */
  groupTarget?: boolean
  /** Whether this sits inside a block, which is what makes it draggable out of one. */
  nested?: boolean
  /** The item whose value input claims focus, for a condition just accepted from the input. */
  focusId?: string | null
  addressOptions?: readonly string[]
}>()

// The bar carries a lifted chip, since where it lands is a root position only the bar knows.
const lift = inject(filterLiftKey, null)

const emit = defineEmits<{
  /** A condition's value changed, `id` naming the condition wherever it nests. */
  change: [id: string, value: unknown]
  /** The X on a condition or block, `id` naming the item to remove. */
  remove: [id: string]
  /** A value input finished, so the bar can return focus to its own input. */
  commit: []
  /** A block's joining operator was switched, `id` naming the block wherever it nests. */
  operator: [id: string, op: 'and' | 'or']
}>()

const operatorItems = $computed<DropdownMenuItem[]>(() =>
  (['and', 'or'] as const).map((op) => ({
    label: op.toUpperCase(),
    onSelect: () => emit('operator', item.id, op),
  })),
)

const definition = $computed(() => (isBlock(item) ? null : getFilterDefinition(item.kind)))
</script>

<template>
  <div
    v-if="isBlock(item)"
    :class="[
      'border-default relative flex min-h-4.5 shrink-0 cursor-default items-center gap-1',
      'rounded-md border border-dashed py-px pr-0.5 pl-1.5 whitespace-nowrap select-none',
      selected && 'outline-[1.5px] outline-offset-[-1.5px] outline-primary',
      // Where a held chip would land to make a group. Dashed to read as the group's own border,
      // which is drawn the same way, rather than as the solid ring a selection carries.
      groupTarget && 'outline-[1.5px] outline-offset-[-1.5px] outline-dashed outline-primary',
    ]"
    data-filter-block
    :data-filter-lift="nested ? item.id : undefined"
    :style="nested ? lift?.styleFor(item.id) : undefined"
    v-on="nested ? (lift?.handlers(item.id) ?? {}) : {}"
  >
    <template v-for="(child, index) in item.children" :key="child.id">
      <!-- The joiner is the block's own control, so switching how the group reads is done where
      it reads rather than through the menu that built it. -->
      <c-dropdown-menu v-if="index > 0" :items="operatorItems" size="sm">
        <button
          class="text-muted hover:text-default cursor-pointer uppercase"
          type="button"
          @click.stop
          @pointerdown.stop
        >
          <c-text element="span" variant="mono-xs">{{ item.op }}</c-text>
        </button>
      </c-dropdown-menu>
      <c-filter-item
        :address-options="addressOptions"
        :focus-id="focusId"
        :item="child"
        nested
        @change="(id, value) => emit('change', id, value)"
        @commit="emit('commit')"
        @operator="(id, op) => emit('operator', id, op)"
        @remove="(id) => emit('remove', id)"
      />
    </template>
    <!-- Set apart from the last child's own remove so the two do not read as one control. -->
    <!-- Laid out rather than left inline, an inline box being as tall as the line it sits on
    however small the icon in it, which is most of the height of a chip this size. -->
    <button
      class="text-muted hover:text-default ml-1 flex cursor-pointer items-center p-0.5"
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
      'bg-elevated hover:bg-accented/60 relative flex min-h-4.5 shrink-0 cursor-default',
      'items-center gap-0.5 overflow-hidden rounded-md py-px pr-0.5 pl-2.5 whitespace-nowrap',
      'select-none',
      selected && 'outline-[1.5px] outline-offset-[-1.5px] outline-primary',
      // Where a held chip would land to make a group. Dashed to read as the group's own border,
      // which is drawn the same way, rather than as the solid ring a selection carries.
      groupTarget && 'outline-[1.5px] outline-offset-[-1.5px] outline-dashed outline-primary',
    ]"
    :data-filter-lift="nested ? item.id : undefined"
    :style="nested ? lift?.styleFor(item.id) : undefined"
    v-on="nested ? (lift?.handlers(item.id) ?? {}) : {}"
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
      class="text-muted hover:text-default flex cursor-pointer items-center p-0.5"
      type="button"
      @click.stop="emit('remove', item.id)"
      @pointerdown.stop
    >
      <c-icon :name="icons.close" size="11" />
    </button>
  </div>
</template>
