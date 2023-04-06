<script lang="ts" setup>
import { ComponentInfo, LayoutDisplay } from '@/api/models'
import { useDisplayStream } from '@/api/operations'
import DisplayContent from '@/components/DisplayContent.vue'
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
let isShowingConfig = $ref(false)

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
    <display-content :display="display" :info="info" />
    <q-dialog v-if="form" v-model="isShowingConfig">
      <q-card bordered :class="[$style.dialogContainer, 'q-pa-sm', 'no-shadow']">
        <div class="q-pb-sm">
          <q-card bordered flat>
            <display-content :display="display" :info="info" />
          </q-card>
        </div>
        <div>
          <schema-form :form="form" />
        </div>
        <div class="q-col-gutter-sm q-mt-xs row">
          <div class="col">
            <q-btn v-close-popup class="full-width" color="primary" flat label="Done" />
          </div>
          <div class="col">
            <q-btn class="full-width" color="warning" flat label="Reset" @click="form?.reset" />
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
      @click="isShowingConfig = !isShowingConfig"
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
  width: 600px;
  max-width: 100%;
}
</style>
