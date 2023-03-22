<template>
  <section-card :title="component.name">
    <div class="row">
      <div class="col-shrink q-pa-sm">
        <q-card bordered flat>
          <q-list class="col-shrink" dense separator>
            <q-item
              v-for="procedure in procedures"
              :key="procedure.name"
              :active="selected?.name === procedure.name"
              clickable
              @click="selected = procedure"
            >
              <q-item-section>
                <q-item-label>
                  {{ procedure.name }}
                </q-item-label>
              </q-item-section>
            </q-item>
          </q-list>
        </q-card>
      </div>
      <q-separator vertical />
      <div class="col q-pa-sm">
        <schema-form v-if="selected" :key="selected.name" :schema="selected.args.json_schema" />
        <div class="q-col-gutter-sm q-pt-sm row">
          <div>
            <q-btn class="full-width" color="primary" label="Run" />
          </div>
          <div>
            <q-btn class="full-width" color="warning" flat label="Reset" />
          </div>
        </div>
        <q-card bordered class="q-mt-sm" flat title="Result">
          <div class="q-pa-sm text-center" style="opacity: 0.5">
            Unsubmitted, run to get results.
          </div>
        </q-card>
      </div>
    </div>
  </section-card>
</template>

<script lang="ts" setup>
import { ComponentInfo, ProcedureKind } from '@/api/models'
import SchemaForm from '@/components/SchemaForm.vue'
import SectionCard from '@/components/SectionCard.vue'

const { component, kind } = defineProps<{
  component: ComponentInfo
  kind: ProcedureKind
}>()

const actions = $computed(() =>
  component.procedures.filter((procedure) => procedure.kind === 'action')
)
const queries = $computed(() =>
  component.procedures.filter((procedure) => procedure.kind === 'query')
)

const procedures = $computed(() => (kind === 'action' ? actions : queries))

let selected = $ref(procedures[0] ?? null)
</script>
