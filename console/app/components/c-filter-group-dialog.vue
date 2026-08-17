<script lang="ts">
export type FilterGroupDialogProps = {
  /** What the two chips read as, for naming the pair being joined. */
  labels: [string, string]
}
</script>

<script lang="ts" setup>
import icons from '@/icons'

const { labels } = defineProps<FilterGroupDialogProps>()

/** Closes with the operator to join by, or `false` for a cancel. */
const emit = defineEmits<{ close: ['and' | 'or' | false] }>()

// The bar already joins everything by AND, so a group that reads AND changes nothing a reader
// would notice. OR is what the grouping is nearly always reached for.
let op = $ref<'and' | 'or'>('or')
</script>

<template>
  <c-modal
    title="Group Filters"
    :ui="{ content: 'w-[420px] max-w-[95vw]' }"
    @update:open="(value: boolean) => value || emit('close', false)"
  >
    <template #body>
      <c-text class="mb-4 block" variant="body2">
        Join
        <c-text element="span" variant="mono-xs">{{ labels[0] }}</c-text>
        and
        <c-text element="span" variant="mono-xs">{{ labels[1] }}</c-text>
        into one group.
      </c-text>
      <c-radio-group
        v-model="op"
        :items="[
          { label: 'OR, matching either of them.', value: 'or' },
          { label: 'AND, matching both.', value: 'and' },
        ]"
      />
    </template>
    <template #footer>
      <div class="flex w-full gap-2">
        <c-button
          block
          class="flex-1"
          color="neutral"
          :icon="icons.cancel"
          label="Cancel"
          variant="soft"
          @click="emit('close', false)"
        />
        <c-button
          block
          class="flex-1"
          :icon="icons.confirm"
          :label="op === 'or' ? 'Group as OR' : 'Group as AND'"
          @click="emit('close', op)"
        />
      </div>
    </template>
  </c-modal>
</template>
