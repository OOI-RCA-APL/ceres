<template>
  <q-card bordered flat>
    <div class="items-center no-wrap q-px-md q-py-sm row">
      <template v-if="to">
        <router-link class="wrapper-link" :to="to">
          <common-text class="text-capitalize text-no-wrap" variant="title2">
            {{ title }}
          </common-text>
        </router-link>
      </template>
      <template v-else>
        <common-text class="text-capitalize text-no-wrap" variant="title2">
          {{ title }}
        </common-text>
      </template>
      <template v-if="icon">
        <q-space />
        <q-icon :name="icon" size="20px" />
      </template>
      <slot name="header-append" />
    </div>
    <template v-if="$slots.default && !noBody">
      <q-separator :class="padding ? 'q-mb-md' : ''" />
      <q-card-section v-if="title || icon" :class="padding ? 'q-pt-none' : 'q-py-none'">
        <slot v-if="padding" />
      </q-card-section>
      <slot v-if="!padding" />
    </template>
  </q-card>
</template>

<script lang="ts" setup>
import CommonText from './CommonText.vue'
const { padding = false, noBody = false } = defineProps<{
  icon?: string
  padding?: boolean
  title?: string
  to?: string
  noBody?: boolean
}>()
</script>

<style lang="scss" scoped>
.self-title {
  padding: 0;
  margin: 0;
}
</style>
