<script lang="ts" setup>
import AlertsIndicator from '@/components/AlertsIndicator.vue'
import StatusBadgeAggregate from '@/components/StatusBadgeAggregate.vue'
</script>

<template>
  <q-item class="items-center row" dense>
    <div :class="[$style.iconContainer, 'items-center', 'justify-center', 'row']" />
    <q-item-section no-wrap>
      <q-item-label class="q-ml-md text-no-wrap">Components</q-item-label>
    </q-item-section>
    <q-item-section side>
      <div class="items-center q-mr-xs row">
        <alerts-indicator class="q-mr-xs" />
        <status-badge-aggregate />
      </div>
    </q-item-section>
  </q-item>
</template>

<style module>
.iconContainer {
  min-width: 40px;
}
</style>
