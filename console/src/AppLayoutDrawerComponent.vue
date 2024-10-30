<script lang="ts" setup>
import AppLayoutDrawerComponent from '@/AppLayoutDrawerComponent.vue'
import { Address } from '@/api/address'
import { ComponentInfo } from '@/api/components'
import AlertsIndicator from '@/components/AlertsIndicator.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import { useDrawer } from '@/drawer'
import icons from '@/icons'

const { address, component } = $defineProps<{
  address: Address
  component: ComponentInfo
}>()

const drawer = useDrawer()

const isExpanded = $computed(() => !drawer.collapsed.some((current) => current.equals(address)))
const isRoot = $computed(() => address.isRoot)
const isLeaf = $computed(() => !isRoot && component.components.length === 0)

function toggleExpanded() {
  if (isExpanded) {
    drawer.collapsed = [...drawer.collapsed, address]
  } else {
    drawer.collapsed = drawer.collapsed.filter((current) => !current.equals(address))
  }
}
</script>

<template>
  <q-item :class="[$style.root, 'items-center', 'row']" :dense="address.depth > 0">
    <div
      :class="[$style.iconContainer, 'items-center', 'justify-center', 'row']"
      :style="{ marginLeft: `${8 * address.depth}px` }"
    >
      <q-icon v-if="isLeaf" :class="$style.left" :name="icons.circle" size="7px" />
      <q-btn
        v-else
        :class="$style.left"
        flat
        round
        size="xs"
        :tabindex="isLeaf ? -1 : 0"
        @click.stop.prevent="isLeaf ? undefined : toggleExpanded()"
      >
        <q-icon :name="isExpanded ? icons.menuDown : icons.menuRight" size="22px" />
      </q-btn>
    </div>
    <q-item-section no-wrap>
      <q-item-label class="q-ml-md text-no-wrap">
        {{ address.isRoot ? 'Components' : component.name }}
      </q-item-label>
    </q-item-section>
    <q-item-section side>
      <div class="items-center q-mr-xs row">
        <alerts-indicator :address class="q-mr-xs" />
        <status-badge :address />
      </div>
    </q-item-section>
  </q-item>
  <div v-if="!isLeaf && isExpanded">
    <app-layout-drawer-component
      v-for="subcomponent in component.components"
      :key="subcomponent.name"
      :address="address.append(subcomponent.name)"
      :component="subcomponent"
    />
  </div>
</template>

<style module>
.root {
  min-height: 38px;
}

.left {
  margin-left: -16px;
}

.iconContainer {
  min-width: 40px;
}
</style>
