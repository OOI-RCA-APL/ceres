<script lang="ts" setup>
import { useEngine } from '@/api/engine'
import { guard, NotFoundError } from '@/errors'
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

const form = useForm({
  editing: group == null,
  data: {
    name: '',
    description: '',
  },
  validators: {
    name: validate.isNotEmpty('A group name is required.'),
  },
  async onSubmit(data) {
    if (id == null) {
      const created = await guard(engine.groups.create(data), {
        'already-exists-error': () => notify.error(`Group "${data.name}" already exists.`),
      })

      notify.success(`Group "${created.name}" created successfully.`)
      await navigation.go(`/groups/${created.id}`)
      return
    }

    await guard(engine.groups.update(id, data), {
      'already-exists-error': () => notify.error(`Group "${data.name}" already exists.`),
    })

    notify.success(`Group "${data.name}" updated successfully.`)
    form.done(data)
  },
})

form.load({ ...group })

const title = $computed(() =>
  group == null ? 'Create Group' : form.data.name.trim() || group.name,
)
</script>

<template>
  <c-card-page :title>
    <form @submit.prevent="form.submit()">
      <div class="flex flex-col gap-3 p-4">
        <c-form-field description="A unique name for this group." label="Name">
          <c-input
            v-model="form.data.name"
            class="w-full"
            :disabled="form.readonly"
            :icon="icons.group"
            :spellcheck="false"
          />
        </c-form-field>
        <c-form-field
          description="An optional description of this group's purpose."
          label="Description"
        >
          <c-textarea
            v-model="form.data.description"
            class="w-full"
            :disabled="form.readonly"
            :spellcheck="false"
          />
        </c-form-field>
      </div>
      <c-separator />
      <div class="flex gap-2 p-4">
        <template v-if="group">
          <c-button
            v-if="form.state === 'viewing'"
            block
            class="flex-1"
            :icon="icons.edit"
            label="Edit"
            @click="form.edit()"
          />
          <template v-else>
            <c-button
              block
              class="flex-1"
              color="neutral"
              :icon="icons.cancel"
              label="Cancel"
              @click="form.discard()"
            />
            <c-button
              block
              class="flex-1"
              :disabled="form.validation !== 'valid'"
              :icon="icons.submit"
              label="Update"
              @click="form.submit()"
            />
          </template>
        </template>
        <c-button
          v-else
          block
          :disabled="form.validation !== 'valid'"
          :icon="icons.submit"
          label="Create"
          :loading="form.state === 'submitting'"
          @click="form.submit()"
        />
      </div>
    </form>
    <template #sections>
      <!-- The sections below describe the stored group, so they stand down while it is being
      edited rather than describing something that may be about to change. -->
      <slot v-if="form.state !== 'editing'" />
    </template>
  </c-card-page>
</template>
