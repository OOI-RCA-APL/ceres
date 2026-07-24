<script lang="ts" setup>
import StatusBadge from '@/components/StatusBadge.vue'
import icons from '@/icons'

const expanded = defineModel<boolean>('expanded', { default: true })
</script>

<template>
  <q-item class="items-center row" dense>
    <div :class="[$style.iconContainer, 'items-center', 'justify-center', 'row']">
      <q-btn
        :class="$style.toggleButton"
        flat
        round
        size="xs"
        tabindex="0"
        @click.stop.prevent="expanded = !expanded"
      >
        <q-icon :name="expanded ? icons.menuDown : icons.menuRight" size="18px" />
      </q-btn>
    </div>
    <q-item-section no-wrap>
      <q-item-label class="q-ml-md text-no-wrap">Components</q-item-label>
    </q-item-section>
    <q-item-section side>
      <div class="items-center q-mr-xs row">
        <status-badge />
      </div>
    </q-item-section>
  </q-item>
</template>

<style module>
.iconContainer {
  min-width: 40px;
}

.toggleButton {
  margin-left: -22px;
}
</style>
