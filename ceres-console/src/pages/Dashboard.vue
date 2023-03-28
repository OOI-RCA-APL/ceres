<script lang="ts" setup>
import { reload, useMutation } from '@/api/operations'
import CommonText from '@/components/CommonText.vue'
import SectionCard from '@/components/SectionCard.vue'

const reloadMutation = useMutation('reload', async () => {
  await reload()
})
</script>

<template>
  <div>
    <div>
      <common-text class="q-ml-md q-py-sm" variant="title2">Dashboard</common-text>
      <q-separator />
    </div>
    <div class="q-ma-md">
      <section-card padding title="Actions">
        <div class="q-gutter-sm row">
          <q-btn
            color="primary"
            label="Reload"
            :loading="reloadMutation.isLoading.value"
            @click="reloadMutation.mutate()"
          />
        </div>
      </section-card>
    </div>
  </div>
</template>
