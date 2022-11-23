<template>
  <q-dialog
    :model-value="modelValue"
    @update:model-value="(value) => emit('update:modelValue', value)"
  >
    <section-card class="self-card" padding title="Scripts">
      <template #header-append>
        <q-space />
        <q-btn
          color="grey-8"
          dense
          flat
          :icon="icons.close"
          round
          @click="emit('update:modelValue', false)"
        />
      </template>
      <div class="q-mb-md row">
        <q-select
          v-model="selectedScriptName"
          class="col-grow"
          clearable
          dense
          hint="Select a script to run, edit or delete."
          label="Script"
          :options="scripts.map((script) => script.name)"
          options-dense
          outlined
        />
        <div class="q-ml-sm q-mt-xs">
          <q-btn
            v-if="selectedScriptName != null"
            color="negative"
            dense
            flat
            :icon="icons.delete"
            round
            @click="promptDelete"
          />
          <q-btn color="primary" dense flat :icon="icons.add" round>
            <q-menu v-model="isShowingCreateMenu">
              <q-card class="q-pa-sm">
                <q-input
                  v-model="createForm.data.name"
                  class="q-mb-sm"
                  dense
                  hint="Unique name of the script."
                  label="Name"
                  lazy-rules
                  outlined
                  :spellcheck="false"
                />
                <q-btn
                  class="full-width"
                  color="primary"
                  dense
                  :disable="createForm.validation !== 'valid'"
                  label="Create"
                  @click="createForm.submit"
                />
              </q-card>
            </q-menu>
          </q-btn>
        </div>
      </div>
      <q-form :ref="runForm.bind">
        <q-input
          v-model="runForm.data.script"
          autogrow
          class="q-mb-md"
          dense
          hint="The series of steps to execute. You can edit the steps before submitting."
          input-class="run-script-dialog-button-script-input"
          label="Steps"
          lazy-rules
          outlined
          :readonly="runForm.readonly"
          :spellcheck="false"
          type="textarea"
          @clear="runForm.data.script = ''"
        />
        <q-btn-group spread>
          <q-btn
            color="primary"
            dense
            :disable="
              runForm.state !== 'editing' ||
              selectedScriptName == null ||
              runForm.data.script === selectedScript?.content
            "
            label="Save"
            @click="promptSave"
          />
          <q-btn
            color="primary"
            dense
            label="Run"
            :loading="runForm.state === 'submitting'"
            @click="runForm.submit"
          />
        </q-btn-group>
      </q-form>
    </section-card>
  </q-dialog>
</template>

<script lang="ts" setup>
import { useForm } from '@/form'
import SectionCard from '@/components/SectionCard.vue'
import icons from '@/icons'
import { useQuasar } from 'quasar'
import { watchEffect } from 'vue'

const { modelValue = false } = defineProps<{
  modelValue?: boolean
}>()

const emit = defineEmits<{
  (emit: 'update:modelValue', value: boolean): void
}>()

const quasar = useQuasar()

let scripts = $ref([
  {
    name: 'reboot',
    content: ['CONNECTION control', 'SEND <REBOOT', 'RECEIVE .*, 60s'].join('\n'),
  },
  {
    name: 'get-status',
    content: ['CONNECTION control', 'SEND <STATUS', 'RECEIVE >STATUS:.*, 10s'].join('\n'),
  },
])
let isShowingCreateMenu = $ref(false)

let selectedScriptName: string | null = $ref(null)
const selectedScript = $computed(
  () => scripts.find((script) => script.name === selectedScriptName) ?? null
)

const runForm = useForm({
  data: {
    script: '',
  },
  onSubmit: async () => {
    quasar.notify({
      type: 'positive',
      message: 'Script completed successfully.',
    })
  },
})

const createForm = useForm({
  data: {
    name: '',
  },
  validators: {
    name: (name) => (name != null && /^[A-Za-z0-9]+$/.test(name)) || 'Invalid script name.',
  },
  onSubmit: async (data) => {
    quasar.notify({
      type: 'positive',
      message: 'Script created successfully.',
    })

    isShowingCreateMenu = false
    selectedScriptName = data.name
    isShowingCreateMenu = false
    scripts.push({
      name: data.name,
      content: '',
    })
  },
})

function promptDelete() {
  if (selectedScriptName == null) {
    return
  }

  async function execute() {
    if (selectedScriptName) {
      scripts = scripts.filter((script) => script.name !== selectedScriptName)
    }

    quasar.notify({
      type: 'positive',
      message: 'Script deleted successfully.',
    })

    selectedScriptName = null
  }

  quasar
    .dialog({
      title: 'Delete Script',
      message: `Permanently delete the script "${selectedScriptName}"?`,
      ok: {
        label: 'Delete',
        color: 'negative',
      },
      cancel: {
        label: 'Cancel',
        color: 'grey',
      },
    })
    .onOk(() => void execute())
}

function promptSave() {
  if (selectedScriptName == null) {
    return
  }

  async function execute() {
    const script = selectedScript
    if (script == null) {
      return
    }

    script.content = runForm.data.script

    quasar.notify({
      type: 'positive',
      message: 'Script saved successfully.',
    })
  }

  quasar
    .dialog({
      title: 'Save Script',
      message: `Save changes to script "${selectedScriptName}"?`,
      ok: {
        label: 'Save',
        color: 'primary',
      },
      cancel: {
        label: 'Cancel',
        color: 'grey',
      },
    })
    .onOk(() => void execute())
}

watchEffect(() => {
  if (selectedScript) {
    runForm.data.script = selectedScript.content
  }
})
</script>

<style lang="scss" scoped>
.self-card {
  max-width: 660px;
  width: 100%;
}
</style>

<style lang="scss">
.run-script-dialog-button-script-input {
  font-family: 'Roboto Mono', monospace;
  font-size: 13px;
  overflow-wrap: normal;
  overflow-x: scroll;
  white-space: pre;
}
</style>
