<script lang="ts" setup>
import { onMounted } from 'vue'

import { useEngine } from '@/api/engine'
import icons from '@/icons'

const engine = useEngine()

onMounted(() => engine.auth.loadFeatures())

const authority = $computed(() => engine.auth.authority)

// Two lines of sixteen bytes, the way certificate viewers wrap a fingerprint, so the halves
// compare at a glance.
const fingerprint = $computed(() => {
  const bytes = authority?.fingerprint.split(':') ?? []
  return [bytes.slice(0, 16), bytes.slice(16)].map((half) => half.join(':')).join('\n')
})

// One entry per platform, each the shortest path to trusting the authority for websites.
const steps = [
  {
    platform: 'macOS',
    text: 'Open the downloaded file to add it to Keychain Access. Open it there, expand Trust, and set "When using this certificate" to Always Trust.',
  },
  {
    platform: 'Windows',
    text: 'Open the downloaded file, choose Install Certificate, and place it in Trusted Root Certification Authorities.',
  },
  {
    platform: 'iPhone and iPad',
    text: 'Open the downloaded file and install the profile under Settings > General > VPN & Device Management. Then turn on full trust for it under Settings > General > About > Certificate Trust Settings.',
  },
  {
    platform: 'Android',
    text: 'Install the downloaded file under Settings > Security > Encryption & credentials > Install a certificate > CA certificate.',
  },
  {
    platform: 'Firefox',
    text: 'Firefox keeps its own list. Under Settings > Privacy & Security > Certificates, choose View Certificates, import the file on the Authorities tab, and check "Trust this CA to identify websites".',
  },
]
</script>

<template>
  <c-card-page title="Trust this server?">
    <div v-if="authority != null" class="flex flex-col gap-4 p-4">
      <c-text variant="body2">
        This server's certificate is signed by its own certificate authority. Trust the authority
        once on each device, and browsers accept the server without a warning from then on.
      </c-text>
      <c-button
        block
        color="primary"
        download
        external
        :icon="icons.export"
        label="Download Certificate"
        to="/ca.crt"
      />
      <div class="flex flex-col gap-1">
        <c-text variant="th">SHA-256 fingerprint</c-text>
        <c-text data-fingerprint variant="mono-xs">{{ fingerprint }}</c-text>
        <c-text variant="description">
          Compare it with the fingerprint your device shows before trusting the file.
        </c-text>
      </div>
    </div>
    <div v-else class="p-4">
      <c-text variant="body2">
        This server does not manage its own certificate, so there is no authority to download.
      </c-text>
    </div>
    <template v-if="authority != null">
      <c-separator />
      <dl class="flex flex-col gap-3 p-4">
        <div v-for="step in steps" :key="step.platform">
          <dt>
            <c-text variant="th">{{ step.platform }}</c-text>
          </dt>
          <dd>
            <c-text class="text-muted" variant="body3">{{ step.text }}</c-text>
          </dd>
        </div>
      </dl>
    </template>
  </c-card-page>
</template>
