<template>
  <q-dialog
    :model-value="modelValue"
    @update:model-value="(value) => emit('update:modelValue', value)"
  >
    <section-card class="self-card" padding title="Jobs">
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
      <q-form :ref="form.bind">
        <div class="q-mb-md row">
          <div class="col-grow row">
            <q-select
              v-model="form.data.name"
              class="col-grow"
              clearable
              dense
              hint="Select a job to run."
              label="Job"
              :options="jobNames"
              options-dense
              outlined
            />
          </div>
          <div v-if="form.data.name" class="col-shrink">
            <help
              v-if="form.data.name"
              class="q-mt-sm"
              size="20px"
              :title="form.data.name.toLowerCase().split('_').map(_.upperFirst).join(' ')"
            >
              <p>A description for what the job does and any commands it runs go here.</p>
            </help>
          </div>
        </div>
        <q-btn-group spread>
          <q-btn
            color="primary"
            dense
            :disable="form.data.name == null"
            label="Run"
            :loading="form.state === 'submitting'"
            @click="form.submit"
          />
        </q-btn-group>
      </q-form>
    </section-card>
  </q-dialog>
</template>

<script lang="ts" setup>
import { useForm } from '@/form'
import Help from '@/components/Help.vue'
import SectionCard from '@/components/SectionCard.vue'
import icons from '@/icons'
import _ from 'lodash'
import { useQuasar } from 'quasar'

const { modelValue = false } = defineProps<{
  modelValue?: boolean
}>()

const jobNames = ['sync-configuration', 'power-cycle']

const emit = defineEmits<{
  (emit: 'update:modelValue', value: boolean): void
}>()

const quasar = useQuasar()

const form = useForm({
  data: {
    name: null as string | null,
  },
  onSubmit: async () => {
    quasar.notify({
      type: 'positive',
      message: 'Job completed successfully.',
    })
  },
})
</script>

<style lang="scss" scoped>
.self-card {
  max-width: 350px;
  width: 100%;
}
</style>

<style lang="scss">
.run-script-dialog-button-script-input {
  font-family: 'Roboto Mono', monospace;
  font-size: 13px;
}
</style>
