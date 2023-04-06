<script lang="ts" setup>
import { ComponentInfo, LayoutDisplay } from '@/api/models'
import { useDisplayStream } from '@/api/operations'
import DisplayContent from '@/components/DisplayContent.vue'
import SectionCard from '@/components/SectionCard.vue'
import SchemaForm from '@/components/schema-form/SchemaForm.vue'
import { DisplayInfo } from '@/display'
import { createSchemaForm } from '@/schema-form'
import { debounce } from 'quasar'
import { computed, watch } from 'vue'

const {
  component,
  display,
  noConfig = false,
} = defineProps<{
  component: ComponentInfo
  display: LayoutDisplay
  noConfig?: boolean
}>()

let info: DisplayInfo | null = $shallowRef(null)
let isShowingDialog = $ref(false)

const procedure = $computed(
  () =>
    component.procedures.find(
      (procedure) => procedure.kind === 'query' && procedure.name === display.procedure
    ) ?? null
)

const form = procedure
  ? createSchemaForm({
      schema: computed(() => procedure.args.json_schema),
      persist: computed(() =>
        procedure
          ? `state/display/schema-form/${component.address}/procedures/${procedure.name})`
          : undefined
      ),
    })
  : null

if (form && !form.isValid) {
  form.reset()
}

let args = $ref<Record<string, unknown>>(form?.value ?? ({} as any))

watch(
  () => form?.value,
  debounce(() => {
    args = form?.value ?? ({} as any)
  }, 250)
)

useDisplayStream(
  component.address,
  display.procedure,
  computed(() => args),
  (current) => {
    info = current
  }
)

const configButtonColor = $computed(() => {
  if (!form) {
    return undefined
  }
  if (!form.isValid) {
    return 'negative'
  }
  if (!form.isDefault) {
    return 'primary'
  }

  return undefined
})
</script>

<template>
  <q-card bordered class="column full-height relative-position" flat>
    <display-content
      :display="display"
      :info="info"
      title-clickable
      @title-click="isShowingDialog = !isShowingDialog"
    />
    <q-dialog v-if="form" v-model="isShowingDialog">
      <q-card
        bordered
        :class="[$style.dialogContainer, 'q-pa-sm', $q.dark.isActive && 'no-shadow']"
      >
        <div class="q-mb-sm">
          <section-card padding title="Display">
            <q-card bordered flat>
              <display-content :display="display" :info="info" />
            </q-card>
          </section-card>
        </div>
        <div v-if="!form.isEmpty" class="q-mb-sm">
          <section-card padding title="Configuration">
            <schema-form :form="form" />
          </section-card>
        </div>
        <div class="q-col-gutter-sm row">
          <div class="col">
            <q-btn v-close-popup class="full-width" color="primary" flat label="Done" />
          </div>
          <div v-if="!form.isEmpty" class="col">
            <q-btn
              class="full-width"
              color="warning"
              :disable="form.isDefault"
              flat
              label="Reset"
              @click="form?.reset"
            />
          </div>
        </div>
      </q-card>
    </q-dialog>
    <q-btn
      v-if="!noConfig && form && !form.isEmpty"
      :class="$style.configButton"
      :color="configButtonColor"
      flat
      icon="settings"
      round
      size="xs"
      @click="isShowingDialog = !isShowingDialog"
    />
  </q-card>
</template>

<style module>
.configButton {
  position: absolute;
  right: 2px;
  top: 1px;
}

.dialogContainer {
  min-width: 800px;
  max-width: 100%;
}
</style>
