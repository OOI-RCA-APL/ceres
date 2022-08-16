<template>
  <div class="items-center q-gutter-sm row">
    <div>
      <q-btn
        color="primary"
        dense
        flat
        :icon="icons.job"
        label="Jobs"
        @click="isShowingJobsDialog = true"
      >
        <jobs-dialog v-model="isShowingJobsDialog" />
      </q-btn>
    </div>
    <div>
      <q-btn
        color="primary"
        dense
        flat
        :icon="icons.script"
        label="Scripts"
        @click="isShowingScriptsDialog = true"
      >
        <scripts-dialog v-model="isShowingScriptsDialog" />
      </q-btn>
    </div>
  </div>
</template>

<script lang="ts" setup>
import icons from '@/icons'
import JobsDialog from '@/components/JobsDialog.vue'
import ScriptsDialog from '@/components/ScriptsDialog.vue'

defineProps<{
  unitName: string
}>()

let isShowingJobsDialog = $ref(false)
let isShowingScriptsDialog = $ref(false)
</script>
