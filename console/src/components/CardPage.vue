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
  <q-page :class="$style.root">
    <q-card bordered :class="$style.card" flat>
      <div :class="[$style.header, 'items-center q-pr-md row']">
        <q-btn
          :class="[$style.backButton, 'gt-xs']"
          dense
          flat
          :icon="icons.arrowLeft"
          round
          @click="navigation.back()"
        >
          <q-tooltip :delay="500">Back</q-tooltip>
        </q-btn>
        <common-text class="q-mx-md q-my-sm" element="h1" variant="title1">{{ title }}</common-text>
        <slot name="header-append" />
      </div>
      <q-separator />
      <slot />
    </q-card>
  </q-page>
</template>

<style lang="scss" module>
.root {
  align-items: center;
  display: flex;
  flex-direction: column;
  padding-bottom: 40px;
  padding-left: 8px;
  padding-right: 8px;
  padding-top: 40px;
}

:global(.light) .root {
  background-color: $grey-1;
}

@media (max-width: $breakpoint-xs-max) {
  .page {
    padding-bottom: 16px;
    padding-top: 16px;
  }
}

.card {
  max-width: 440px;
  width: 100%;
}

.header {
  position: relative;
}

.backButton {
  position: absolute;
  top: 8px;
  left: -46px;
  opacity: 0.3;
  transition: opacity 0.25s;
}

.backButton:hover {
  opacity: 0.5;
}
</style>
