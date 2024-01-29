<script lang="ts" setup>
import CommonText from '@/components/CommonText.vue'
import icons from '@/icons'
import { useNavigation } from '@/navigation'

defineProps<{
  title: string
}>()

const navigation = useNavigation()
</script>

<template>
  <q-page class="self-page">
    <q-card bordered class="self-card" flat>
      <div class="items-center q-pr-md row self-header">
        <q-btn
          class="gt-xs self-back-button"
          fab-mini
          flat
          :icon="icons.arrowBack"
          text-color="black"
          @click="navigation.back()"
        >
          <q-tooltip>Back</q-tooltip>
        </q-btn>
        <common-text class="q-mx-md q-my-sm" element="h1" variant="title1">{{ title }}</common-text>
        <slot name="header-append" />
      </div>
      <q-separator />
      <slot />
    </q-card>
  </q-page>
</template>

<style lang="scss" scoped>
.self-page {
  align-items: center;
  display: flex;
  flex-direction: column;
  padding-bottom: 40px;
  padding-left: 8px;
  padding-right: 8px;
  padding-top: 40px;
}

@media (max-width: $breakpoint-xs-max) {
  .self-page {
    padding-bottom: 16px;
    padding-top: 16px;
  }
}

.self-card {
  max-width: 440px;
  width: 100%;
}

.self-header {
  position: relative;
}

.self-back-button {
  position: absolute;
  top: 11px;
  left: -50px;
  opacity: 0.3;
  transition: opacity 0.25s;
}

.self-back-button:hover {
  opacity: 0.5;
}
</style>
