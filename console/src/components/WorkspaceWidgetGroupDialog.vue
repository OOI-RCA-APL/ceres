<script lang="ts" setup>
import CommonText from '@/components/CommonText.vue'
import icons from '@/icons'
import { usePersisted } from '@/persistence'
import { useWorkspace } from '@/workspace'

const { widgetIds } = defineProps<{
  /** The widgets to group, resolved by the menu that opened this dialog. */
  widgetIds: string[]
}>()

const emit = defineEmits<{ close: [] }>()

const workspace = useWorkspace()

// Opens open, since the dialog is only mounted to be shown, and unmounts once hidden.
let open = $ref(true)

// The last confirmed choices are the likeliest next ones, so they are where the dialog starts.
// They are written back only on "Group", so browsing the selects and cancelling remembers
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

// How many rows the taken widgets stand in, which is what makes a per-row split mean anything.
// With a single row, per-row and all-on-one are the same page, so only the latter is offered.
const rowCount = $computed(() => {
  const taking = new Set(widgetIds)
  for (const layout of workspace.layouts) {
    const count = layout.rows.filter((row) =>
      row.widgets.some((widget) => taking.has(widget.id))
    ).length
    if (count > 0) {
      return count
    }
  }

  return 0
})

let kind = $ref(persisted.kind)
let split = $ref(persisted.split === 'row' && rowCount < 2 ? 'widget' : persisted.split)
let frameless = $ref(persisted.frameless)

// A page holding one widget already names it on the tab or the dot, so its frame is pure
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
  <q-dialog v-model="open" @hide="emit('close')">
    <q-card bordered :class="$style.dialog" flat>
      <div class="q-px-md row">
        <common-text class="q-mb-sm q-mt-sm" element="h2" variant="title1">
          {{ widgetIds.length > 1 ? 'Group Widgets' : 'Group Widget' }}
        </common-text>
        <q-space />
        <div class="items-center row">
          <q-btn flat :icon="icons.close" round size="10px" @click="open = false" />
        </div>
      </div>
      <q-separator />
      <q-card-section>
        <q-select
          v-model="kind"
          class="q-mb-xs"
          dense
          emit-value
          label="Group Into"
          map-options
          :options="kindOptions"
          options-dense
          outlined
        />
        <div class="items-center no-wrap row">
          <!-- With one widget every split lands the same single page, so there is no choice to
          offer. -->
          <div v-if="widgetIds.length > 1" class="col-grow">
            <q-select
              v-model="split"
              dense
              emit-value
              label="As"
              map-options
              :options="splitOptions"
              options-dense
              outlined
            />
          </div>
          <div v-if="offersFrameless" class="col-auto" :class="widgetIds.length > 1 && 'q-ml-sm'">
            <q-toggle v-model="frameless" dense label="Frameless" size="sm" />
          </div>
        </div>
      </q-card-section>
      <q-separator />
      <q-btn
        autofocus
        class="full-width"
        color="primary"
        dense
        flat
        label="Group"
        no-caps
        @click="group"
      />
    </q-card>
  </q-dialog>
</template>

<style lang="scss" module>
// A fixed width rather than a percentage, since Quasar's own dialog sizing rule outranks this
// class and would stretch a percentage to its 560px cap. Wide enough for the split select and
// the frames toggle to share their row without wrapping.
.dialog {
  width: 330px;
  max-width: 90vw;
}
</style>
