<script lang="ts" setup>
import { ComponentInfo, ProcedureKind } from '@/api/models'
import ComponentProcedure from '@/components/ComponentProcedure.vue'
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
        <template v-if="selected">
          <component-procedure :key="selected.name" :component="component" :procedure="selected" />
        </template>
      </div>
    </div>
  </section-card>
</template>
