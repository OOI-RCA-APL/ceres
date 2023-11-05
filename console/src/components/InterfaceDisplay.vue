<script lang="ts" setup>
import { ComponentInfo, DisplayElement, Element } from '@/api/models'
import { useElementStream } from '@/api/operations'
import InterfaceDisplayContent from '@/components/InterfaceDisplayContent.vue'
import SchemaForm from '@/components/schema-form/SchemaForm.vue'
import { InterfacePath } from '@/interface'
import { useSchemaForm } from '@/schema-form'
import { debounce } from 'quasar'
import { computed, watch } from 'vue'

const {
  component,
  element,
  path,
  noConfig = false,
} = defineProps<{
  component: ComponentInfo
  element: DisplayElement
  path: InterfacePath
  noConfig?: boolean
}>()

let rendered: Element | null = $shallowRef(null)
let isLoading = $ref(true)
let isShowingDialog = $ref(false)

const query = $computed(
  () =>
    component.procedures.find(
      (procedure) => procedure.type === 'query' && procedure.name === element.query
    ) ?? null
)

const form = query
  ? useSchemaForm({
      schema: computed(() => query.arguments.json_schema),
      persist: computed(() =>
        query
          ? `state/display/schema-form/${component.address}/display/${query.name}/${path.join(
              '.'
            )})`
          : undefined
      ),
    })
  : null

if (form && !form.isValid) {
  form.reset()
}

let args = $ref<Record<string, unknown>>(form?.value ?? ({} as any))

watch(
  () => JSON.stringify(form?.value),
  debounce(() => {
    args = form?.value ?? ({} as any)
    isLoading = true
  }, 250)
)

useElementStream(
  component.address,
  element.query,
  computed(() => args),
  (current) => {
    rendered = current
    isLoading = false
  }
)

const configButtonColor = $computed(() => {
  if (!form) {
    return undefined
  }
  if (!form.isValid) {
    return 'negative'
  }

  return 'primary'
})
</script>

<template>
  <q-card
    bordered
    :class="[$q.dark.isActive && $style.dark, 'column', 'full-height', 'relative-position']"
    flat
  >
    <interface-display-content
      :component="component"
      :display="element"
      :element="rendered"
      :path="path"
      title-clickable
      @title-click="isShowingDialog = !isShowingDialog"
    />
    <q-dialog v-if="form" v-model="isShowingDialog" full-width>
      <q-card bordered :class="[$style.dialogContainer, $q.dark.isActive && 'no-shadow']">
        <interface-display-content
          :component="component"
          :display="element"
          :element="rendered"
          :is-loading="isLoading"
          :path="path"
        />
        <q-separator />
        <template v-if="!form.isEmpty">
          <div class="q-pt-sm q-px-sm">
            <schema-form :form="form" />
          </div>
          <q-separator class="q-mt-sm" />
        </template>
        <div class="justify-center row">
          <div class="col">
            <q-btn v-close-popup class="full-width" color="primary" flat label="Done" square />
          </div>
          <div v-if="!form.isEmpty" class="col">
            <q-btn
              class="full-width"
              color="warning"
              :disable="form.isInitialValue"
              flat
              label="Reset"
              square
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
.dark {
  background-color: #131313;
}

.configButton {
  position: absolute;
  right: 2px;
  top: 1px;
}
</style>
