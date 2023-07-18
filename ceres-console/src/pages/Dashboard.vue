<script lang="ts" setup>
import { reload, useConfig, useMutation } from '@/api/operations'
import CommonText from '@/components/CommonText.vue'
import SectionCard from '@/components/SectionCard.vue'
import { useQuasar } from 'quasar'

const quasar = useQuasar()
const config = useConfig()

const reloadMutation = useMutation('reload', async () => {
  return await reload()
})

async function executeReload() {
  const result = await reloadMutation.mutateAsync()
  if (result.ok) {
    quasar.notify({
      message: 'Configuration reloaded successfully.',
      type: 'positive',
    })

    await config.refetch()
  } else {
    quasar.notify({
      message: 'Configuration reload failed.',
      type: 'negative',
      actions: [
        {
          label: 'Details',
          color: 'white',
          handler: () =>
            quasar.dialog({
              title: 'Error Details',
              message: `
<div class="full-width monospace-sm overflow-auto scroll" style="white-space: pre">
  ${JSON.stringify(result.error, null, 4)}
</div>
              `.trim(),
              html: true,
            }),
        },
      ],
    })
  }
}

function promptReload() {
  quasar
    .dialog({
      title: 'Reload',
      message: 'Are you sure you want to reload the server configuration?',
      class: 'no-shadow',
      componentProps: {
        outline: true,
      },
      cancel: true,
      ok: {
        label: 'Reload',
        color: 'primary',
      },
    })
    .onOk(async () => {
      await executeReload()
    })
}
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
            @click="promptReload"
          />
        </div>
      </section-card>
    </div>
  </div>
</template>
