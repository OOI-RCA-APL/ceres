<script lang="ts" setup>
import { usePersisted } from '@/persistence'
import { useWorkspace } from '@/workspace'

const { widgetIds } = defineProps<{
  /** The widgets to group, resolved by the menu that opened this dialog. */
  widgetIds: string[]
}>()

const emit = defineEmits<{ close: [] }>()

const workspace = useWorkspace()

// Opens open since the dialog is only mounted to be shown, and unmounts once hidden.
let open = $ref(true)

// The last confirmed choices are the likeliest next ones so they are where the dialog starts.
// They are written back only on "Group" so browsing the selects and cancelling remembers
// nothing.
const persisted = usePersisted({
  schema: (zod) =>
    zod.object({
      kind: zod.enum(['tabs', 'carousel']).catch('tabs'),
      split: zod.enum(['widget', 'row', 'none']).catch('widget'),
      frameless: zod.boolean().catch(false),
    }),
  methods: [{ type: 'local-storage', key: 'group-widgets' }],
})

// How many rows the taken widgets stand in, which gives a per-row split meaning.
// With a single row, per-row and all-on-one are the same page so only the latter is offered.
const rowCount = $computed(() => {
  const taking = new Set(widgetIds)
  for (const layout of workspace.layouts) {
    const count = layout.rows.filter((row) =>
      row.widgets.some((widget) => taking.has(widget.id)),
    ).length
    if (count > 0) {
      return count
    }
  }

  return 0
})

let kind = $ref<'tabs' | 'carousel'>(persisted.kind)
let split = $ref<'widget' | 'row' | 'none'>(
  persisted.split === 'row' && rowCount < 2 ? 'widget' : persisted.split,
)
let frameless = $ref(persisted.frameless)

// A page holding one widget already names it on the tab or the dot so its frame is pure
// repetition and hiding frames is offered. A page holding several needs them to stay told apart.
const offersFrameless = $computed(() => split === 'widget' || widgetIds.length === 1)

const kindOptions = [
  { label: 'Tabs', value: 'tabs' },
  { label: 'Carousel', value: 'carousel' },
]

const pageWord = $computed(() => (kind === 'tabs' ? 'Tab' : 'Slide'))

// Named in the chosen kind's own word, and short enough to share a row with the frames toggle.
const splitOptions = $computed(() => [
  { label: `${pageWord} Per Widget`, value: 'widget' },
  ...(rowCount > 1 ? [{ label: `${pageWord} Per Row`, value: 'row' }] : []),
  { label: `One ${pageWord}`, value: 'none' },
])

function group() {
  persisted.kind = kind
  persisted.split = split
  persisted.frameless = frameless
  workspace.groupWidgets(widgetIds, kind, split, offersFrameless && frameless)
  open = false
}
</script>

<template>
  <c-modal
    v-model:open="open"
    :title="widgetIds.length > 1 ? 'Group Widgets' : 'Group Widget'"
    :ui="{ content: 'w-[330px] max-w-[90vw]' }"
    @after:leave="emit('close')"
  >
    <template #body>
      <c-select
        v-model="kind"
        class="mb-2 w-full"
        :items="kindOptions"
        label-key="label"
        value-key="value"
      />
      <div class="flex flex-nowrap items-center gap-2">
        <!-- With one widget every split lands the same single page so there is no choice to
        offer. -->
        <c-select
          v-if="widgetIds.length > 1"
          v-model="split"
          class="grow"
          :items="splitOptions"
          label-key="label"
          value-key="value"
        />
        <c-checkbox v-if="offersFrameless" v-model="frameless" label="Frameless" size="sm" />
      </div>
    </template>
    <template #footer>
      <c-button autofocus block color="primary" label="Group" variant="ghost" @click="group" />
    </template>
  </c-modal>
</template>
