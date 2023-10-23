<script lang="ts" setup>
import CommonText from '@/components/CommonText.vue'

const { padding = false, noBody = false } = defineProps<{
  icon?: string
  padding?: boolean | 'xs' | 'sm' | 'md' | 'lg' | 'xl'
  title?: string
  to?: string
  noBody?: boolean
}>()
</script>

<template>
  <q-card bordered class="column" flat>
    <template v-if="title">
      <div class="items-center no-wrap q-pl-md q-pr-sm q-py-xs row">
        <template v-if="to">
          <router-link class="wrapper-link" :to="to">
            <common-text class="text-no-wrap" variant="title2">
              {{ title }}
            </common-text>
          </router-link>
        </template>
        <template v-else>
          <common-text class="text-no-wrap" variant="title2">
            {{ title }}
          </common-text>
        </template>
        <template v-if="icon">
          <q-space />
          <q-icon :name="icon" size="20px" />
        </template>
        <slot name="header-append" />
      </div>
      <q-separator />
    </template>
    <div
      v-if="$slots.default && !noBody"
      :class="[
        'col-grow column',
        padding && `q-pa-${typeof padding === 'boolean' ? 'md' : padding}`,
      ]"
    >
      <slot />
    </div>
  </q-card>
</template>
