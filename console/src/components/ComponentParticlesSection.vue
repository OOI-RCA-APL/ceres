<script lang="ts" setup>
import { Address, AddressSelector } from '@/api/address'
import { useAuth } from '@/api/auth'
import { ParticleTypeInfo } from '@/api/components'
import icons from '@/icons'
import { useNotify } from '@/notify'
import { useParticleTypes } from '@/particle-types'
import { isType, Schema } from '@/schema-form'
import { isStructurallyEqual } from '@/utilities'
import {
  ChartWidget,
  ChartWidgetParticleModel,
  createWidget,
  getWidgetInfo,
  useWorkspaces,
  WidgetRow,
  WidgetRowModel,
  withoutMeta,
  Workspace,
} from '@/workspace'

const { address, scopedWorkspaces } = defineProps<{
  address: Address
  /** Workspaces currently on the component's strip. A chart lands on the first of them. */
  scopedWorkspaces: Workspace[]
}>()

const emit = defineEmits<{
  /** A chart landed on the workspace with this ID, which the caller shows and refreshes its
  strip for. */
  charted: [id: string]
}>()

let expanded = $(defineModel<boolean>('expanded', { required: true }))

const auth = useAuth()
const notify = useNotify()
const workspaces = useWorkspaces()

const types = $(useParticleTypes(() => address.toString()).types)

function isPlottable(schema: Schema): boolean {
  return isType(schema, 'number') || isType(schema, 'integer')
}

function describeType(schema: Schema): string {
  for (const candidate of ['string', 'number', 'integer', 'boolean', 'array', 'object']) {
    if (isType(schema, candidate)) {
      return candidate
    }
  }

  return 'value'
}

function describeField(schema: unknown): string | undefined {
  return typeof schema === 'object' && schema != null
    ? (schema as { description?: string }).description
    : undefined
}

function plottableFields(type: ParticleTypeInfo): string[] {
  return type.fields
    .filter((field) => isPlottable(field.schema as Schema))
    .map((field) => field.name)
}

// Chartable fields start checked, others stay listed but disabled. Derived rather than seeded
// once so no watcher is needed over the query result.
let selected = $ref<Record<string, string[]>>({})

function selectionFor(type: ParticleTypeInfo): string[] {
  return selected[type.type] ?? plottableFields(type)
}

function isSelected(type: ParticleTypeInfo, field: string): boolean {
  return selectionFor(type).includes(field)
}

function toggle(type: ParticleTypeInfo, field: string, value: boolean) {
  const current = selectionFor(type)
  if (value === current.includes(field)) {
    return
  }

  selected = {
    ...selected,
    [type.type]: value ? [...current, field] : current.filter((name) => name !== field),
  }
}

/** Land a chart widget for `type`'s checked fields into a workspace's stored layout.

Reads the workspace fresh rather than trusting the strip's own, only periodically refreshed,
copy. A pending edit for this user that still matches is discarded, a diverging one is warned about.
*/
async function chartIntoExisting(targetId: string, row: WidgetRow): Promise<Workspace> {
  const current = await workspaces.get(targetId)
  const landed = await workspaces.update(targetId, {
    data: { ...current.data, layout: [...current.data.layout, row] },
  })

  const edit = await workspaces.getEdit(targetId)
  if (edit != null) {
    if (isStructurallyEqual(withoutMeta(edit.data), withoutMeta(current.data))) {
      await workspaces.discardEdit(targetId)
    } else {
      notify.warn('This workspace has unsaved edits that do not yet show the new chart.')
    }
  }

  return landed
}

/** Build a chart widget for `type`'s checked fields and land it on the component's strip.

With a workspace already showing there, the chart joins it. With none, a new private workspace
placed on this component carries it since a one-click action should not decide to publish.
*/
async function chart(type: ParticleTypeInfo) {
  const fields = selectionFor(type)
  if (fields.length === 0) {
    return
  }

  const widget = createWidget('chart') as ChartWidget
  widget.particles = [
    ChartWidgetParticleModel.parse({
      address: new AddressSelector(address.toString()),
      type: type.type,
      series: fields.map((field) => ({ field })),
    }),
  ]

  const row = WidgetRowModel.parse({
    widgets: [widget],
    height: getWidgetInfo('chart').options.minHeight,
  })

  try {
    const targetId = scopedWorkspaces[0]?.id
    const landed =
      targetId != null
        ? await chartIntoExisting(targetId, row)
        : await workspaces.create({
            scope: address.toString(),
            owner_id: auth.user?.id,
            data: { layout: [row] },
          })

    notify.success('Chart added to a workspace on this component.')
    emit('charted', landed.id)
  } catch {
    notify.error('Failed to add the chart.')
  }
}
</script>

<template>
  <q-list v-if="types.length > 0" bordered class="q-mt-md rounded-borders" dense>
    <q-expansion-item v-model="expanded" dense dense-toggle :label="`Particles (${types.length})`">
      <q-list class="q-pb-sm" dense>
        <q-expansion-item
          v-for="type in types"
          :key="type.type"
          :caption="type.description ?? undefined"
          dense
          dense-toggle
          :label="type.type"
        >
          <q-list dense>
            <q-item v-for="field in type.fields" :key="field.name" v-ripple tag="label">
              <q-item-section side>
                <q-checkbox
                  dense
                  :disable="!isPlottable(field.schema as Schema)"
                  :model-value="isSelected(type, field.name)"
                  @update:model-value="(value) => toggle(type, field.name, Boolean(value))"
                />
              </q-item-section>
              <q-item-section>
                <q-item-label>{{ field.name }}</q-item-label>
                <q-item-label caption>
                  <span class="monospace-sm">{{ describeType(field.schema as Schema) }}</span>
                  <span v-if="describeField(field.schema)">
                    &nbsp;&middot; {{ describeField(field.schema) }}
                  </span>
                </q-item-label>
              </q-item-section>
            </q-item>
          </q-list>
          <div class="q-pa-sm text-right">
            <q-btn
              color="primary"
              dense
              :disable="selectionFor(type).length === 0"
              :icon="icons.chart"
              label="Chart"
              @click="chart(type)"
            />
          </div>
        </q-expansion-item>
      </q-list>
    </q-expansion-item>
  </q-list>
</template>
