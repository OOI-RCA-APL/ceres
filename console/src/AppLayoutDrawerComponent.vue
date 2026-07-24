<script lang="ts" setup>
import AppLayoutDrawerComponent from '@/AppLayoutDrawerComponent.vue'
import { useAccess } from '@/api/access'
import { Address } from '@/api/address'
import { ComponentInfo } from '@/api/components'
import AlertsIndicator from '@/components/AlertsIndicator.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import { useDrawer } from '@/drawer'
import icons from '@/icons'

const { address, component } = defineProps<{
  address: Address
  component: ComponentInfo
}>()

const drawer = useDrawer()
const access = useAccess()

const badge = $ref<InstanceType<typeof StatusBadge> | null>(null)

// Components the user can only look at read slightly quieter than the ones they can control.
const canControl = $computed(() => access.canOperate(address.toString()))

const isExpanded = $computed(() => !drawer.collapsed.some((current) => current.equals(address)))
const isTopLevel = $computed(() => address.depth === 1)
const isLeaf = $computed(() => component.components.length === 0)

function toggleExpanded() {
  if (isExpanded) {
    drawer.collapsed = [...drawer.collapsed, address]
  } else {
    drawer.collapsed = drawer.collapsed.filter((current) => !current.equals(address))
  }
}
</script>

<template>
  <q-item
    :class="[$style.root, 'items-center', 'row']"
    clickable
    dense
    :to="`/components/${address}`"
  >
    <div
      :class="[$style.iconContainer, 'items-center', 'justify-center', 'row']"
      :style="{ marginLeft: `${8 * address.depth}px` }"
    >
      <q-icon v-if="isLeaf" :class="$style.left" :name="icons.circle" size="6px" />
      <q-btn
        v-else
        :class="$style.left"
        flat
        round
        size="xs"
        :tabindex="isLeaf ? -1 : 0"
        @click.stop.prevent="isLeaf ? undefined : toggleExpanded()"
      >
        <q-icon :name="isExpanded ? icons.menuDown : icons.menuRight" size="18px" />
      </q-btn>
    </div>
    <q-item-section no-wrap>
      <q-item-label
        :class="['q-ml-md', 'text-no-wrap', !canControl && $style.readonly]"
        :style="!isTopLevel && { paddingLeft: '1.5px' }"
      >
        {{ isTopLevel ? component.address : '.' + component.name }}
      </q-item-label>
    </q-item-section>
    <q-item-section side>
      <div
        :class="[$style.status, 'items-center', 'justify-end', 'q-mr-xs', 'row']"
        @mouseenter="badge?.menu.onEnter()"
        @mouseleave="badge?.menu.onLeave()"
      >
        <alerts-indicator :address class="q-mr-xs" />
        <status-badge ref="badge" :address />
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
.left {
  margin-left: -22px;
}

.iconContainer {
  min-width: 40px;
}

.readonly {
  opacity: 0.9;
}

/* Reserve the width an indicator would take so every row has the same status hover target. */
.status {
  min-width: 56px;
}
</style>
