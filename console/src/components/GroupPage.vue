<script lang="ts" setup>
import { useEngine } from '@/api/engine'
import CardPage from '@/components/CardPage.vue'
import { NotFoundError, guard } from '@/errors'
import { useForm } from '@/form'
import icons from '@/icons'
import { useNavigation } from '@/navigation'
import { useNotify } from '@/notify'
import { useValidate } from '@/validate'

const { id = null } = defineProps<{
  id?: string | null
}>()

const navigation = useNavigation()
const notify = useNotify()
const validate = useValidate()
const engine = useEngine()

const group = id != null ? await engine.groups.get(id) : null
if (group == null && id != null) {
  throw new NotFoundError('group', `Group ID "${id}" does not exist.`)
}

function getTitle() {
  if (group == null) {
    return 'Create Group'
  }

  return form.data.name.trim() || group.name
}

type GroupFormData = {
  name: string
  description: string
}

const form = useForm({
  editing: group == null,
  data: <GroupFormData>{
    name: '',
    description: '',
  },
  validators: {
    name: validate.isNotEmpty('A group name is required.'),
  },
  async onSubmit(data) {
    if (id == null) {
      const created = await guard(engine.groups.create(data), [
        {
          type: 'already-exists-error',
          do: () => notify.error(`Group "${data.name}" already exists.`),
        },
      ])

      notify.success(`Group "${created.name}" created successfully.`)
      navigation.go(`/groups/${created.id}`)
      return
    }

    await guard(engine.groups.update(id, data), [
      {
        type: 'already-exists-error',
        do: () => notify.error(`Group "${data.name}" already exists.`),
      },
    ])

    notify.success(`Group "${data.name}" updated successfully.`)
    form.done(data)
  },
})

form.load({
  ...group,
})
</script>

<template>
  <card-page :title="getTitle()">
    <q-form :ref="form.bind" @submit.prevent>
      <div class="q-pa-md">
        <q-input
          v-model="form.data.name"
          class="q-mb-sm"
          dense
          hint="A unique name for this group."
          label="Name"
          lazy-rules
          outlined
          :readonly="form.readonly"
          :rules="[form.validators.name]"
          :spellcheck="false"
        >
          <template #prepend>
            <q-icon :name="icons.group" />
          </template>
        </q-input>
        <q-input
          v-model="form.data.description"
          dense
          hint="An optional description of this group's purpose."
          label="Description"
          outlined
          :readonly="form.readonly"
          :spellcheck="false"
          type="textarea"
        />
      </div>
      <q-separator />
      <div class="q-pa-md">
        <template v-if="group">
          <div class="q-gutter-sm row">
            <template v-if="form.state === 'viewing'">
              <q-btn
                class="col"
                color="primary"
                :icon="icons.edit"
                label="Edit"
                unelevated
                @click="form.edit"
              />
            </template>
            <template v-else>
              <q-btn
                class="col"
                color="grey-8"
                :icon="icons.cancel"
                label="Cancel"
                unelevated
                @click="form.discard"
              />
              <q-btn
                class="col"
                color="primary"
                :disable="form.validation !== 'valid'"
                :icon="icons.submit"
                label="Update"
                unelevated
                @click="form.submit"
              />
            </template>
          </div>
        </template>
        <template v-else>
          <q-btn-group flat spread>
            <q-btn
              color="primary"
              :disable="form.validation !== 'valid'"
              :icon="icons.submit"
              label="Create"
              :loading="form.state === 'submitting'"
              @click="form.submit"
            />
          </q-btn-group>
        </template>
      </div>
    </q-form>
    <template #sections>
      <slot v-if="form.state !== 'editing'" />
    </template>
  </card-page>
</template>
