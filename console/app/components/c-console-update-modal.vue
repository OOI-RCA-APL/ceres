<script lang="ts" setup>
import { reloadNuxtApp } from '#app'
import { useConsoleVersion } from '@/console-version'

const consoleVersion = useConsoleVersion()

function reload() {
  reloadNuxtApp({ force: true })
}
</script>

<template>
  <!-- Not dismissible, since an outdated page can save workspace data it misreads. -->
  <c-modal
    :close="false"
    :dismissible="false"
    :open="consoleVersion.outdated"
    title="Ceres Updated"
  >
    <template #body>
      <c-text element="p" variant="body2">
        The engine now runs Ceres {{ consoleVersion.served }}, and this page still runs
        {{ consoleVersion.running }}. Reload to use the new console.
      </c-text>
    </template>
    <template #footer>
      <div class="flex w-full justify-end">
        <c-button @click="reload">Reload</c-button>
      </div>
    </template>
  </c-modal>
</template>
